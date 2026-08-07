#!/usr/bin/env python3
"""Observe what SHAPE of value each Observation.code actually carries.

Runs ONCE on a CSIRO HPC node against the full Delta warehouse; its three output
files are then committed to this repo and everything downstream is offline. The
sibling of occurrences/count_occurrences.py, and staged the same way — see
README.md.

WHY THIS EXISTS. The chartevents table's validation gate asserts three things
about a proposed target: that it is a member of the constraint, that it exists
and is active, and that the server confirms its display. None of those can see
the defect that actually dominates the stream — a target whose SCALE is
incompatible with the data. Measured against the demo warehouse over the 160
highest-occurrence committed LOINC mappings, 19 of them (12%, 12.8M
occurrences) name a LOINC code whose SCALE_TYP contradicts the value MIMIC
records:

    223907 Pupil Size Right  -> 8642-1  |Right pupil Diameter Auto|   Qn
                                but MIMIC charts 7 enumerated penlight sizes
    224017 GU Catheter Size  -> 78945-3 |Guiding catheter size|       Qn
                                but MIMIC charts `14 French` .. `Coude Catheter`
    223792 Pain Management   -> 34858-1 |Pain medicine Note|          Doc
                                a DOCUMENT code bound to a flowsheet value

The first is the one case build_chartevents_table.py's COMMENT_OVERRIDES
docstring had already found by hand; this check finds it without being told, and
finds the `GU = Guiding` abbreviation defect that the same docstring argues no
template setting can fix. A SCALE_TYP of `Doc` or `-` is never a legal
Observation.code target for a flowsheet value, and that is decidable from data
plus a $lookup — no LLM, no threshold, no per-item judgement.

So this job's output is a GATE INPUT, not a search input. Feeding the value
domain into the code-search query text was tried and rejected: it fixes real
defects (`224650 Ectopy Type 1` -> `76281-5 |Type of arrhythmia on EKG|` at
0.85, from no-match in both systems) but disturbs two correct controls and
compresses confidences toward 0.85 — the same failure the category-injected
templates T1 and T2 were rejected for. The value domain is recorded here so a
deterministic check can use it; whether any query ever sends it is a separate
decision with its own evidence.

WHAT IS RECORDED, per (element, system, code):

  the SHAPE       how many occurrences carry a Quantity, a string, a
                  CodeableConcept, a boolean, an integer, a dateTime, some
                  other value[x], no value at all, or a dataAbsentReason
  a SCALE HINT    Qn / NomOrd / Nar / (blank), derived by the stated rule below
                  so the consumer compares LOINC's SCALE_TYP against one field
                  rather than re-deriving it from nine counts
  the UNITS       every distinct valueQuantity unit with its UCUM code and count
  the VALUE DOMAIN  every distinct string-ish value with its count, FREQUENCY
                  ranked and capped at --top-values

THE SCALE HINT IS A STATED RULE, applied identically to every code:

    no value on any occurrence                          -> (blank)
    >= 95% of VALUED occurrences are Quantity/integer    -> Qn
    >= 95% are string-ish and distinct <= --enum-max      -> NomOrd
    >= 95% are string-ish and distinct >  --enum-max      -> Nar
    anything else                                        -> (blank), shape=mixed

95% rather than 100% because a handful of `___` or `Not applicable` strings on
an otherwise numeric item is an ETL artefact, not evidence that the item is
nominal — and a rule that demanded purity would classify almost nothing. The
blank cases are deliberately unusable: a mixed-shape item is one a human should
read, not one a gate should decide from.

FREQUENCY RANKED, not alphabetical. A first pass over the demo collected value
sets with collect_set() and sorted them, which put `Adequate lighting` at the
head of `227969 Safety Measures` and buried whatever nurses actually chart. The
head of the distribution is the whole signal, so the rank is by count, with the
value string as a tiebreak so the committed file is stable across runs.

CAPS ARE RECORDED, NEVER SILENT. --top-values bounds the rows collected per
code and --max-value-chars bounds the grouping key; both land in the summary,
and a code whose domain was truncated carries `domain_truncated` so a reader
cannot mistake 40 values for all of them.

NOT Observation.component.code. Component values live at component.value[x],
paired with component.code inside the same array element, so observing them
needs a forEach over `component` rather than the flat view here. That element is
2 codes at 100% coverage, so it would be machinery for nothing; when it stops
being 2 codes this is the reason it was left out.

Deliberately self-contained: stdlib + pathling/pyspark only, no imports from
this repo. The node runs Python 3.12 under the REMOTE project's uv environment
(`/scratch3/nau025/mimic-on-fhir-delta`), not this repo's 3.14 one, and compute
nodes have no internet, so nothing here may resolve a dependency at run time.

Outputs, all written to --out-dir:
  observation-value-shapes.csv    one row per code: the counts, the shape, the
                                  scale hint, the units
  observation-value-domains.csv   one row per (code, value): long format, so a
                                  value containing a comma or a semicolon needs
                                  no escaping scheme of its own
  value-shape-summary.json        per-element totals + the run's identity: Delta
                                  version and commit timestamp, host, versions,
                                  the caps in force, and the sha256 of both CSVs

Usage (on the node, via extract_value_shapes.slurm):
  uv run python3 valueshapes/extract_value_shapes.py --data "$DATA" \
      --out-dir valueshapes
Dry run (laptop, no Spark, no warehouse):
  uv run python3 scripts/terminology-mapping/valueshapes/extract_value_shapes.py --dry-run
Smoke test against the demo warehouse (laptop, needs pathling + Java):
  uv run --with pathling python3 .../extract_value_shapes.py \
      --data /Users/nau025/warehouses/mimic-iv-demo/delta --out-dir /tmp/vs
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

SHAPES_NAME = "observation-value-shapes.csv"
DOMAINS_NAME = "observation-value-domains.csv"
SUMMARY_NAME = "value-shape-summary.json"

# Only the elements that HAVE a value[x]. Keyed by the element name in
# elements.json so the coding path stays in step with count_occurrences.py
# rather than being re-typed here.
VALUED_ELEMENTS = ["Observation.code"]

SHAPE_COLUMNS = [
    "element", "system", "code", "display", "occurrences",
    "n_quantity", "n_string", "n_codeable", "n_boolean", "n_integer",
    "n_datetime", "n_other", "n_no_value", "n_data_absent",
    "shape", "scale_hint", "distinct_values", "domain_truncated", "units",
]
DOMAIN_COLUMNS = ["element", "system", "code", "rank", "value", "occurrences"]

# The value[x] choices read as their own columns. Every path is single-valued by
# construction — a collection-valued column is an error in a SQL-on-FHIR view,
# and `exists()` is what keeps the CodeableConcept and the structured choices
# countable without one.
VALUE_COLUMNS = [
    ("qty_value", "value.ofType(Quantity).value"),
    ("qty_unit", "value.ofType(Quantity).unit"),
    ("qty_ucum", "value.ofType(Quantity).code"),
    ("qty_system", "value.ofType(Quantity).system"),
    ("val_string", "value.ofType(string)"),
    ("cc_text", "value.ofType(CodeableConcept).text"),
    ("cc_present", "value.ofType(CodeableConcept).exists()"),
    ("val_boolean", "value.ofType(boolean)"),
    ("val_integer", "value.ofType(integer)"),
    ("val_datetime", "value.ofType(dateTime)"),
    ("val_time", "value.ofType(time)"),
    # One column per structured choice rather than a union: Pathling rejects
    # `value.ofType(Period) | value.ofType(Range)` with "Operator `|` is not
    # supported for: unknown(Period), unknown(Range)", so the union has to
    # happen in Spark after the view rather than inside the FHIRPath.
    ("period_present", "value.ofType(Period).exists()"),
    ("range_present", "value.ofType(Range).exists()"),
    ("ratio_present", "value.ofType(Ratio).exists()"),
    ("sampled_present", "value.ofType(SampledData).exists()"),
    ("absent_present", "dataAbsentReason.exists()"),
]


def log(msg):
    """Progress to stderr, so it interleaves with Spark's own stdout noise."""
    print(msg, file=sys.stderr, flush=True)


