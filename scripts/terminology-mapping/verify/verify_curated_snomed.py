#!/usr/bin/env python3
"""Check every SNOMED code in a curated mapping table against a real server.

Why this is a SEPARATE script and not part of verify_mappings.py: it needs the
network, and `make mappings` is deliberately offline and instant. Run it when
you touch a curated table, not on every build.

Why it exists at all: the rest of this pipeline maps by rule, so a wrong target
is a bug you can read in the code. A curated table maps by judgement, and its
failure mode is a plausible-looking concept id that is retired, that belongs to
a national extension, or that simply is not the concept whose name sits next to
it in the CSV. None of those are visible by inspection, and all of them survive
a build. Four checks, all of them things a human cannot verify by eye:

1. the code exists                — a typo'd concept id is otherwise silent
2. the concept is active          — SNOMED retires concepts, and a curated
                                    table ages; 9 targets from an earlier
                                    OHDSI-sourced table had been
                                    retired by the time this repo used them
3. the module is the international core, not a national extension — an
   AU/US/NL-only concept resolves fine on the server it was picked from and
   nowhere else, which is the least reproducible failure there is
4. snomed_display matches a designation of the concept — this is what catches
   a row whose code and name have drifted apart, i.e. a mapping that reads
   correctly and means something else

Usage:
  uv run scripts/terminology-mapping/verify/verify_curated_snomed.py
  uv run scripts/terminology-mapping/verify/verify_curated_snomed.py --fix-displays
"""

import argparse
import csv
import json
import sys
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.cli import add_common_args, resolve  # noqa: E402
from common.fhirclient import http  # noqa: E402
from conceptmaps.lib.canonical import SNOMED, TABLE_DIR  # noqa: E402

# The SNOMED CT international core module. Anything else is a national
# extension: it resolves on the server it was authored against and nowhere
# else, so a mapping into one cannot be reproduced by a consumer.
INTL_MODULE = "900000000000207008"


def lookup(fhir_base, code):
    """(active, module, {designations}) for a SNOMED code, or None if absent."""
    query = urllib.parse.urlencode({"system": SNOMED, "code": code})
    status, body = http(
        "GET", f"{fhir_base.rstrip('/')}/CodeSystem/$lookup?{query}")
    if status != 200 or not body or body.get("resourceType") != "Parameters":
        return None
    active, module, names = True, None, set()
    for parameter in body.get("parameter", []):
        if parameter["name"] == "display":
            names.add(parameter["valueString"])
        elif parameter["name"] == "property":
            part = {p["name"]: p for p in parameter["part"]}
            key = part["code"]["valueCode"]
            value = part.get("value", {})
            if key == "inactive":
                active = not value.get("valueBoolean", False)
            elif key == "moduleId":
                module = value.get("valueCode")
        elif parameter["name"] == "designation":
            for p in parameter["part"]:
                if p["name"] == "value":
                    names.add(p["valueString"])
    return active, module, names


def snomed_columns(fieldnames):
    """(code column, display column, system column) for this table's SNOMED
    targets, or None if it holds none.

    Two table shapes, and the header is what distinguishes them — see
    conceptmaps/lib/curated.py. A SINGLE-TARGET table names its terminology in
    the heading, so `snomed_code` present means every row is SNOMED. A
    MIXED-TARGET table names the system per row, so the SNOMED rows are a SUBSET
    selected by `target_system` and the other rows belong to a terminology this
    script has nothing to say about.

    Keyed on the header rather than on the filename: `*-standard.csv` is the
    mixed-target naming convention, but a check that silently passes because it
    matched no glob is exactly the failure this script exists to prevent.
    """
    if "snomed_code" in fieldnames:
        return "snomed_code", "snomed_display", None
    if "target_code" in fieldnames and "target_system" in fieldnames:
        return "target_code", "target_display", "target_system"
    return None


