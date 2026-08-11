#!/usr/bin/env python3
"""Count how often every coded value actually occurs in MIMIC-on-FHIR.

Runs ONCE on a CSIRO HPC node against the full Delta warehouse, and its output
files are then committed to this repo. Everything downstream is offline:
build_statistics.py reads code-occurrences.csv to weight the mapping coverage
tables by how much data each code carries, because missing a code used on every
admission is not the same failure as missing one used twice in 2012.

Why this and not the existing artefacts:

  scripts/binding-analysis/distinct-codes.ndjson already carries counts, but
  phase 0 filtered out every element that was ALREADY BOUND — so the three
  elements this repo maps most (Observation.code, Procedure.code, Specimen.type)
  are exactly the ones missing from it. Rather than merge two extraction runs
  against warehouse states that differ by a provisioning step, this recounts
  all ten elements in one job, with one provenance record.

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

A CODING COUNT IS NOT A RESOURCE COUNT, and on a choice element the difference
is the whole story. `MedicationRequest.medication[x]` is `CodeableConcept |
Reference(Medication)`; only the CodeableConcept branch carries a Coding, so
extract_path can only ever see that branch. The 2026-08-06 run counted 1,883,681
codings against 15,416,901 MedicationRequest rows — so at least 87.8% of
requests carry their drug identity somewhere this file cannot reach, and a
coverage percentage over the codings alone reads as a statement about
prescriptions when it is a statement about one branch of one element.

Two extra views fix that, both declared per element in elements.json:

  count_shapes      per RESOURCE, which branch of the choice was taken. Turns
                    "silently absent" into a counted fact, and catches a
                    CodeableConcept carrying text but no coding — which under a
                    required binding is a conformance violation, not a shape.
  reference_join    follows the Reference to the element that DOES carry the
                    codes (Medication.code) and counts its codings weighted by
                    referring resources. That is the numerator for resource-level
                    reachability, and neither element can produce it alone.

Outputs, all written to --out-dir:
  code-occurrences.csv     element,system,code,display,occurrences
  element-shapes.csv       element,shape,resources — one row per observed
                           combination of the declared booleans. Only for
                           elements declaring count_shapes.
  reference-occurrences.csv  element,via,system,code,display,resources — the
                           target element's codings, counted once per REFERRING
                           resource. Only for elements declaring reference_join.
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
SHAPES_NAME = "element-shapes.csv"
REFERENCES_NAME = "reference-occurrences.csv"
SUMMARY_NAME = "occurrence-summary.json"
CSV_COLUMNS = ["element", "system", "code", "display", "occurrences"]
SHAPES_COLUMNS = ["element", "shape", "resources"]
REFERENCES_COLUMNS = ["element", "via", "system", "code", "display",
                      "resources"]

# The label a shape row gets when every declared boolean came back false: the
# element is present (the resource is in the table) but took none of the branches
# that could carry a code. Spelled out rather than left as an empty string, which
# in a CSV is indistinguishable from a column nobody filled in.
NO_BRANCH = "(none)"


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


def plan_shape_view(element):
    """The view for one element's choice-branch counts: one row per RESOURCE.

    No `forEach`, which is the entire point. A coding-level view cannot answer
    "how many resources took the Reference branch" because a resource that took
    it contributes no coding rows at all — it is absent from that view, and
    absence there is indistinguishable from a resource that has no such element.

    The booleans are declared in elements.json rather than derived from
    extract_path. Deriving them means string surgery on a FHIRPath to find the
    choice base, and a wrong guess yields plausible counts with nothing to catch
    them — the same failure mode the forEach comment above describes.
    """
    return {
        "resource_type": element["resource_type"],
        "select": [{
            "column": [{"path": path, "name": name}
                       for name, path in element["count_shapes"].items()],
        }],
    }


# How the reference join finds its partner rows. Two strategies, tried in order,
# because this job gets one queue slot and a wrong guess about FHIRPath support
# would cost a whole second run to learn.
#
#   reference-key  getReferenceKey() / getResourceKey(), the SQL-on-FHIR
#                  functions that exist for exactly this join. Correct by
#                  construction for every reference spelling.
#   string-id      the raw `reference` string against the target's `id`, with the
#                  trailing identifier extracted in Spark. Used only if the
#                  engine does not implement the functions above.
KEY_FUNCTIONS = "reference-key"
STRING_ID = "string-id"
JOIN_STRATEGIES = (KEY_FUNCTIONS, STRING_ID)


def plan_reference_views(element, target, strategy=KEY_FUNCTIONS):
    """(source view, target view) for a reference_join, joined on a resource key.

    The source view is one row per REFERRING resource, so the counts this
    produces are resource-weighted: a Medication referenced by 40,000 requests
    contributes 40,000, which is what makes the result comparable with the
    element's own resource total. The target view is one row per Coding, keyed so
    the join can fan out over a multi-coding Medication.code.

    `getReferenceKey()` is preferred over string-matching `Medication/xyz`
    against an id because a reference may legitimately be relative, absolute,
    versioned or a `urn:uuid:` — spellings a naive `split('/')` gets wrong in
    four different ways. The STRING_ID fallback handles all four too, but in
    Spark rather than in FHIRPath, and only because it must: see JOIN_STRATEGIES.
    """
    path = element["reference_join"]["reference_path"]
    if strategy == KEY_FUNCTIONS:
        source_column = {"path": f"{path}.getReferenceKey()",
                         "name": "target_key"}
        target_key = {"path": "getResourceKey()", "name": "target_key"}
    else:
        # Raw, unprocessed. The normalisation happens in count_references, where
        # Spark can do it — a FHIRPath expression complex enough to strip a
        # version suffix is exactly what this fallback exists to avoid needing.
        source_column = {"path": f"{path}.reference", "name": "target_ref"}
        target_key = {"path": "id", "name": "target_id"}
    return (
        {"resource_type": element["resource_type"],
         "select": [{"column": [source_column]}]},
        {"resource_type": target["resource_type"],
         "select": [
             {"column": [target_key]},
             {"forEach": target["extract_path"], "column": [
                 {"path": "system", "name": "system"},
                 {"path": "code", "name": "code"},
                 {"path": "display", "name": "display"},
             ]},
         ]},
    )


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

def do_dry_run(elements, registry=None):
    registry = {e["element"]: e for e in (registry or elements)}
    log(f"DRY RUN: {len(elements)} element(s) planned\n")
    for i, element in enumerate(elements, 1):
        plan = plan_view(element)
        print("=" * 70)
        print(f"[{i}] {element['element']}")
        print(f"    resource : {plan['resource_type']}")
        print(f"    forEach  : {element['extract_path']}")
        print(f"    select   : {json.dumps(plan['select'])}")
        print("    groupBy  : system, code   (display via max, for determinism)")
        if element.get("count_shapes"):
            shape = plan_shape_view(element)
            print(f"    + shapes : {json.dumps(shape['select'])}")
            print("      groupBy: every declared boolean   -> "
                  f"{SHAPES_NAME}")
        if element.get("reference_join"):
            name = element["reference_join"]["target"]
            target = registry.get(name)
            if target is None:
                print(f"    + refjoin: ERROR unknown target element {name!r}")
            else:
                for strategy in JOIN_STRATEGIES:
                    src, tgt = plan_reference_views(element, target, strategy)
                    print(f"    + refjoin: {src['resource_type']} -> "
                          f"{tgt['resource_type']} ({name})  [{strategy}]")
                    print(f"      source : {json.dumps(src['select'])}")
                    print(f"      target : {json.dumps(tgt['select'])}")
                print("      join   : LEFT on target_key, so an unresolvable "
                      f"reference is counted rather than dropped. Strategies "
                      f"tried in the order shown   -> {REFERENCES_NAME}")
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


def count_shapes(data, element):
    """[(shape, resources)] for one element's choice branches, plus its totals.

    `shape` names the branches that were TRUE, joined with `+`, so one row is
    readable on its own: `with_codeable_concept+with_coding` is an inline coded
    concept and `with_reference` is a pointer. Reporting a column per boolean
    instead would give every element a different CSV header.

    The combination that matters most is the one nobody plans for:
    with_codeable_concept true and with_coding false is a CodeableConcept
    carrying text alone, which under a REQUIRED binding is non-conformant — R4
    asks for at least one Coding from the value set, and text is not one. It is
    surfaced as `codeable_concept_without_coding` rather than left for a reader
    to reconstruct from the shape labels.
    """
    from pyspark.sql import functions as F

    names = list(element["count_shapes"])
    plan = plan_shape_view(element)
    df = data.view(plan["resource_type"], select=plan["select"])
    agg = (df.groupBy(*names)
             .agg(F.count(F.lit(1)).alias("resources"))
             .orderBy(F.desc("resources"), *names))

    rows, totals = [], {name: 0 for name in names}
    resources = no_branch = text_only = 0
    for record in agg.collect():
        n = record["resources"]
        true_names = [name for name in names if record[name]]
        rows.append({"element": element["element"],
                     "shape": "+".join(true_names) or NO_BRANCH,
                     "resources": n})
        resources += n
        for name in true_names:
            totals[name] += n
        if not true_names:
            no_branch += n
        if ("with_codeable_concept" in names and "with_coding" in names
                and record["with_codeable_concept"]
                and not record["with_coding"]):
            text_only += n

    summary = {"resources": resources, **totals, "no_branch": no_branch}
    if "with_codeable_concept" in names and "with_coding" in names:
        summary["codeable_concept_without_coding"] = text_only
    return rows, summary


def count_references(data, element, target):
    """[(system, code, display, resources)] reached THROUGH the reference, + totals.

    Counted once per REFERRING resource, not once per target resource: the
    question is "how many MedicationRequests point at a drug code $translate can
    resolve", and a Medication referenced by 40,000 prescriptions answers it
    40,000 times. Aggregating the target alone would answer a question about the
    drug dictionary instead, which the target element's own count already covers.

    A LEFT join, deliberately. An inner join would silently drop a reference
    that resolves to nothing, and a dangling reference in a warehouse whose
    required binding is only enforceable on the target is precisely the defect
    worth counting rather than hiding — it is reported as `dangling`.
    """
    last_error = None
    for strategy in JOIN_STRATEGIES:
        try:
            return _count_references(data, element, target, strategy)
        except Exception as exc:  # noqa: BLE001 — see JOIN_STRATEGIES
            last_error = exc
            err = "".join(
                traceback.format_exception_only(type(exc), exc)).strip()
            log(f"      refjoin: {strategy} strategy failed ({err})")
    raise last_error


def _count_references(data, element, target, strategy):
    """One attempt at the reference join, with one key strategy.

    Split out so a strategy that the engine does not support costs a retry rather
    than the whole output. The chosen strategy is recorded in the summary, because
    "which join produced this" is provenance a reader of the numbers needs and
    cannot recover afterwards.
    """
    from pyspark.sql import functions as F

    src_plan, tgt_plan = plan_reference_views(element, target, strategy)
    src = data.view(src_plan["resource_type"], select=src_plan["select"])
    tgt = data.view(tgt_plan["resource_type"], select=tgt_plan["select"])

    if strategy == STRING_ID:
        # Normalise here rather than in FHIRPath. Strip any `/_history/N` first —
        # otherwise the version number becomes the id — then take the trailing
        # run of characters that is neither `/` nor `:`, which yields the logical
        # id for all four spellings: `Medication/abc`, `http://h/fhir/
        # Medication/abc`, `urn:uuid:abc`, and `Medication/abc/_history/2`.
        src = src.withColumn(
            "target_key",
            F.regexp_extract(
                F.regexp_replace(F.col("target_ref"), r"/_history/.*$", ""),
                r"([^/:]+)$", 1)).drop("target_ref")
        # An empty extraction is not a key; treat it as absent so it lands in
        # `dangling` rather than joining every unmatched row to every other.
        src = src.withColumn("target_key",
                             F.when(F.col("target_key") == "", None)
                              .otherwise(F.col("target_key")))
        tgt = tgt.withColumnRenamed("target_id", "target_key")

    src = src.where(F.col("target_key").isNotNull())
    referring = src.count()
    joined = src.join(tgt, on="target_key", how="left")
    agg = (joined.groupBy("system", "code")
                 .agg(F.count(F.lit(1)).alias("resources"),
                      F.max("display").alias("display"))
                 .orderBy(F.desc("resources"), "system", "code"))

    rows, dangling = [], 0
    for record in agg.collect():
        if record["code"] is None and record["system"] is None:
            # Either the reference resolved to no Medication at all or it
            # resolved to one carrying no code. Both leave the referring
            # resource with no translatable code, which is the fact being
            # counted; telling them apart needs the target's own row count and
            # is left to the reader of occurrence-summary.json.
            dangling += record["resources"]
            continue
        rows.append({"element": element["element"],
                     "via": target["element"],
                     "system": record["system"] or "",
                     "code": record["code"] or "",
                     "display": record["display"] or "",
                     "resources": record["resources"]})
    return rows, {
        "via": target["element"],
        "join_strategy": strategy,
        "referring_resources": referring,
        "codings_reached": sum(r["resources"] for r in rows),
        "distinct_codes_reached": len(rows),
        "dangling": dangling,
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


def write_side_csv(rows, out_dir, name, columns, sort_key):
    """One of the two per-element side files, or nothing if no element wants it.

    Not written at all when empty, rather than written as a header-only file: a
    header with no rows says "measured, found nothing", and for these two files
    the truthful statement is "no element declared this", which is a different
    thing. common/occurrences.py treats a missing file as the latter.
    """
    if not rows:
        return None
    path = os.path.join(out_dir, name)
    with open(path, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns)
        writer.writeheader()
        writer.writerows(sorted(rows, key=sort_key))
    return path


def sha256(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def do_run(elements, data_path, out_dir, registry=None):
    if not data_path:
        log("ERROR: --data is required for a real run (or use --dry-run).")
        return 2

    log(f"Opening Delta warehouse: {data_path}")
    pc, data = open_warehouse(data_path)

    # The FULL registry, not the (possibly --elements filtered) run list: a
    # reference_join names its target by element, and that target has to be
    # resolvable even when the target itself is not being recounted this run.
    by_name = {e["element"]: e for e in (registry or elements)}

    all_rows = []
    shape_rows = []
    reference_rows = []
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

        # Both side views are OPTIONAL and each fails independently of the code
        # count above. They are the newest queries here and the ones most likely
        # to meet a FHIRPath a given Pathling build does not implement
        # (getReferenceKey in particular); losing the per-code counts — the
        # artifact everything downstream needs — to a failure in a supplementary
        # view would be a bad trade on a queue slot.
        if element.get("count_shapes"):
            try:
                rows, totals = count_shapes(data, element)
                shape_rows.extend(rows)
                per_element.setdefault(name, {})["shapes"] = totals
                log(f"      shapes -> {totals['resources']:,} resources in "
                    f"{len(rows)} shape(s)")
            except Exception as exc:  # noqa: BLE001
                err = "".join(
                    traceback.format_exception_only(type(exc), exc)).strip()
                per_element.setdefault(name, {})["shapes"] = {"error": err}
                failures += 1
                log(f"      shapes -> ERROR: {err}")

        if element.get("reference_join"):
            target_name = element["reference_join"]["target"]
            target = by_name.get(target_name)
            if target is None:
                err = f"reference_join target {target_name!r} is not in the registry"
                per_element.setdefault(name, {})["reference_join"] = {"error": err}
                failures += 1
                log(f"      refjoin -> ERROR: {err}")
            else:
                try:
                    rows, totals = count_references(data, element, target)
                    reference_rows.extend(rows)
                    per_element.setdefault(name, {})["reference_join"] = totals
                    log(f"      refjoin -> {totals['referring_resources']:,} "
                        f"referring, {totals['codings_reached']:,} codings "
                        f"reached via {target_name}, "
                        f"{totals['dangling']:,} dangling")
                except Exception as exc:  # noqa: BLE001
                    err = "".join(
                        traceback.format_exception_only(type(exc), exc)).strip()
                    per_element.setdefault(name, {})["reference_join"] = {
                        "error": err}
                    failures += 1
                    log(f"      refjoin -> ERROR: {err}")

    csv_path = write_csv(all_rows, out_dir)
    shapes_path = write_side_csv(
        shape_rows, out_dir, SHAPES_NAME, SHAPES_COLUMNS,
        lambda r: (r["element"], -r["resources"], r["shape"]))
    references_path = write_side_csv(
        reference_rows, out_dir, REFERENCES_NAME, REFERENCES_COLUMNS,
        lambda r: (r["element"], r["via"], -r["resources"], r["system"],
                   r["code"]))
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
    # Hashed like the main CSV and for the same reason: build_statistics.py
    # refuses counts whose bytes it cannot vouch for, and a side file that
    # bypassed that check would be the one number in the thesis nothing verified.
    for key, path in (("shapes_csv", shapes_path),
                      ("references_csv", references_path)):
        if path:
            summary[key] = os.path.basename(path)
            summary[f"{key}_sha256"] = sha256(path)
    summary_path = os.path.join(out_dir, SUMMARY_NAME)
    with open(summary_path, "w") as fh:
        json.dump(summary, fh, indent=1)
        fh.write("\n")

    log(f"\nWrote {csv_path} ({len(all_rows):,} rows) and {summary_path}")
    for path, rows in ((shapes_path, shape_rows),
                       (references_path, reference_rows)):
        if path:
            log(f"Wrote {path} ({len(rows):,} rows)")
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

    registry = load_registry(args.registry)
    elements = load_registry(args.registry, args.elements)
    log(f"Loaded {len(elements)} element(s) from {args.registry}")
    if args.dry_run:
        return do_dry_run(elements, registry)
    return do_run(elements, args.data, args.out_dir, registry)


if __name__ == "__main__":
    sys.exit(main())