# --------------------------------------------------------------------------- #
# Query planning — pure, shared by the dry run and the real run.
# --------------------------------------------------------------------------- #

def plan_view(element):
    """The SQL-on-FHIR view for one element: one row per Coding, value attached.

    Two select entries at the same level. The first reads the value[x] choices
    as scalar columns of the resource; the second is the `forEach` over
    `code.coding` that count_occurrences.py established, which is what keeps
    system/code/display aligned per Coding instead of cross-joining them.
    Together they yield one row per Coding carrying that resource's value — so a
    CodeableConcept with two Codings counts its value under both, which is
    correct: both codes were used to say it.

    `forEach`, not `forEachOrNull`: a resource with no code contributes no rows,
    because "absent" is not a coded value and must not become one.
    """
    return {
        "resource_type": element["resource_type"],
        "select": [
            {"column": [{"path": path, "name": name}
                        for name, path in VALUE_COLUMNS]},
            {"forEach": element["extract_path"],
             "column": [{"path": "system", "name": "system"},
                        {"path": "code", "name": "code"},
                        {"path": "display", "name": "display"}]},
        ],
    }


def load_registry(path, wanted):
    with open(path) as fh:
        elements = json.load(fh)["elements"]
    keep = set(wanted)
    unknown = keep - {e["element"] for e in elements}
    if unknown:
        log(f"ERROR: unknown element(s): {', '.join(sorted(unknown))}")
        sys.exit(2)
    return [e for e in elements if e["element"] in keep]


