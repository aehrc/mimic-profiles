#!/usr/bin/env python3
"""Verify the generated ConceptMap / ValueSet pairs.

This is what you read before deciding to publish. It re-derives NO mapping: no
dot rules, no code conversion, no "is this code in that release" logic. Those
live once, in conceptmaps/lib/. This reads the generated artefacts and checks
properties of them.

Discovery, not a registry
-------------------------
There is no shared FIELDS dict any more — one builder script per population, each
owning its own declaration. So this script finds the populations by globbing
`conceptmaps/build_*_cm_vs.py` and reading each module's FIELD / SOURCES / META,
then locates that population's artefacts from META. Adding a population needs no
edit here.

Why it imports SOURCES rather than working from the ConceptMap alone: check 1
compares the map against an INDEPENDENT enumeration of the IG's own
CodeSystems and ValueSets. Derived from the map instead, it would compare the map
against itself and pass unconditionally — and "a whole population silently
vanished from the map" is the single most valuable thing it catches. The
artefacts are still paired through the map (`targetCanonical` names the value
set), so checks 2-4 read only what was written.

Checks
------
1. Coverage. Every code in each bound MIMIC population is either mapped by the
   ConceptMap, recorded in it as `unmatched`, or listed in unmapped-<field>.csv.
   Nothing may be silently absent from all three. The map and the CSV must also
   agree about what is unmapped, or one of them is stale.

2. ValueSet == ConceptMap target side. The value set is the map's
   targetCanonical, so "member of the value set" and "reachable by $translate"
   must be the same set. A drift here means the two were built from different
   inputs — which cannot now happen in one pass, so this is a regression guard.

3. Every (system, version) the artefacts reference is one we actually built.
   A shared terminology server can hold releases this repo has no source for;
   pinning a code into one produces an artefact that cannot be reproduced or
   redistributed. Caught here rather than at $expand time on someone else's
   server. Systems on UNVERSIONED_SYSTEMS may legitimately pin nothing.

4. No code maps to an ICD-10-PCS grouper. 64 of MIMIC's 2,544 ICD-9 procedure
   codes are verbatim valid 4-character PCS body-part groupers: procedure 0095
   means ICD-9 00.95, but as a raw string it matches PCS 0095 "Subarachnoid
   Space, Intracranial". Such a mapping would point a procedure at an anatomical
   structure AND make the unmapped report read zero. Keyed on the target system
   being ICD-10-PCS, so it guards any population that ever maps there.

Exits non-zero when any code is unmapped or any invariant fails.
--allow-unmapped downgrades the unmapped count to a warning once you have
reviewed the CSV; it does NOT relax checks 2-4, which are correctness bugs
rather than data gaps.

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
from conceptmaps.lib.builders import discover  # noqa: E402
from conceptmaps.lib.canonical import (ICD10_PCS, MIMIC_BASE,  # noqa: E402
                                       UNVERSIONED_SYSTEMS)
from conceptmaps.lib.igsource import source_concepts  # noqa: E402
from conceptmaps.lib.notation import concept_properties  # noqa: E402

# `discover` moved to conceptmaps/lib/builders.py, which is also where a table
# generator learns which populations a SHARED table has to cover. Two copies of
# the glob would be two answers to "which builders exist", and the one that
# drifted would be silent — see that module.


def load(path, what):
    if not path.is_file():
        sys.exit(f"missing {what}: {path} — run the builders first")
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


def mimic_codes(sources):
    """{(source system, code)} for every bound MIMIC population, read from the
    IG rather than from the map. See the module docstring."""
    return {(source["system"], code)
            for source in sources
            for code, _ in source_concepts(source)}


def check_field(field, sources, meta, out_dir, releases, groupers):
    print(f"\n== {field} ({meta['element']}) ==")
    failures, warnings = [], []

    conceptmap = load(out_dir / f"ConceptMap-{meta['id']}.json", "ConceptMap")
    # Paired through the artefact: the map names the value set it must agree
    # with, so the two cannot be matched up wrongly here.
    vs_id = conceptmap["targetCanonical"].rsplit("/", 1)[-1]
    valueset = load(out_dir / f"ValueSet-{vs_id}.json", "ValueSet")

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
    source = mimic_codes(sources)

    csv_path = out_dir / f"unmapped-{field}.csv"
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
    if declared_unmatched != listed:
        failures.append(
            f"the ConceptMap's `unmatched` entries and {csv_path.name} disagree: "
            f"{len(declared_unmatched - listed)} only in the map, "
            f"{len(listed - declared_unmatched)} only in the CSV")
    if listed:
        warnings.append(f"{len(listed)} unmapped code(s) in {csv_path.name}")

    # 2. ValueSet == ConceptMap target side. Both sides read the version with
    # .get so an unversioned group and an unversioned include compare equal
    # rather than raising — see check 3 for which systems may be unversioned.
    cm_targets = {(g["target"], g.get("targetVersion"), t["code"])
                  for g in conceptmap["group"] if g.get("target")
                  for e in g["element"] for t in e.get("target", [])
                  if t.get("code")}
    vs_members = {(i["system"], i.get("version"), c["code"])
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

    # 3. only releases we built. Two kinds of entry legitimately pin no
    # release: unmatched groups (the code is in none of them, so no single
    # version is the right one to name) and mappings into a system this repo
    # builds no CodeSystem for. Only the second kind may appear in the value
    # set, and only for a system on the UNVERSIONED_SYSTEMS list — anything
    # else unversioned is a build bug that would otherwise slip through by
    # being skipped rather than checked.
    referenced = {(g["target"], g["targetVersion"])
                  for g in conceptmap["group"] if g.get("targetVersion")}
    referenced |= {(i["system"], i["version"])
                   for i in valueset["compose"]["include"] if i.get("version")}
    unbuilt = referenced - releases
    if unbuilt:
        failures.append(f"references release(s) this repo did not build: "
                        f"{sorted(unbuilt)}")
    else:
        print(f"  releases        {len(referenced)} referenced, all built here")

    unversioned = {g["target"] for g in conceptmap["group"]
                   if g.get("target") and not g.get("targetVersion")
                   and any(t.get("code") for e in g["element"]
                           for t in e.get("target", []))}
    unversioned |= {i["system"] for i in valueset["compose"]["include"]
                    if not i.get("version")}
    rogue = unversioned - UNVERSIONED_SYSTEMS
    if rogue:
        failures.append(f"mapping(s) into {sorted(rogue)} pin no release, but "
                        f"only {sorted(UNVERSIONED_SYSTEMS)} may go unversioned")
    elif unversioned:
        print(f"  unversioned     {sorted(unversioned)} — built elsewhere, "
              f"declared")

    # 4. the PCS grouper collision. Keyed on the target system, so it guards
    # any population that ever maps into ICD-10-PCS, not just this one.
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
    elif any(g.get("target") == ICD10_PCS for g in conceptmap["group"]):
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

    populations = discover()
    releases = built_releases(args.out_dir)
    groupers = pcs_groupers(args.out_dir)
    print(f"populations:    {', '.join(f for f, _, _ in populations)}")
    print(f"built releases: {len(releases)}  "
          f"({', '.join(sorted(f'{u.rsplit('/', 1)[-1]}|{v}' for u, v in releases))})")
    print(f"PCS non-leaf concepts (collision set): {len(groupers):,}")

    failed, unmapped_total = False, 0
    for field, sources, meta in populations:
        failures, unmapped = check_field(
            field, sources, meta, args.out_dir, releases, groupers)
        unmapped_total += unmapped
        failed |= bool(failures)

    if failed:
        sys.exit("\nFAILED: see the checks above. These are correctness "
                 "problems, not data gaps — --allow-unmapped will not bypass them.")
    if unmapped_total and not args.allow_unmapped:
        sys.exit(f"\nREFUSING to pass: {unmapped_total} unmapped code(s). Review "
                 f"the unmapped-*.csv files and the <field>-report.json files, "
                 f"then re-run with --allow-unmapped to publish anyway.")
    print("\nOK" + (f" ({unmapped_total} unmapped, explicitly allowed)"
                    if unmapped_total else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
