#!/usr/bin/env python3
"""Count how often every coded value actually occurs in MIMIC-on-FHIR.

Runs ONCE on a CSIRO HPC node against the full Delta warehouse, and its two
output files are then committed to this repo. Everything downstream is offline:
build_statistics.py reads code-occurrences.csv to weight the mapping coverage
tables by how much data each code carries, because missing a code used on every
admission is not the same failure as missing one used twice in 2012.

Why this and not the existing artefacts:

  scripts/binding-analysis/distinct-codes.ndjson already carries counts, but
  phase 0 filtered out every element that was ALREADY BOUND — so the three
  elements this repo maps most (Observation.code, Procedure.code, Specimen.type)
  are exactly the ones missing from it. Rather than merge two extraction runs
  against warehouse states that differ by a provisioning step, this recounts
  all seven elements in one job, with one provenance record.

  pathling_mcp_tool's get_cardinality_and_top_values_impl caps at 20 values,
  which is useless for a field whose whole story is its long tail, and it
  explodes multiple array columns independently, which cross-joins the codings
  of a multi-coding CodeableConcept instead of keeping them aligned. This uses
  the SQL-on-FHIR `forEach` that phase1_extract_distinct.py established: one row
  per Coding, system/code/display aligned by construction.

Deliberately self-contained: stdlib + pathling/pyspark only, no imports from
this repo. The node runs Python 3.12 under the REMOTE project's uv environment
(`/scratch3/nau025/mimic-on-fhir-delta`), not this repo's 3.14 one, and compute
nodes have no internet, so nothing here may resolve a dependency at run time.

Counts are keyed on (element, system, code) and NOT on meta.profile. A resource
may legitimately carry more than one profile, and grouping on an exploded
meta.profile would then count its codings once per profile. Population identity
is recoverable anyway: each unbuilt population has its own CodeSystem
(mimic-chartevents-d-items, mimic-d-labitems, mimic-microbiology-organism), so
the code's system says which population it belongs to without a profile column.

Outputs, both written to --out-dir:
  code-occurrences.csv     element,system,code,display,occurrences
  occurrence-summary.json  per-element totals + the run's identity, including
                           each Delta table's version and commit timestamp and
                           the sha256 of the CSV. build_statistics.py verifies
                           that hash, so a half-copied CSV cannot quietly enter
                           a thesis table.

Usage (on the node, via count_occurrences.slurm):
  uv run python3 occurrences/count_occurrences.py --data "$DATA" --out-dir occurrences
Dry run (laptop, no Spark, no warehouse):
  uv run python3 scripts/terminology-mapping/occurrences/count_occurrences.py --dry-run
"""

import argparse
import csv
import hashlib
import json
import os
import platform
import socket
import sys
import traceback
from datetime import datetime, timezone

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_REGISTRY = os.path.join(SCRIPT_DIR, "elements.json")

CSV_NAME = "code-occurrences.csv"
SUMMARY_NAME = "occurrence-summary.json"
CSV_COLUMNS = ["element", "system", "code", "display", "occurrences"]


def log(msg):
    """Progress to stderr, so it interleaves with Spark's own stdout noise."""
    print(msg, file=sys.stderr, flush=True)


# --------------------------------------------------------------------------- #
# Query planning — pure, shared by the dry run and the real run.
# --------------------------------------------------------------------------- #

def plan_view(element):
    """The SQL-on-FHIR view for one element: one row per Coding.

    `forEach` over the Coding collection is what keeps system/code/display
    aligned per Coding. Reading them as three independent collection columns
    would cross-join them, which is wrong for any CodeableConcept carrying more
    than one Coding — and silently right for the ones carrying exactly one,
    which is how that bug survives review.

    Resources that do not have the element contribute no rows (forEach, not
    forEachOrNull): "absent" is not a coded value and must not become one.
    """
    return {
        "resource_type": element["resource_type"],
        "select": [{
            "forEach": element["extract_path"],
            "column": [
                {"path": "system", "name": "system"},
                {"path": "code", "name": "code"},
                {"path": "display", "name": "display"},
            ],
        }],
    }