def default_registry():
    """elements.json, preferring a copy staged next to this script.

    The remote layout puts valueshapes/ beside occurrences/, so the sibling path
    resolves on the node without staging a second copy of the registry; the
    local path exists so a run from a directory that carries its own copy does
    not silently read a different one.
    """
    local = os.path.join(SCRIPT_DIR, "elements.json")
    if os.path.isfile(local):
        return local
    return os.path.join(os.path.dirname(SCRIPT_DIR), "occurrences",
                        "elements.json")


def classify(counts, distinct, enum_max):
    """(shape, scale_hint) by the stated rule. See THE SCALE HINT in the module
    docstring — the thresholds are arguments so the rule can be moved with
    evidence, and both land in the summary."""
    valued = (counts["n_quantity"] + counts["n_string"] + counts["n_codeable"]
              + counts["n_boolean"] + counts["n_integer"]
              + counts["n_datetime"] + counts["n_other"])
    if not valued:
        return "no-value", ""
    quant = counts["n_quantity"] + counts["n_integer"]
    stringish = counts["n_string"] + counts["n_codeable"]
    if quant / valued >= 0.95:
        return "quantitative", "Qn"
    if stringish / valued >= 0.95:
        if distinct and distinct > enum_max:
            return "free-text", "Nar"
        return "enumerated", "NomOrd"
    return "mixed", ""


# --------------------------------------------------------------------------- #
# Dry run — must not import pyspark or pathling.
# --------------------------------------------------------------------------- #

