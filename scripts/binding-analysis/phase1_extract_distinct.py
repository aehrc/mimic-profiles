#!/usr/bin/env python3
"""Phase 1: extract distinct coded values per candidate element from MIMIC-on-FHIR.

Reads scripts/binding-analysis/work-items.json (produced by phase0_candidates.py),
and for each candidate element runs a Pathling SQL-on-FHIR view query against the Delta
warehouse to collect distinct (system, code, display, count) tuples, restricted to
resource instances whose meta.profile contains the candidate's profile URL.

Runs on a CSIRO HPC node (Spark + pathling, Delta-format MIMIC-on-FHIR, no internet).
Cannot be tested against real data here, so:
  * every environment assumption sits behind a CLI flag,
  * `--dry-run` prints the planned queries WITHOUT importing pathling/pyspark,
  * each work item is wrapped in try/except so one bad FHIRPath cannot kill the run.

Outputs:
  * <output> (default distinct-codes.ndjson): one JSON object per distinct code:
      {"profile_id","element_id","type","system","code","display","n"}
  * extract-summary.json: per-item row_count / distinct_count / "no_data" / error.

Usage (on the node):
  python3 phase1_extract_distinct.py --data /path/to/delta/warehouse
Dry run (laptop, no Spark):
  python3 phase1_extract_distinct.py --dry-run
"""

import argparse
import json
import os
import sys
import traceback
from collections import defaultdict

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_WORK_ITEMS = os.path.join(SCRIPT_DIR, "work-items.json")


def log(msg):
    """Progress logging to stderr so it interleaves with Spark's stdout."""
    print(msg, file=sys.stderr, flush=True)


# --------------------------------------------------------------------------- #
# Query planning (pure, no Spark) -- shared by dry-run and the real run.
# --------------------------------------------------------------------------- #

def profile_filter(profile_url):
    """FHIRPath filter selecting instances claiming this profile in meta.profile."""
    return "meta.profile.where($this = '%s').exists()" % profile_url


def plan_select(item):
    """Return the SQL-on-FHIR `select` clause for one work item.

    * CodeableConcept / Coding items have `extract_path` already pointing at the
      Coding (the `.coding` tail is pre-appended for CodeableConcept in phase 0):
      forEach over the Coding collection, reading system/code/display from each.
      forEach keeps the three columns aligned per Coding (no cross-join), and
      instances without the element simply contribute no rows.
    * Bare `code`-typed items: the path itself is the code; system/display absent.
    """
    path = item["extract_path"]
    if item.get("type") == "code":
        return [{"column": [{"path": path, "name": "code"}]}]
    return [{
        "forEach": path,
        "column": [
            {"path": "system", "name": "system"},
            {"path": "code", "name": "code"},
            {"path": "display", "name": "display"},
        ],
    }]


def plan_item(item):
    """Full plan for one work item: resource type, where clause, select clause."""
    return {
        "resource_type": item["resource_type"],
        "profile_url": item["profile_url"],
        "where": [{"path": profile_filter(item["profile_url"])}],
        "select": plan_select(item),
    }


# --------------------------------------------------------------------------- #
# Loading / filtering work items
# --------------------------------------------------------------------------- #

def load_work_items(path, profiles=None, resource_types=None):
    with open(path) as fh:
        doc = json.load(fh)
    items = doc.get("candidates", [])
    if profiles:
        wanted = set(profiles)
        items = [i for i in items if i["profile_id"] in wanted]
    if resource_types:
        wanted = set(resource_types)
        items = [i for i in items if i["resource_type"] in wanted]
    return items


def group_items(items):
    """Group work items by (resource_type, profile_url), preserving order."""
    groups = defaultdict(list)
    for item in items:
        groups[(item["resource_type"], item["profile_url"])].append(item)
    return groups


# --------------------------------------------------------------------------- #
# Pathling data access -- ADAPT HERE if Felix's warehouse layout differs.
# --------------------------------------------------------------------------- #

def open_pathling_data(data_path):
    """Create a PathlingContext and open the Delta warehouse.

    Assumes the standard Pathling Delta warehouse layout: one Delta table per
    resource type under `data_path` (e.g. .../Condition, .../Encounter). If Felix's
    layout differs (e.g. individual .parquet, or ndjson), change ONLY this function.
    """
    from pathling import PathlingContext

    # Let PathlingContext build its own SparkSession: a pre-existing session
    # lacks the Pathling JVM libraries on the classpath, which surfaces as
    # "TypeError: 'JavaPackage' object is not callable".
    pc = PathlingContext.create()
    data = pc.read.delta(data_path)
    return pc, data


def run_extract(data, item):
    """Run one SQL-on-FHIR view query for a work item; return a Spark DataFrame.

    Uses `DataSource.view(resource, select=[...], where=[...])` (Pathling 7+;
    the old `extract` API was removed). One view per work item -- never combine
    multiple collection columns across items.
    """
    plan = plan_item(item)
    return data.view(
        plan["resource_type"],
        select=plan["select"],
        where=plan["where"],
    )