def load_registry(path, wanted=None):
    with open(path) as fh:
        elements = json.load(fh)["elements"]
    if wanted:
        keep = set(wanted)
        unknown = keep - {e["element"] for e in elements}
        if unknown:
            log(f"ERROR: unknown element(s): {', '.join(sorted(unknown))}")
            sys.exit(2)
        elements = [e for e in elements if e["element"] in keep]
    return elements


# --------------------------------------------------------------------------- #
# Dry run — must not import pyspark or pathling.
# --------------------------------------------------------------------------- #

def do_dry_run(elements):
    log(f"DRY RUN: {len(elements)} element(s) planned\n")
    for i, element in enumerate(elements, 1):
        plan = plan_view(element)
        print("=" * 70)
        print(f"[{i}] {element['element']}")
        print(f"    resource : {plan['resource_type']}")
        print(f"    forEach  : {element['extract_path']}")
        print(f"    select   : {json.dumps(plan['select'])}")
        print("    groupBy  : system, code   (display via max, for determinism)")
    print("=" * 70)
    log("\nDRY RUN complete. No Spark session was created.")
    return 0


# --------------------------------------------------------------------------- #
# Real run.
# --------------------------------------------------------------------------- #

def open_warehouse(data_path):
    """PathlingContext + the Delta warehouse.

    PathlingContext must build its own SparkSession — a pre-existing one lacks
    the Pathling JVM libraries on the classpath, which surfaces as the
    thoroughly unhelpful "TypeError: 'JavaPackage' object is not callable".
    """
    from pathling import PathlingContext

    pc = PathlingContext.create()
    return pc, pc.read.delta(data_path)


def delta_identity(spark, data_path, resource_type):
    """(version, commit timestamp, rows) for one resource's Delta table.

    A real fingerprint of what was counted, rather than a path someone typed.
    Best-effort: a warehouse laid out differently still produces correct counts,
    so a failure here records nulls instead of losing the run.
    """
    table = f"{data_path.rstrip('/')}/{resource_type}.parquet"
    try:
        history = spark.sql(f"DESCRIBE HISTORY delta.`{table}`") \
            .select("version", "timestamp") \
            .orderBy("version", ascending=False) \
            .first()
        rows = spark.sql(f"SELECT count(*) AS n FROM delta.`{table}`").first()["n"]
        return {"delta_version": history["version"],
                "committed": str(history["timestamp"]),
                "rows": rows}
    except Exception as exc:  # noqa: BLE001 — provenance is not worth a crash
        return {"error": "".join(
            traceback.format_exception_only(type(exc), exc)).strip()}


def count_element(data, element):
    """[(system, code, display, occurrences)] for one element, plus its totals.

    Grouped on (system, code) alone, with `display` taken as max() rather than
    first(): a code whose display drifted across the ETL would otherwise split
    into two rows, inflating the distinct-code count, and first() without an
    ORDER BY would make the committed CSV non-deterministic.
    """
    from pyspark.sql import functions as F

    plan = plan_view(element)
    df = data.view(plan["resource_type"], select=plan["select"])
    agg = (df.groupBy("system", "code")
             .agg(F.count(F.lit(1)).alias("occurrences"),
                  F.max("display").alias("display"))
             .orderBy(F.desc("occurrences"), "system", "code"))
    rows = [{"element": element["element"],
             "system": r["system"] or "",
             "code": r["code"] or "",
             "display": r["display"] or "",
             "occurrences": r["occurrences"]}
            for r in agg.collect()]
    return rows, {
        # Codings, not resources: this is the denominator every occurrence-
        # weighted percentage downstream divides by, so it is what gets stated.
        "codings": sum(r["occurrences"] for r in rows),
        "distinct_codes": len(rows),
        # A Coding present but carrying no code — a data defect, and one that
        # would otherwise hide inside an empty-string group.
        "codings_without_code": sum(r["occurrences"] for r in rows
                                    if not r["code"]),
    }


