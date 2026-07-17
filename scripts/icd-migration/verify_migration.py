#!/usr/bin/env python3
"""Independently verify the output of migrate_condition_codes.py.

Compares the migrated Condition table against the SOURCE warehouse row by row,
re-deriving the expected result from display-map.json (i.e. it does not trust
migration-report.json). Checks:

  1. Same set of Condition ids, no rows lost or invented.
  2. Zero codings left on the MIMIC dot-less source systems.
  3. Every source MIMIC coding was rewritten EXACTLY as the map dictates
     (target system, dotted code, official display, pinned version), with all
     other Coding fields carried over unchanged.
  4. Every non-MIMIC coding (SNOMED etc.) passed through byte-identical.
  5. Coding list length and order preserved per Condition.
  6. Sanity on pins: every ICD-9-CM version is 2012; no empty/missing versions.

Usage:
  uv run python scripts/icd-migration/verify_migration.py \
      --source /path/to/spark-warehouse --migrated transformed_data
"""

import argparse
import json
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_MAP = os.path.join(SCRIPT_DIR, "display-map.json")

SOURCE_SYSTEMS = {
    "http://mimic.mit.edu/fhir/mimic/CodeSystem/mimic-diagnosis-icd10":
        "http://hl7.org/fhir/sid/icd-10-cm",
    "http://mimic.mit.edu/fhir/mimic/CodeSystem/mimic-diagnosis-icd9":
        "http://hl7.org/fhir/sid/icd-9-cm",
}
ICD9_TARGET = "http://hl7.org/fhir/sid/icd-9-cm"


def log(msg):
    print(msg, file=sys.stderr, flush=True)


def strip_internal(d):
    """Drop Pathling-internal keys (leading underscore, e.g. _fid) and nulls,
    recursively, so dict comparison reflects FHIR content only."""
    if isinstance(d, dict):
        return {k: strip_internal(v) for k, v in d.items()
                if not k.startswith("_") and v is not None}
    if isinstance(d, list):
        return [strip_internal(v) for v in d]
    return d


def expected_coding(coding, code_maps):
    """Re-derive what the migration should have produced for one source coding."""
    target = SOURCE_SYSTEMS.get(coding.get("system"))
    if target is None:
        return coding  # non-MIMIC: must pass through unchanged
    entry = code_maps[target].get(coding.get("code"))
    if entry is None:
        return None  # unmapped — the migration should have ABORTED on this
    new = dict(coding)
    new["system"] = entry.get("system", target)
    new["code"] = entry["code"]
    new["display"] = entry["display"]
    new["version"] = entry["version"]
    return new


def collect_codes(path, label):
    """Read a Delta Condition table -> {id: [coding dicts]} (order preserved).

    A '@vN' suffix (e.g. /warehouse@v0) time-travels to Delta version N —
    lets the ORIGINAL data serve as --source after an in-place migration."""
    from pathling import PathlingContext
    global _PC
    try:
        pc = _PC
    except NameError:
        pc = _PC = PathlingContext.create()
    if "@v" in path:
        path, _, version = path.rpartition("@v")
        df = (pc.spark.read.format("delta")
              .option("versionAsOf", int(version))
              .load(os.path.join(path, "Condition.parquet"))
              .select("id", "code"))
        path = "%s (delta version %s)" % (path, version)
    else:
        df = pc.read.delta(path).read("Condition").select("id", "code")
    out = {}
    for row in df.collect():
        d = row.asDict(recursive=True)
        cc = d.get("code") or {}
        out[d["id"]] = strip_internal(cc.get("coding") or [])
    log("%s: %d Condition rows read from %s" % (label, len(out), path))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source", default=os.environ.get("MIMIC_WAREHOUSE"),
                    required="MIMIC_WAREHOUSE" not in os.environ,
                    help="Path to the ORIGINAL Delta warehouse "
                         "(default: $MIMIC_WAREHOUSE).")
    ap.add_argument("--migrated", required=True,
                    help="Path to the migrated output warehouse.")
    ap.add_argument("--map", default=DEFAULT_MAP)
    ap.add_argument("--max-examples", type=int, default=5)
    args = ap.parse_args()

    with open(args.map) as fh:
        code_maps = json.load(fh)

    src = collect_codes(args.source, "source")
    mig = collect_codes(args.migrated, "migrated")

    problems = []
    stats = {"conditions": len(src), "codings_checked": 0, "migrated": 0,
             "passthrough": 0, "per_version": {}}

    # 1. id sets
    missing = set(src) - set(mig)
    extra = set(mig) - set(src)
    if missing:
        problems.append("%d Condition ids missing from output, e.g. %s"
                        % (len(missing), sorted(missing)[:args.max_examples]))
    if extra:
        problems.append("%d unexpected Condition ids in output, e.g. %s"
                        % (len(extra), sorted(extra)[:args.max_examples]))

    residual = 0
    mismatch_examples = []
    for cid, src_codings in src.items():
        mig_codings = mig.get(cid)
        if mig_codings is None:
            continue
        # 5. list length/order
        if len(mig_codings) != len(src_codings):
            mismatch_examples.append(
                (cid, "coding count %d -> %d" % (len(src_codings), len(mig_codings))))
            continue
        for before, after in zip(src_codings, mig_codings):
            stats["codings_checked"] += 1
            # 2. residual source systems
            if after.get("system") in SOURCE_SYSTEMS:
                residual += 1
            exp = expected_coding(before, code_maps)
            if exp is None:
                mismatch_examples.append(
                    (cid, "source code %s|%s not in display-map (drift guard "
                          "should have aborted)" % (before.get("system"), before.get("code"))))
                continue
            exp = strip_internal(exp)
            if after != exp:  # 3. exact rewrite / 4. exact passthrough
                mismatch_examples.append(
                    (cid, "expected %s got %s" % (json.dumps(exp, sort_keys=True),
                                                  json.dumps(after, sort_keys=True))))
                continue
            if before.get("system") in SOURCE_SYSTEMS:
                stats["migrated"] += 1
                v = after.get("version")
                key = "%s|%s" % (after["system"], v)
                stats["per_version"][key] = stats["per_version"].get(key, 0) + 1
                # 6. version sanity
                if not v:
                    mismatch_examples.append((cid, "migrated coding has no version: %s"
                                              % json.dumps(after)))
                elif after["system"] == ICD9_TARGET and v != "2012":
                    mismatch_examples.append((cid, "ICD-9-CM pinned to %s, expected 2012" % v))
            else:
                stats["passthrough"] += 1

    if residual:
        problems.append("%d codings still on MIMIC source systems" % residual)
    if mismatch_examples:
        problems.append("%d coding mismatches, e.g.:\n    %s" % (
            len(mismatch_examples),
            "\n    ".join("%s: %s" % ex for ex in mismatch_examples[:args.max_examples])))

    print(json.dumps({"stats": {**stats, "per_version": dict(sorted(stats["per_version"].items()))}},
                     indent=2))
    if problems:
        print("\nFAIL — %d problem(s):" % len(problems))
        for p in problems:
            print("  - %s" % p)
        return 1
    print("\nPASS — output matches the expected transform exactly.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