# --------------------------------------------------------------------------- #
# Dry run
# --------------------------------------------------------------------------- #

def do_dry_run(items):
    groups = group_items(items)
    log("DRY RUN: %d work items in %d (resource_type, profile) groups\n"
        % (len(items), len(groups)))
    n = 0
    for (rtype, purl), group in groups.items():
        print("=" * 70)
        print("RESOURCE TYPE: %s" % rtype)
        print("PROFILE:       %s" % purl)
        print("FILTER:        %s" % profile_filter(purl))
        print("-" * 70)
        for item in group:
            n += 1
            plan = plan_item(item)
            print("  [%d] %s (%s)" % (n, item["element_id"], item["type"]))
            print("       select: %s" % json.dumps(plan["select"]))
        print()
    log("DRY RUN complete: %d items planned." % n)
    return 0


# --------------------------------------------------------------------------- #
# Real run
# --------------------------------------------------------------------------- #

def do_run(items, data_path, output_path):
    if not data_path:
        log("ERROR: --data is required for a real run (or use --dry-run).")
        return 2

    from pyspark.sql import functions as F

    log("Opening Pathling Delta warehouse at: %s" % data_path)
    _, data = open_pathling_data(data_path)

    groups = group_items(items)
    total = len(items)
    summary = []
    i = 0

    out_dir = os.path.dirname(os.path.abspath(output_path)) or "."
    summary_path = os.path.join(out_dir, "extract-summary.json")

    with open(output_path, "w") as out:
        for (rtype, purl), group in groups.items():
            for item in group:
                i += 1
                label = "%s / %s" % (item["profile_id"], item["element_id"])
                try:
                    df = run_extract(data, item)
                    # Aggregate distinct (system, code, display) with counts.
                    have = set(df.columns)
                    grp_cols = [c for c in ("system", "code", "display") if c in have]
                    agg = df.groupBy(*grp_cols).agg(F.count(F.lit(1)).alias("n"))
                    rows = agg.collect()

                    row_count = 0
                    distinct = 0
                    for r in rows:
                        d = r.asDict()
                        out.write(json.dumps({
                            "profile_id": item["profile_id"],
                            "element_id": item["element_id"],
                            "type": item["type"],
                            "system": d.get("system"),
                            "code": d.get("code"),
                            "display": d.get("display"),
                            "n": d["n"],
                        }) + "\n")
                        row_count += d["n"]
                        distinct += 1
                    out.flush()

                    status = "no_data" if distinct == 0 else "ok"
                    summary.append({
                        "profile_id": item["profile_id"],
                        "element_id": item["element_id"],
                        "resource_type": rtype,
                        "row_count": row_count,
                        "distinct_count": distinct,
                        "status": status,
                    })
                    log("[%d/%d] %s | %s -> %d distinct (%s)"
                        % (i, total, item["profile_id"], item["element_id"],
                           distinct, status))
                except Exception as exc:  # noqa: BLE001 -- one bad item must not kill the run
                    err = "".join(traceback.format_exception_only(type(exc), exc)).strip()
                    summary.append({
                        "profile_id": item["profile_id"],
                        "element_id": item["element_id"],
                        "resource_type": rtype,
                        "status": "error",
                        "error": err,
                    })
                    log("[%d/%d] %s | %s -> ERROR: %s"
                        % (i, total, item["profile_id"], item["element_id"], err))

    with open(summary_path, "w") as sh:
        json.dump({
            "total_items": total,
            "ok": sum(1 for s in summary if s.get("status") == "ok"),
            "no_data": sum(1 for s in summary if s.get("status") == "no_data"),
            "errors": sum(1 for s in summary if s.get("status") == "error"),
            "items": summary,
        }, sh, indent=2)

    log("\nDone. Codes -> %s ; summary -> %s" % (output_path, summary_path))
    return 0


# --------------------------------------------------------------------------- #

def parse_args(argv):
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--work-items", default=DEFAULT_WORK_ITEMS,
                   help="Path to work-items.json (default: next to this script).")
    p.add_argument("--data",
                   help="Path to the Pathling Delta warehouse (one table per resource type).")
    p.add_argument("--output", default="distinct-codes.ndjson",
                   help="Output NDJSON path (default: distinct-codes.ndjson).")
    p.add_argument("--dry-run", action="store_true",
                   help="Print planned queries without importing Spark/pathling.")
    p.add_argument("--profiles", nargs="+", metavar="PROFILE_ID",
                   help="Only run these profile_id values (partial run).")
    p.add_argument("--resource-types", nargs="+", metavar="RESOURCE_TYPE",
                   help="Only run these resource_type values (partial run).")
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv if argv is not None else sys.argv[1:])
    items = load_work_items(args.work_items, args.profiles, args.resource_types)
    log("Loaded %d work item(s) from %s" % (len(items), args.work_items))
    if not items:
        log("No work items match the given filters; nothing to do.")
        return 0
    if args.dry_run:
        return do_dry_run(items)
    return do_run(items, args.data, args.output)


if __name__ == "__main__":
    sys.exit(main())