def write_csv(rows, out_dir):
    """One CSV for every element, ordered by element then descending count.

    Descending count is the order a reader wants (the heaviest codes first) and
    is fully determined by the data, so the committed file is stable.
    """
    path = os.path.join(out_dir, CSV_NAME)
    rows = sorted(rows, key=lambda r: (r["element"], -r["occurrences"],
                                       r["system"], r["code"]))
    with open(path, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    return path


def sha256(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def do_run(elements, data_path, out_dir):
    if not data_path:
        log("ERROR: --data is required for a real run (or use --dry-run).")
        return 2

    log(f"Opening Delta warehouse: {data_path}")
    pc, data = open_warehouse(data_path)

    all_rows = []
    per_element = {}
    tables = {}
    failures = 0

    for i, element in enumerate(elements, 1):
        name = element["element"]
        resource_type = element["resource_type"]
        if resource_type not in tables:
            tables[resource_type] = delta_identity(pc.spark, data_path,
                                                   resource_type)
        try:
            rows, totals = count_element(data, element)
            all_rows.extend(rows)
            per_element[name] = totals
            log(f"[{i}/{len(elements)}] {name} -> "
                f"{totals['distinct_codes']:,} codes, "
                f"{totals['codings']:,} codings")
        except Exception as exc:  # noqa: BLE001 — one bad element must not
            # cost the whole job: this runs on a queue slot, and six good
            # elements are worth keeping when the seventh has a bad path.
            err = "".join(traceback.format_exception_only(type(exc), exc)).strip()
            per_element[name] = {"error": err}
            failures += 1
            log(f"[{i}/{len(elements)}] {name} -> ERROR: {err}")

    csv_path = write_csv(all_rows, out_dir)
    summary = {
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "host": socket.gethostname(),
        "warehouse": data_path,
        "csv": CSV_NAME,
        "csv_sha256": sha256(csv_path),
        "versions": {
            "python": platform.python_version(),
            "spark": pc.spark.version,
            "pathling": _pathling_version(),
        },
        "tables": tables,
        "elements": per_element,
    }
    summary_path = os.path.join(out_dir, SUMMARY_NAME)
    with open(summary_path, "w") as fh:
        json.dump(summary, fh, indent=1)
        fh.write("\n")

    log(f"\nWrote {csv_path} ({len(all_rows):,} rows) and {summary_path}")
    if failures:
        log(f"{failures} element(s) failed — see 'elements' in the summary.")
    return 1 if failures else 0


def _pathling_version():
    try:
        from importlib.metadata import version
        return version("pathling")
    except Exception:  # noqa: BLE001
        return "unknown"


# --------------------------------------------------------------------------- #

def main(argv=None):
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", help="Pathling Delta warehouse root (one "
                                   "<ResourceType>.parquet table per resource)")
    ap.add_argument("--registry", default=DEFAULT_REGISTRY,
                    help="elements.json (default: next to this script)")
    ap.add_argument("--out-dir", default=SCRIPT_DIR,
                    help="where to write the CSV + summary (default: next to "
                         "this script)")
    ap.add_argument("--elements", nargs="+", metavar="ELEMENT",
                    help="only count these elements (partial run)")
    ap.add_argument("--dry-run", action="store_true",
                    help="print the planned views without importing Spark")
    args = ap.parse_args(argv if argv is not None else sys.argv[1:])

    elements = load_registry(args.registry, args.elements)
    log(f"Loaded {len(elements)} element(s) from {args.registry}")
    if args.dry_run:
        return do_dry_run(elements)
    return do_run(elements, args.data, args.out_dir)


if __name__ == "__main__":
    sys.exit(main())
