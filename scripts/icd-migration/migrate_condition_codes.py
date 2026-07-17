#!/usr/bin/env python3
"""Migrate MIMIC ICD Condition.code codings to pinned ICD-9-CM / ICD-10-CM.

Rewrites every Condition.code.coding on the custom dot-less MIMIC systems
(http://mimic.mit.edu/fhir/mimic/CodeSystem/mimic-diagnosis-icd10 and
.../mimic-diagnosis-icd9) to the proper SID system: dotted code, official
display, and a pinned Coding.version (the earliest release the code is valid
in — for ICD-9-CM always 2012, the frozen final release). The old MIMIC coding
is REPLACED, not kept alongside. All other codings pass through untouched.

The rewrite is driven entirely by scripts/icd-migration/display-map.json
(built by check_icd_codes.py against a terminology server) — this script needs
NO network access and is meant to run on the CSIRO HPC node (Spark + pathling,
Delta-format MIMIC-on-FHIR, no internet). Cannot be tested against real data
here, so:
  * every environment assumption sits behind a CLI flag,
  * `--dry-run` exercises the transform on built-in samples WITHOUT importing
    pyspark/pathling,
  * the run ABORTS before writing anything if the data contains a MIMIC ICD
    code missing from the map (data/CodeSystem drift guard).

Outputs:
  * the migrated Condition table, written as a Delta table (default) or NDJSON
    under --output; the source warehouse is never modified unless you point
    --output back at it (requires --overwrite)
  * migration-report.json next to --output: before/after coding counts,
    per-version pin counts, and the residual old-system count (must be 0)

Usage (on the node):
  python3 migrate_condition_codes.py --data /path/to/delta/warehouse \\
      --output /path/to/migrated-warehouse
ICD-10 only (e.g. before the map has an ICD-9 section):
  python3 migrate_condition_codes.py --systems icd10 ...
In-place (overwrites ONLY the Condition table inside the source warehouse):
  python3 migrate_condition_codes.py --data /path/to/delta/warehouse \\
      --output /path/to/delta/warehouse --overwrite
Dry run (laptop, no Spark):
  python3 migrate_condition_codes.py --dry-run
"""

import argparse
import copy
import json
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_MAP = os.path.join(SCRIPT_DIR, "display-map.json")

SYSTEMS = {
    "icd10": {
        "source": "http://mimic.mit.edu/fhir/mimic/CodeSystem/mimic-diagnosis-icd10",
        "target": "http://hl7.org/fhir/sid/icd-10-cm",
    },
    "icd9": {
        "source": "http://mimic.mit.edu/fhir/mimic/CodeSystem/mimic-diagnosis-icd9",
        "target": "http://hl7.org/fhir/sid/icd-9-cm",
    },
}


def log(msg):
    """Progress logging to stderr so it interleaves with Spark's stdout."""
    print(msg, file=sys.stderr, flush=True)


# --------------------------------------------------------------------------- #
# The transform (pure, no Spark) -- shared by dry-run and the UDF.
# --------------------------------------------------------------------------- #

def load_lookup(path, keys):
    """Load display-map.json and return the migration lookup for the selected
    system keys: source system URL -> {"target": target system URL,
    "codes": {original dot-less code -> {"code","display","version"}}}."""
    with open(path) as fh:
        doc = json.load(fh)
    lookup = {}
    for key in keys:
        cfg = SYSTEMS[key]
        code_map = doc.get(cfg["target"])
        if not code_map:
            raise SystemExit(
                "map file %s has no (or an empty) '%s' section — regenerate it "
                "with check_icd_codes.py, or restrict --systems" % (path, cfg["target"]))
        missing_version = sum(1 for e in code_map.values() if not e.get("version"))
        if missing_version:
            raise SystemExit(
                "map file %s: %d '%s' entries lack a pinned 'version' — "
                "regenerate it with check_icd_codes.py --valueset ..."
                % (path, missing_version, cfg["target"]))
        lookup[cfg["source"]] = {"target": cfg["target"], "codes": code_map}
    return lookup


