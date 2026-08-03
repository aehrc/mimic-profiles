#!/usr/bin/env python3
"""Verify the generated ConceptMaps and ValueSets, and gate publication.

This is stage 5's gatekeeper and the thing you read before deciding to publish.
It re-derives NOTHING: no dot rules, no code conversion, no "is this code in
that release" logic. Those live once, in ../conceptmaps/build_conceptmap.py.
This reads the generated artefacts and checks properties of them.

Checks
------
1. Coverage. Every code in each bound MIMIC ValueSet is either mapped by the
   ConceptMap or listed in unmapped-<field>.csv. Nothing may be silently
   absent from both.

2. ValueSet == ConceptMap target side. The value set is the map's
   targetCanonical, so "member of the value set" and "reachable by $translate"
   must be the same set. A drift here means the two were built from different
   inputs.

3. Every (system, version) the artefacts reference is one we actually built.
   A shared terminology server can hold releases this repo has no source for;
   pinning a code into one produces an artefact that cannot be reproduced or
   redistributed. Caught here rather than at $expand time on someone else's
   server.

4. No MIMIC ICD-9 procedure code maps to an ICD-10-PCS grouper. 64 of MIMIC's
   2,544 ICD-9 procedure codes are verbatim valid 4-character PCS body-part
   groupers: procedure 0095 means ICD-9 00.95, but as a raw string it matches
   PCS 0095 "Subarachnoid Space, Intracranial". Such a mapping would point a
   procedure at an anatomical structure AND make the unmapped report read
   zero, so it is checked explicitly rather than trusted to stay correct.

Exits non-zero when any code is unmapped or any invariant fails, which is what
stops `make upload-mappings`. --allow-unmapped downgrades the unmapped count to
a warning once you have reviewed the CSV; it does NOT relax checks 2-4, which
are correctness bugs rather than data gaps.

Usage:
  uv run scripts/terminology-mapping/verify/verify_mappings.py
  uv run scripts/terminology-mapping/verify/verify_mappings.py --allow-unmapped
"""

import argparse
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common import paths  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "conceptmaps"))
from build_conceptmap import (  # noqa: E402
    FIELDS, ICD10_PCS, MIMIC_BASE, RESOURCES, concept_properties,
)

PROCEDURE_ICD9_SOURCE = f"{MIMIC_BASE}/CodeSystem/mimic-procedure-icd9"


def load(path, what):
    if not path.is_file():
        sys.exit(f"missing {what}: {path} — run the earlier stages first")
    return json.loads(path.read_text())


def built_releases(out_dir):
    """{(url, version)} for every CodeSystem this repo built."""
    releases = set()
    for path in sorted(out_dir.glob("CodeSystem-*.json")):
        cs = json.loads(path.read_text())
        if not cs["url"].startswith(MIMIC_BASE):
            releases.add((cs["url"], cs["version"]))
    return releases


def pcs_groupers(out_dir):
    """Every non-leaf ICD-10-PCS concept, across releases."""
    groupers = set()
    for path in sorted(out_dir.glob("CodeSystem-icd-10-pcs-*.json")):
        cs = json.loads(path.read_text())
        for concept in cs["concept"]:
            props = concept_properties(concept)
            if len(concept["code"]) != 7 or props.get("notSelectable"):
                groupers.add(concept["code"])
    return groupers


def mimic_codes(field):
    """{(source system, code)} for the whole bound MIMIC ValueSet."""
    codes = set()
    for source in field["sources"]:
        path = RESOURCES / source["file"]
        if path.is_file():
            cs = json.loads(path.read_text())
            codes |= {(source["system"], c["code"]) for c in cs.get("concept", [])}
    return codes