def do_dry_run(elements, args):
    log(f"DRY RUN: {len(elements)} element(s) planned\n")
    for i, element in enumerate(elements, 1):
        plan = plan_view(element)
        print("=" * 74)
        print(f"[{i}] {element['element']}")
        print(f"    resource : {plan['resource_type']}")
        print(f"    forEach  : {element['extract_path']}")
        print(f"    value[x] : {len(VALUE_COLUMNS)} scalar column(s)")
        for name, path in VALUE_COLUMNS:
            print(f"        {name:<15} {path}")
        print("    pass 1   : groupBy(system, code) -> shape counts")
        print("    pass 2   : groupBy(system, code, unit) -> units")
        print("    pass 3   : groupBy(system, code, value) -> domain, "
              f"ranked by count, top {args.top_values}")
    print("=" * 74)
    print(f"    caps     : top_values={args.top_values} "
          f"max_value_chars={args.max_value_chars} enum_max={args.enum_max}")
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

    A real fingerprint of what was read, rather than a path someone typed.
    Best-effort: a warehouse laid out differently still produces correct
    counts, so a failure here records nulls instead of losing the run.
    """
    table = f"{data_path.rstrip('/')}/{resource_type}.parquet"
    try:
        history = (spark.sql(f"DESCRIBE HISTORY delta.`{table}`")
                   .select("version", "timestamp")
                   .orderBy("version", ascending=False).first())
        rows = spark.sql(
            f"SELECT count(*) AS n FROM delta.`{table}`").first()["n"]
        return {"delta_version": history["version"],
                "committed": str(history["timestamp"]), "rows": rows}
    except Exception as exc:  # noqa: BLE001 — provenance is not worth a crash
        return {"error": "".join(
            traceback.format_exception_only(type(exc), exc)).strip()}


def extract_element(data, element, args):
    """(shape rows, domain rows, totals) for one element.

    Three aggregations over one cached view. Each collect() is bounded by the
    number of distinct codes (a few thousand) times a cap, never by the number
    of occurrences — which is the difference between this returning and this
    filling the driver heap on a 461M-row table.
    """
    from pyspark.sql import functions as F, Window

    plan = plan_view(element)
    view = data.view(plan["resource_type"], select=plan["select"])

    name = element["element"]
    stringish = F.coalesce(F.col("val_string"), F.col("cc_text"))
    # Truncated and trimmed BEFORE grouping, so the cap bounds the shuffle key
    # rather than being applied to whatever the shuffle already built.
    value_key = F.substring(F.trim(stringish), 1, args.max_value_chars)

    view = view.select(
        F.coalesce(F.col("system"), F.lit("")).alias("system"),
        F.coalesce(F.col("code"), F.lit("")).alias("code"),
        F.col("display"),
        F.col("qty_value"), F.col("qty_unit"), F.col("qty_ucum"),
        F.col("val_string"), F.col("cc_text"), F.col("cc_present"),
        F.col("val_boolean"), F.col("val_integer"), F.col("val_datetime"),
        F.col("val_time"), F.col("period_present"), F.col("range_present"),
        F.col("ratio_present"), F.col("sampled_present"),
        F.col("absent_present"),
        value_key.alias("value_key"),
    )
    # NOT cached, deliberately. Three aggregations read this view, so caching
    # looks free — but on the full warehouse Observation is 461M rows and the
    # cached intermediate carries value_key, up to --max-value-chars per row.
    # MEMORY_AND_DISK means that spills rather than failing, which trades an
    # OOM for disk thrash on a queue slot. Three column-pruned Delta scans are
    # cheap by comparison: count_occurrences.py does seven over the same table
    # inside its two-hour budget.

    def n(condition):
        return F.sum(F.when(condition, 1).otherwise(0))

    has_string = F.col("val_string").isNotNull()
    has_cc = F.coalesce(F.col("cc_present"), F.lit(False))
    has_qty = F.col("qty_value").isNotNull()
    has_bool = F.col("val_boolean").isNotNull()
    has_int = F.col("val_integer").isNotNull()
    has_dt = (F.col("val_datetime").isNotNull()
              | F.col("val_time").isNotNull())
    has_other = (F.coalesce(F.col("period_present"), F.lit(False))
                 | F.coalesce(F.col("range_present"), F.lit(False))
                 | F.coalesce(F.col("ratio_present"), F.lit(False))
                 | F.coalesce(F.col("sampled_present"), F.lit(False)))
    has_any = (has_string | has_cc | has_qty | has_bool | has_int | has_dt
               | has_other)

    # ---- pass 1: the shape counts, one row per code ----
    shapes = (view.groupBy("system", "code").agg(
        F.count(F.lit(1)).alias("occurrences"),
        F.max("display").alias("display"),
        n(has_qty).alias("n_quantity"),
        n(has_string).alias("n_string"),
        n(has_cc).alias("n_codeable"),
        n(has_bool).alias("n_boolean"),
        n(has_int).alias("n_integer"),
        n(has_dt).alias("n_datetime"),
        n(has_other).alias("n_other"),
        n(~has_any).alias("n_no_value"),
        n(F.coalesce(F.col("absent_present"), F.lit(False)))
        .alias("n_data_absent"),
        F.countDistinct("value_key").alias("distinct_values"),
    ).collect())

    # ---- pass 2: units, with counts. A few per code at most. ----
    units = (view.filter(F.col("qty_unit").isNotNull()
                         | F.col("qty_ucum").isNotNull())
             .groupBy("system", "code", "qty_unit", "qty_ucum")
             .agg(F.count(F.lit(1)).alias("n"))
             .orderBy("system", "code", F.desc("n"))
             .collect())
    by_code_units = {}
    for row in units:
        unit = row["qty_unit"] or ""
        ucum = row["qty_ucum"] or ""
        label = f"{unit}|{ucum}" if ucum and ucum != unit else (unit or ucum)
        by_code_units.setdefault((row["system"], row["code"]), []).append(
            f"{label}={row['n']}")

    # ---- pass 3: the value domain, frequency ranked, capped ----
    counted = (view.filter(F.col("value_key").isNotNull()
                           & (F.length(F.col("value_key")) > 0))
               .groupBy("system", "code", "value_key")
               .agg(F.count(F.lit(1)).alias("n")))
    ranked = (counted.withColumn(
        "rank", F.row_number().over(
            Window.partitionBy("system", "code")
            .orderBy(F.desc("n"), F.col("value_key"))))
        .filter(F.col("rank") <= args.top_values)
        .orderBy("system", "code", "rank")
        .collect())

    domain_rows = [{"element": name, "system": r["system"], "code": r["code"],
                    "rank": r["rank"], "value": r["value_key"],
                    "occurrences": r["n"]}
                   for r in ranked]

    shape_rows = []
    for r in shapes:
        counts = {c: r[c] for c in (
            "n_quantity", "n_string", "n_codeable", "n_boolean", "n_integer",
            "n_datetime", "n_other")}
        distinct = r["distinct_values"]
        shape, hint = classify(counts, distinct, args.enum_max)
        shape_rows.append({
            "element": name, "system": r["system"], "code": r["code"],
            "display": r["display"] or "", "occurrences": r["occurrences"],
            **counts,
            "n_no_value": r["n_no_value"],
            "n_data_absent": r["n_data_absent"],
            "shape": shape, "scale_hint": hint,
            "distinct_values": distinct,
            "domain_truncated": ("yes" if distinct > args.top_values else ""),
            "units": ";".join(by_code_units.get((r["system"], r["code"]), [])),
        })

    truncated = sum(1 for r in shape_rows if r["domain_truncated"])
    totals = {
        "codings": sum(r["occurrences"] for r in shape_rows),
        "distinct_codes": len(shape_rows),
        "domains_truncated": truncated,
        "shapes": {s: sum(1 for r in shape_rows if r["shape"] == s)
                   for s in sorted({r["shape"] for r in shape_rows})},
    }
    return shape_rows, domain_rows, totals


def write_csv(rows, columns, out_dir, filename, sort_key):
    path = os.path.join(out_dir, filename)
    with open(path, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns)
        writer.writeheader()
        writer.writerows(sorted(rows, key=sort_key))
    return path


def sha256(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def do_run(elements, args):
    if not args.data:
        log("ERROR: --data is required for a real run (or use --dry-run).")
        return 2

    log(f"Opening Delta warehouse: {args.data}")
    pc, data = open_warehouse(args.data)

    all_shapes, all_domains, per_element, tables = [], [], {}, {}
    failures = 0

    for i, element in enumerate(elements, 1):
        name = element["element"]
        resource_type = element["resource_type"]
        if resource_type not in tables:
            tables[resource_type] = delta_identity(pc.spark, args.data,
                                                   resource_type)
        try:
            shapes, domains, totals = extract_element(data, element, args)
            all_shapes.extend(shapes)
            all_domains.extend(domains)
            per_element[name] = totals
            log(f"[{i}/{len(elements)}] {name} -> "
                f"{totals['distinct_codes']:,} codes, "
                f"{totals['codings']:,} codings, "
                f"{len(domains):,} domain row(s), "
                f"{totals['domains_truncated']:,} domain(s) truncated")
            for shape, count in sorted(totals["shapes"].items()):
                log(f"        {shape:<14} {count:>6}")
        except Exception as exc:  # noqa: BLE001 — one bad element must not cost
            # the whole job: this runs on a queue slot.
            err = "".join(
                traceback.format_exception_only(type(exc), exc)).strip()
            per_element[name] = {"error": err}
            failures += 1
            log(f"[{i}/{len(elements)}] {name} -> ERROR: {err}")

    shapes_path = write_csv(
        all_shapes, SHAPE_COLUMNS, args.out_dir, SHAPES_NAME,
        lambda r: (r["element"], -r["occurrences"], r["system"], r["code"]))
    domains_path = write_csv(
        all_domains, DOMAIN_COLUMNS, args.out_dir, DOMAINS_NAME,
        lambda r: (r["element"], r["system"], r["code"], r["rank"],
                   r["value"]))

    summary = {
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "host": socket.gethostname(),
        "warehouse": args.data,
        "shapes_csv": SHAPES_NAME,
        "shapes_csv_sha256": sha256(shapes_path),
        "domains_csv": DOMAINS_NAME,
        "domains_csv_sha256": sha256(domains_path),
        # The caps in force, because a reader of the domains file cannot
        # otherwise tell a short domain from a truncated one, and because a
        # future run that moves them should show up as a diff here.
        "caps": {"top_values": args.top_values,
                 "max_value_chars": args.max_value_chars,
                 "enum_max": args.enum_max,
                 "quantitative_or_stringish_fraction": 0.95},
        "versions": {"python": platform.python_version(),
                     "spark": pc.spark.version,
                     "pathling": _pathling_version()},
        "tables": tables,
        "elements": per_element,
    }
    summary_path = os.path.join(args.out_dir, SUMMARY_NAME)
    with open(summary_path, "w") as fh:
        json.dump(summary, fh, indent=1)
        fh.write("\n")

    log(f"\nWrote {shapes_path} ({len(all_shapes):,} rows)")
    log(f"Wrote {domains_path} ({len(all_domains):,} rows)")
    log(f"Wrote {summary_path}")
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
    ap.add_argument("--registry", default=None,
                    help="elements.json (default: a copy beside this script, "
                         "else ../occurrences/elements.json)")
    ap.add_argument("--out-dir", default=SCRIPT_DIR,
                    help="where to write the CSVs + summary (default: next to "
                         "this script)")
    ap.add_argument("--elements", nargs="+", metavar="ELEMENT",
                    default=VALUED_ELEMENTS,
                    help=f"elements to observe (default: "
                         f"{' '.join(VALUED_ELEMENTS)})")
    ap.add_argument("--top-values", type=int, default=40,
                    help="value-domain rows kept per code, by descending count "
                         "(default: %(default)s)")
    ap.add_argument("--max-value-chars", type=int, default=200,
                    help="value strings truncated to this before grouping, so "
                         "a free-text field cannot make the shuffle key "
                         "unbounded (default: %(default)s)")
    ap.add_argument("--enum-max", type=int, default=200,
                    help="above this many distinct values a string-ish code is "
                         "called free-text rather than enumerated "
                         "(default: %(default)s)")
    ap.add_argument("--dry-run", action="store_true",
                    help="print the planned view without importing Spark")
    args = ap.parse_args(argv if argv is not None else sys.argv[1:])

    registry = args.registry or default_registry()
    if not os.path.isfile(registry):
        log(f"ERROR: registry not found: {registry}")
        return 2
    elements = load_registry(registry, args.elements)
    log(f"Loaded {len(elements)} element(s) from {registry}")
    if args.dry_run:
        return do_dry_run(elements, args)
    return do_run(elements, args)


if __name__ == "__main__":
    sys.exit(main())