def migrate_coding(coding, lookup):
    """Rewrite one Coding dict. Returns (new_coding, status) with status one of
    'migrated' | 'unmapped' | 'untouched'. Never mutates the input; fields other
    than system/code/display/version (id, extension, userSelected, Pathling's
    internal _fid, ...) are carried over unchanged."""
    if not coding:
        return coding, "untouched"
    system_map = lookup.get(coding.get("system"))
    if system_map is None:
        return coding, "untouched"
    entry = system_map["codes"].get(coding.get("code"))
    if entry is None:
        return coding, "unmapped"
    new = dict(coding)
    # A per-entry "system" overrides the section default: codes mis-filed in
    # the MIMIC ICD-9 CodeSystem that are really ICD-10-CM relabel across.
    new["system"] = entry.get("system", system_map["target"])
    new["code"] = entry["code"]
    new["display"] = entry["display"]
    new["version"] = entry["version"]
    return new, "migrated"


def migrate_codeable_concept(cc, lookup):
    """Rewrite a CodeableConcept dict (Condition.code). Returns
    (new_cc, n_migrated, n_unmapped). The unmapped count should always be 0 in
    a real run because the pre-scan aborts first; it is still tracked so the
    dry-run can demonstrate the drift guard."""
    if not cc or not cc.get("coding"):
        return cc, 0, 0
    n_migrated = n_unmapped = 0
    new_codings = []
    for coding in cc["coding"]:
        new_coding, status = migrate_coding(coding, lookup)
        if status == "migrated":
            n_migrated += 1
        elif status == "unmapped":
            n_unmapped += 1
        new_codings.append(new_coding)
    new_cc = dict(cc)
    new_cc["coding"] = new_codings
    return new_cc, n_migrated, n_unmapped


# --------------------------------------------------------------------------- #
# Dry run
# --------------------------------------------------------------------------- #

SAMPLE_CONCEPTS = [
    # typical single MIMIC ICD-10 coding
    {"coding": [{"system": SYSTEMS["icd10"]["source"], "code": "A0100",
                 "display": "Typhoid fever, unspecified"}],
     "text": "Typhoid fever, unspecified"},
    # MIMIC ICD-9 codings: numeric, V-code, E-code dot placements
    {"coding": [{"system": SYSTEMS["icd9"]["source"], "code": "0389",
                 "display": "Unspecified septicemia"}]},
    {"coding": [{"system": SYSTEMS["icd9"]["source"], "code": "V4501"},
                {"system": SYSTEMS["icd9"]["source"], "code": "E8500"}]},
    # mixed codings; extra Coding fields must survive the rewrite
    {"coding": [{"system": SYSTEMS["icd10"]["source"], "code": "Z66",
                 "display": "Do not resuscitate", "userSelected": True},
                {"system": "http://snomed.info/sct", "code": "304253006"}]},
    # mis-filed code: ICD-10-CM code on the MIMIC ICD-9 system relabels across
    {"coding": [{"system": SYSTEMS["icd9"]["source"], "code": "I509",
                 "display": "Heart failure, unspecified"}]},
    # drift guard demo: a MIMIC code that is NOT in the map
    {"coding": [{"system": SYSTEMS["icd10"]["source"], "code": "NOTACODE1"}]},
]


def do_dry_run(map_path, keys):
    lookup = load_lookup(map_path, keys)
    for source, system_map in lookup.items():
        versions = {}
        for entry in system_map["codes"].values():
            versions[entry["version"]] = versions.get(entry["version"], 0) + 1
        log("DRY RUN: %s -> %s — %d codes, pinned versions: %s"
            % (source, system_map["target"], len(system_map["codes"]),
               ", ".join("%s (%d)" % kv for kv in sorted(versions.items()))))
    log("")

    for i, cc in enumerate(SAMPLE_CONCEPTS, 1):
        new_cc, n_migrated, n_unmapped = migrate_codeable_concept(
            copy.deepcopy(cc), lookup)
        print("=" * 70)
        print("SAMPLE %d  (migrated: %d, unmapped: %d%s)"
              % (i, n_migrated, n_unmapped,
                 " — a real run would ABORT on this" if n_unmapped else ""))
        print("  before: %s" % json.dumps(cc))
        print("  after:  %s" % json.dumps(new_cc))

    print("=" * 70)
    log("\nDRY RUN complete. No Spark imported, no data touched.")
    return 0