def check_field(key, field, out_dir, releases, groupers):
    print(f"\n== {key} ({field['element']}) ==")
    failures, warnings = [], []

    conceptmap = load(out_dir / f"ConceptMap-{field['id']}.json", "ConceptMap")
    valueset = load(out_dir / f"ValueSet-{field['target_valueset'].rsplit('/', 1)[-1]}.json",
                    "ValueSet")

    # A source code is MAPPED only if it has a target with a code. An
    # `unmatched` target records "considered, deliberately not mapped" and
    # carries no code, so it counts as declared-unmapped, not mapped.
    mapped, declared_unmatched = set(), set()
    for group in conceptmap["group"]:
        for element in group["element"]:
            entry = (group["source"], element["code"])
            if any(t.get("code") for t in element.get("target", [])):
                mapped.add(entry)
            else:
                declared_unmatched.add(entry)
    source = mimic_codes(field)

    csv_path = out_dir / f"unmapped-{key}.csv"
    listed = set()
    if csv_path.is_file():
        with open(csv_path) as fh:
            listed = {(r["source_system"], r["mimic_code"])
                      for r in csv.DictReader(fh)}

    # 1. coverage
    missing = source - mapped - declared_unmatched - listed
    print(f"  coverage        {len(mapped):,}/{len(source):,} mapped, "
          f"{len(declared_unmatched)} declared unmatched in the map, "
          f"{len(listed)} listed in the CSV")
    if missing:
        failures.append(f"{len(missing)} code(s) neither mapped nor recorded as "
                        f"unmatched, e.g. {sorted(missing)[:5]}")
    # The map and the CSV must agree about what is unmapped, or one of them is
    # stale and the gate would be reading the wrong number.
    if declared_unmatched != listed:
        failures.append(
            f"the ConceptMap's `unmatched` entries and {csv_path.name} disagree: "
            f"{len(declared_unmatched - listed)} only in the map, "
            f"{len(listed - declared_unmatched)} only in the CSV")
    if listed:
        warnings.append(f"{len(listed)} unmapped code(s) in {csv_path.name}")

    # 2. ValueSet == ConceptMap target side
    cm_targets = {(g["target"], g["targetVersion"], t["code"])
                  for g in conceptmap["group"] if g.get("target")
                  for e in g["element"] for t in e.get("target", [])
                  if t.get("code")}
    vs_members = {(i["system"], i["version"], c["code"])
                  for i in valueset["compose"]["include"]
                  for c in i.get("concept", [])}
    if cm_targets != vs_members:
        only_cm, only_vs = cm_targets - vs_members, vs_members - cm_targets
        failures.append(
            f"ValueSet and ConceptMap target side disagree: "
            f"{len(only_cm)} only in the map, {len(only_vs)} only in the "
            f"value set (e.g. {sorted(only_cm or only_vs)[:3]})")
    else:
        print(f"  vs == cm        {len(vs_members):,} target codes, identical")

    # 3. only releases we built. Unmatched groups name the system they
    # searched but no version — the code is in none of them — so they pin no
    # release and there is nothing here to account for.
    referenced = {(g["target"], g["targetVersion"])
                  for g in conceptmap["group"] if g.get("targetVersion")}
    referenced |= {(i["system"], i["version"])
                   for i in valueset["compose"]["include"]}
    unbuilt = referenced - releases
    if unbuilt:
        failures.append(f"references release(s) this repo did not build: "
                        f"{sorted(unbuilt)}")
    else:
        print(f"  releases        {len(referenced)} referenced, all built here")

    # 4. the PCS grouper collision
    collisions = [
        (e["code"], t["code"])
        for g in conceptmap["group"] if g.get("target") == ICD10_PCS
        for e in g["element"] for t in e.get("target", [])
        if t.get("code") in groupers
    ]
    if collisions:
        failures.append(f"{len(collisions)} code(s) mapped to an ICD-10-PCS "
                        f"grouper rather than a 7-character leaf, e.g. "
                        f"{collisions[:5]}")
    else:
        print("  pcs groupers    none mapped (guard holds)")

    for warning in warnings:
        print(f"  WARN  {warning}")
    for failure in failures:
        print(f"  FAIL  {failure}")
    return failures, len(listed)


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out-dir", type=Path, default=paths.OUTPUT)
    ap.add_argument("--allow-unmapped", action="store_true",
                    help="treat unmapped codes as a warning once reviewed; does "
                         "not relax the correctness checks")
    args = ap.parse_args()

    releases = built_releases(args.out_dir)
    groupers = pcs_groupers(args.out_dir)
    print(f"built releases: {len(releases)}  "
          f"({', '.join(sorted(f'{u.rsplit('/', 1)[-1]}|{v}' for u, v in releases))})")
    print(f"PCS non-leaf concepts (collision set): {len(groupers):,}")

    report, failed, unmapped_total = {}, False, 0
    for key, field in sorted(FIELDS.items()):
        failures, unmapped = check_field(key, field, args.out_dir, releases, groupers)
        report[key] = {"failures": failures, "unmapped": unmapped}
        unmapped_total += unmapped
        failed |= bool(failures)

    path = args.out_dir / "coverage-report.json"
    path.write_text(json.dumps(report, indent=1) + "\n")
    print(f"\nwrote {path.name}")

    if failed:
        sys.exit("\nFAILED: see the checks above. These are correctness "
                 "problems, not data gaps — --allow-unmapped will not bypass them.")
    if unmapped_total and not args.allow_unmapped:
        sys.exit(f"\nREFUSING to pass: {unmapped_total} unmapped code(s). Review "
                 f"the unmapped-*.csv files, then re-run with --allow-unmapped "
                 f"to publish anyway.")
    print("\nOK" + (f" ({unmapped_total} unmapped, explicitly allowed)"
                    if unmapped_total else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