def check_table(path, fhir_base, fix_displays):
    rows = list(csv.DictReader(open(path, newline="")))
    columns = snomed_columns(rows[0].keys() if rows else [])
    if columns is None:
        print(f"\n== {path.name} ==")
        print("  no SNOMED target column — skipped")
        return []
    code_column, display_column, system_column = columns

    mapped = [r for r in rows if (r[code_column] or "").strip()
              and (system_column is None
                   or (r[system_column] or "").strip() == SNOMED)]
    print(f"\n== {path.name} ==")
    if system_column:
        other = sum(1 for r in rows if (r[code_column] or "").strip()
                    and (r[system_column] or "").strip() != SNOMED)
        print(f"  {len(rows)} row(s), {len(mapped)} with a SNOMED target, "
              f"{other} targeting another system (not this script's business)")
    else:
        print(f"  {len(rows)} row(s), {len(mapped)} with a target, "
              f"{len(rows) - len(mapped)} declared non-mappings")

    seen, problems, fixed = {}, [], 0
    for row in mapped:
        code = row[code_column].strip()
        if code not in seen:
            seen[code] = lookup(fhir_base, code)
        result = seen[code]

        if result is None:
            problems.append(f"{row['mimic_code']} -> {code}: NOT FOUND on the "
                            f"server")
            continue
        active, module, names = result
        if not active:
            problems.append(f"{row['mimic_code']} -> {code} "
                            f"({row[display_column]}): RETIRED — find its "
                            f"replacement")
        if module != INTL_MODULE:
            problems.append(f"{row['mimic_code']} -> {code} "
                            f"({row[display_column]}): module {module} is "
                            f"not the international core")
        if row[display_column].strip() not in names:
            if fix_displays and names:
                row[display_column] = sorted(names, key=len)[0]
                fixed += 1
            else:
                problems.append(
                    f"{row['mimic_code']} -> {code}: display "
                    f"{row[display_column]!r} is not a designation of this "
                    f"concept. Server has e.g. {sorted(names)[:2]}")

    if fixed:
        with open(path, "w", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        print(f"  rewrote {fixed} display(s)")

    print(f"  {len(seen)} distinct concept(s) checked")
    for problem in problems:
        print(f"  FAIL  {problem}")
    if not problems:
        print("  all targets exist, are active, are international, and their "
              "displays match")
    return problems


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fix-displays", action="store_true",
                    help="rewrite a display that is not a designation of its "
                         "concept, instead of failing. Only ever changes the "
                         "display — a wrong CODE is still your problem.")
    add_common_args(ap)
    args = ap.parse_args()
    resolve(args)

    if not args.fhir_base:
        sys.exit("no --fhir-base and ONTOSERVER_URL unset — this check needs a "
                 "terminology server holding SNOMED CT")

    # Discovered by glob rather than by walking a registry: with one builder
    # script per population there is no shared FIELDS dict to walk, and a table
    # is checkable on its own terms regardless of which builder declares it.
    #
    # `*-standard.csv` as well as `*-snomed.csv`: a MIXED-TARGET table carries
    # SNOMED rows alongside rows in another terminology, and those SNOMED codes
    # age exactly like any other — retired concepts and national-extension
    # concepts are precisely what this script exists to catch, and a table
    # excluded by the glob would have been checked by nothing at all.
    # check_table reads the header to decide which columns hold the SNOMED
    # target and which rows carry one.
    tables = sorted(set(TABLE_DIR.glob("*-snomed.csv"))
                    | set(TABLE_DIR.glob("*-standard.csv")))
    if not tables:
        print(f"no curated tables with SNOMED targets in {TABLE_DIR}")
        return 0

    problems = []
    for path in tables:
        problems += check_table(path, args.fhir_base, args.fix_displays)

    if problems:
        print(f"\n{len(problems)} problem(s). A curated mapping is only as "
              f"good as the concept it names.")
        return 1
    print("\nall curated tables verified")
    return 0


if __name__ == "__main__":
    sys.exit(main())