# --------------------------------------------------------------------------- #
# Pathling data access -- ADAPT HERE if Felix's warehouse layout differs.
# --------------------------------------------------------------------------- #

def open_condition_table(data_path):
    """Open the Delta warehouse via Pathling and return (pc, condition_df).

    Assumes the standard Pathling Delta warehouse layout (one Delta table per
    resource type under data_path), same as phase1_extract_distinct.py. If the
    layout differs, change ONLY this function."""
    from pathling import PathlingContext

    # Let PathlingContext build its own SparkSession: a pre-existing session
    # lacks the Pathling JVM libraries on the classpath.
    pc = PathlingContext.create()
    data = pc.read.delta(data_path)
    return pc, data.read("Condition")


def write_condition_table(pc, df, output_path, fmt, overwrite):
    """Write the migrated Condition DataFrame via a Pathling datasets sink.

    Only the Condition table is in the sink, so writing into an existing
    warehouse (with --overwrite) replaces Condition and leaves every other
    resource table alone."""
    sink = pc.read.datasets({"Condition": df})
    if fmt == "ndjson":
        sink.write.ndjson(output_path)
        return
    from pathling.datasink import SaveMode
    sink.write.delta(
        output_path,
        save_mode=SaveMode.OVERWRITE if overwrite else SaveMode.ERROR)


# --------------------------------------------------------------------------- #
# Real run
# --------------------------------------------------------------------------- #

def count_codings_by_system(df, system_urls):
    """{system_url: coding count} for the given systems in df (missing -> 0)."""
    from pyspark.sql import functions as F
    rows = (df.select(F.explode_outer("code.coding").alias("c"))
              .where(F.col("c.system").isin(list(system_urls)))
              .groupBy("c.system").count().collect())
    counts = {url: 0 for url in system_urls}
    counts.update({r["system"]: r["count"] for r in rows})
    return counts


def do_run(args, keys):
    lookup = load_lookup(args.map, keys)
    for source, system_map in lookup.items():
        log("Loaded %d mapped codes: %s -> %s"
            % (len(system_map["codes"]), source, system_map["target"]))

    if os.path.abspath(args.output) == os.path.abspath(args.data) and not args.overwrite:
        log("ERROR: --output equals --data; refusing in-place migration "
            "without --overwrite.")
        return 2

    from pyspark.sql import functions as F
    from pyspark.sql.functions import udf

    log("Opening Pathling Delta warehouse at: %s" % args.data)
    pc, df = open_condition_table(args.data)
    if args.limit:
        log("SMOKE TEST: limiting to %d Condition rows." % args.limit)
        df = df.limit(args.limit)

    source_urls = list(lookup)
    # Include per-entry system overrides (relabeled mis-filed codes), so their
    # codings are counted even when their section's default target isn't run.
    target_urls = sorted(
        {m["target"] for m in lookup.values()}
        | {e["system"] for m in lookup.values()
           for e in m["codes"].values() if "system" in e})

    # ---- Drift guard: abort before any write if the data has unmapped codes.
    log("Pre-scan: collecting distinct MIMIC ICD codes in Condition.code ...")
    rows = (df.select(F.explode_outer("code.coding").alias("c"))
              .where(F.col("c.system").isin(source_urls))
              .select("c.system", "c.code").distinct().collect())
    present = {url: set() for url in source_urls}
    for r in rows:
        if r["code"]:
            present[r["system"]].add(r["code"])
    unmapped = []
    for url, codes in present.items():
        log("Pre-scan: %d distinct codes on %s" % (len(codes), url))
        unmapped += [(url, c) for c in sorted(codes - set(lookup[url]["codes"]))]
    if unmapped:
        unmapped_path = os.path.join(SCRIPT_DIR, "unmapped-in-data.txt")
        with open(unmapped_path, "w") as fh:
            fh.write("\n".join("%s|%s" % uc for uc in unmapped) + "\n")
        log("ERROR: %d codes in the data are missing from the map "
            "(data/CodeSystem drift) — list written to %s. Nothing was written; "
            "regenerate display-map.json and re-run." % (len(unmapped), unmapped_path))
        return 3

    before = count_codings_by_system(df, source_urls)
    log("Codings to migrate: %s" % json.dumps(before))

    # ---- Transform. The UDF's return type is the DataFrame's OWN schema for
    # Condition.code, so the output schema matches the Pathling encoding by
    # construction, whatever version produced the warehouse.
    code_type = df.schema["code"].dataType

    def _rewrite(code_row):
        if code_row is None:
            return None
        cc = code_row.asDict(recursive=True)
        new_cc, _, _ = migrate_codeable_concept(cc, lookup)
        return new_cc

    out_df = df.withColumn("code", udf(_rewrite, code_type)(F.col("code")))

    log("Writing migrated Condition table (%s) to: %s" % (args.format, args.output))
    write_condition_table(pc, out_df, args.output, args.format, args.overwrite)

    # ---- Verify what actually landed on disk, not the in-memory plan.
    log("Verifying written output ...")
    if args.format == "ndjson":
        verify_df = pc.read.ndjson(args.output).read("Condition")
    else:
        verify_df = pc.read.delta(args.output).read("Condition")
    residual = count_codings_by_system(verify_df, source_urls)
    target_rows = (verify_df
                   .select(F.explode_outer("code.coding").alias("c"))
                   .where(F.col("c.system").isin(target_urls))
                   .groupBy("c.system", "c.version").count().collect())
    per_version = {}
    for r in target_rows:
        per_version.setdefault(r["system"], {})[r["version"] or "(none)"] = r["count"]
    migrated_total = sum(sum(v.values()) for v in per_version.values())

    report = {
        "data": args.data,
        "output": args.output,
        "format": args.format,
        "systems": keys,
        "condition_rows": verify_df.count(),
        "distinct_source_codes_in_data": {u: len(c) for u, c in present.items()},
        "codings_on_source_systems_before": before,
        "codings_on_target_systems_after": {
            u: sum(v.values()) for u, v in per_version.items()},
        "codings_per_pinned_version": {
            u: dict(sorted(v.items())) for u, v in sorted(per_version.items())},
        "residual_source_system_codings": residual,
        "ok": (sum(residual.values()) == 0
               and migrated_total >= sum(before.values())),
    }
    report_path = os.path.join(
        os.path.dirname(os.path.abspath(args.output)) or ".",
        "migration-report.json")
    with open(report_path, "w") as fh:
        json.dump(report, fh, indent=2)

    log("\n%s" % json.dumps(report, indent=2))
    if not report["ok"]:
        log("ERROR: verification failed (residual old-system codings, or fewer "
            "target codings than expected) — inspect %s" % report_path)
        return 4
    log("Done. Report -> %s" % report_path)
    return 0


# --------------------------------------------------------------------------- #

def parse_args(argv):
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--data", default=os.environ.get("MIMIC_WAREHOUSE"),
                   help="Path to the Pathling Delta warehouse (one table per "
                        "resource type). Default: $MIMIC_WAREHOUSE.")
    p.add_argument("--output",
                   help="Where to write the migrated Condition table. Point it at "
                        "--data itself (with --overwrite) for in-place migration.")
    p.add_argument("--map", default=DEFAULT_MAP,
                   help="Path to display-map.json (default: next to this script).")
    p.add_argument("--systems", choices=["icd10", "icd9", "both"], default="both",
                   help="Which MIMIC source systems to migrate (default: %(default)s).")
    p.add_argument("--format", choices=["delta", "ndjson"], default="delta",
                   help="Output format (default: %(default)s).")
    p.add_argument("--overwrite", action="store_true",
                   help="Allow overwriting an existing Condition table at --output "
                        "(required for in-place migration).")
    p.add_argument("--limit", type=int,
                   help="Smoke test: migrate only the first N Condition rows.")
    p.add_argument("--dry-run", action="store_true",
                   help="Run the transform on built-in samples without importing Spark.")
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv if argv is not None else sys.argv[1:])
    keys = ["icd10", "icd9"] if args.systems == "both" else [args.systems]
    if args.dry_run:
        return do_dry_run(args.map, keys)
    if not args.data or not args.output:
        log("ERROR: --data and --output are required for a real run (or use --dry-run).")
        return 2
    return do_run(args, keys)


if __name__ == "__main__":
    sys.exit(main())
