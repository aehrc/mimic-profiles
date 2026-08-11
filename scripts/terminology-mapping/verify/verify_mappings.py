#!/usr/bin/env python3
"""Verify the generated ConceptMap / ValueSet pairs and the stream artefacts.

This is what you read before deciding to publish. It re-derives NO mapping: no
dot rules, no code conversion, no "is this code in that release" logic. Those
live once, in conceptmaps/lib/. This reads the generated artefacts and checks
properties of them.

Discovery, not a registry
-------------------------
The maps are found by globbing `conceptmaps/build_*_cm_vs.py` and reading each
module's FIELD / SOURCES / META; the streams come from lib/streams.py, the one
place they are declared. Adding a map or a stream needs no edit here.

Checks
------
1. Stream coverage. Every code in each stream's enumeration is either mapped by
   every consuming ConceptMap or listed in unmapped-<stream>.csv — and the
   map's `unmatched` entries and the CSV must agree, or one of them is stale.

2. ValueSet == ConceptMap target side. The value set is the map's
   targetCanonical, so "member of the value set" and "reachable by $translate"
   must be the same set.

3. Every (system, version) the artefacts reference is one we actually built.
   Systems on UNVERSIONED_SYSTEMS may legitimately pin nothing.

4. No code maps to an ICD-10-PCS grouper. 64 of MIMIC's 2,544 ICD-9 procedure
   codes are verbatim valid 4-character PCS body-part groupers; such a mapping
   would point a procedure at an anatomical structure AND make the unmapped
   report read zero.

5. Completeness against the BINDING. Every code the element's bound ValueSet
   admits has an entry in the ConceptMap — mapped or `unmatched`. Check 1
   cannot catch a population the builder never declared; this reads the
   binding's own code list from occurrences/elements.json instead.

6. (folded into 5's warning) The FSH-authored facade ValueSets must be
   readable, i.e. `sushi .` must have run; said out loud instead of passing
   silently.

7. Stream <-> map agreement. Every ConceptMap consuming a stream carries the
   IDENTICAL answers for that stream's codes — same target system, same target
   code. A stream resolves once (lib/assemble.py); two maps disagreeing means
   an artefact is stale, which is exactly what a partial rebuild can produce.

8. Partition disjointness. Streams sharing a source system must not overlap:
   an overlapping code would belong to two streams, be counted twice in every
   statistic, and could be published with two different targets.

9. Partition COVERAGE — the other half of 8. Every code any binding admits must
   belong to some stream. Disjointness stops the registry double-counting;
   nothing stopped it under-counting by simply not mentioning a population, and
   that failure is silent where an overlap is not: a stream that does not exist
   writes no row, no worklist and no warning. Check 5 catches this per MAP, so
   it is blind to an element with no builder at all — which is exactly where
   both undeclared populations were found. Counted as unmapped codes rather
   than a FAIL: an undeclared population is a data gap of the same kind the
   worklists record, not a defect in what was built.

Exits non-zero when any code is unmapped or any invariant fails.
--allow-unmapped downgrades the unmapped count to a warning once you have
reviewed the CSVs; it does NOT relax the correctness checks.

Usage:
  uv run scripts/terminology-mapping/verify/verify_mappings.py
  uv run scripts/terminology-mapping/verify/verify_mappings.py --allow-unmapped
"""

import argparse
import csv
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common import occurrences, paths  # noqa: E402
from conceptmaps.lib import streams  # noqa: E402
from conceptmaps.lib.builders import discover  # noqa: E402
from conceptmaps.lib.canonical import (ICD10_PCS, MIMIC_BASE,  # noqa: E402
                                       UNVERSIONED_SYSTEMS)
from conceptmaps.lib.igsource import source_concepts  # noqa: E402
from conceptmaps.lib.notation import concept_properties  # noqa: E402


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


def bound_codes(element):
    """{(system, code)} the element's BINDING admits, from occurrences/elements.json.

    Deliberately NOT derived from SOURCES: comparing the map against its own
    declaration can only catch a declared population going missing — it is
    blind to a population the builder never declared at all, which is the
    failure check 5 exists for.

    Returns None when the element is not in the registry or a bound ValueSet
    could not be read (usually `sushi .` has not run); check 5 then says so
    instead of passing silently.
    """
    entry = occurrences.registry().get(element)
    if entry is None:
        return None
    index = occurrences._resource_index()  # noqa: SLF001
    admitted = {}
    for url in entry.get("bound_valuesets", []):
        admitted.update(occurrences.expand(url, index))
    if entry.get("bound_valuesets") and not admitted:
        return None
    return set(admitted)


def cm_entries(conceptmap):
    """(mapped, declared_unmatched) over one map.

    mapped: {(source system, code): (target system, target code)}. A source
    code is MAPPED only if it has a target with a code; an `unmatched` target
    records "considered, deliberately not mapped" and carries no code.
    """
    mapped, unmatched = {}, set()
    for group in conceptmap["group"]:
        for element in group["element"]:
            entry = (group["source"], element["code"])
            coded = [t for t in element.get("target", []) if t.get("code")]
            if coded:
                mapped[entry] = (group["target"], coded[0]["code"])
            else:
                unmatched.add(entry)
    return mapped, unmatched


def check_map(field, meta, out_dir, releases, groupers, conceptmap):
    """Checks 2-5 for one ConceptMap / ValueSet pair."""
    print(f"\n== {field} ({meta['element']}) ==")
    failures, warnings = [], []

    vs_id = conceptmap["targetCanonical"].rsplit("/", 1)[-1]
    valueset = load(out_dir / f"ValueSet-{vs_id}.json", "ValueSet")
    mapped, declared_unmatched = cm_entries(conceptmap)

    # 2. ValueSet == ConceptMap target side. Both sides read the version with
    # .get so an unversioned group and an unversioned include compare equal.
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

    # 3. only releases we built; only declared systems unversioned.
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

    # 4. the PCS grouper collision.
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

    # 5. Every code the BINDING admits has an entry in the map. Under a
    # REQUIRED binding a conformant instance may carry any admitted code, so
    # any code without an entry is a consumer holding valid data this map
    # cannot answer for — not `unmatched`, nothing, indistinguishable from a
    # map that failed to load.
    admitted = bound_codes(meta["element"])
    if admitted is None:
        warnings.append(
            f"completeness NOT CHECKED for {meta['element']}: its binding's own "
            f"code list could not be enumerated. Either the element is missing "
            f"from occurrences/elements.json, or a bound ValueSet could not be "
            f"read — most of them are FSH-authored, so run `sushi .` first")
    else:
        in_map = set(mapped) | declared_unmatched
        absent = admitted - in_map
        if absent:
            by_system = Counter(system for system, _ in absent)
            failures.append(
                f"{len(absent):,} code(s) the binding admits have NO entry in "
                f"the ConceptMap, so $translate returns nothing for them rather "
                f"than a declared non-answer: "
                + ", ".join(f"{n:,} from {url.rsplit('/', 1)[-1]}"
                            for url, n in by_system.most_common()))
        else:
            print(f"  completeness    {len(admitted):,} bound code(s), every one "
                  f"has an entry")
        # The other direction is NOT a failure: a map may legitimately answer
        # for a code outside the current binding. Reported, never fatal.
        extra = in_map - admitted
        if extra:
            print(f"  {len(extra):,} entr(ies) outside the current binding "
                  f"(answered anyway, not a failure)")

    for warning in warnings:
        print(f"  WARN  {warning}")
    for failure in failures:
        print(f"  FAIL  {failure}")
    return failures


def check_stream(name, consuming, cms, out_dir, counts_present):
    """Checks 1 and 7 for one stream, against every consuming map."""
    source = streams.get(name)
    enumeration = {(source["system"], code)
                   for code, _ in source_concepts(source)}

    csv_path = out_dir / f"unmapped-{name}.csv"
    listed, reasons = set(), Counter()
    if csv_path.is_file():
        with open(csv_path) as fh:
            for r in csv.DictReader(fh):
                listed.add((r["source_system"], r["mimic_code"]))
                reasons[r["reason"]] += 1

    failures = []
    per_map = {}
    for field in consuming:
        mapped, unmatched = cms[field]
        mine_mapped = {k: v for k, v in mapped.items() if k in enumeration}
        mine_unmatched = unmatched & enumeration
        per_map[field] = mine_mapped
        # 1. coverage: nothing silently absent from both the map and the CSV,
        # and the map's unmatched set == the committed worklist.
        missing = enumeration - set(mine_mapped) - mine_unmatched
        if missing:
            failures.append(f"{field}: {len(missing)} code(s) neither mapped "
                            f"nor declared unmatched, e.g. {sorted(missing)[:3]}")
        if mine_unmatched != listed:
            failures.append(
                f"{field}: the map's `unmatched` entries and {csv_path.name} "
                f"disagree — {len(mine_unmatched - listed)} only in the map, "
                f"{len(listed - mine_unmatched)} only in the CSV. One of them "
                f"is stale; rebuild (`make mappings`).")

    # 7. every consuming map carries the identical answers.
    if len(per_map) > 1:
        canonical = None
        for field, mine in sorted(per_map.items()):
            if canonical is None:
                canonical = (field, mine)
            elif mine != canonical[1]:
                diff = {k for k in set(mine) | set(canonical[1])
                        if mine.get(k) != canonical[1].get(k)}
                failures.append(
                    f"{field} and {canonical[0]} disagree on {len(diff)} "
                    f"answer(s) for this stream, e.g. {sorted(diff)[:3]} — a "
                    f"stream resolves once, so one artefact is stale")

    unmapped_total = len(listed)
    consumers_note = ",".join(consuming)
    print(f"  {name:28s} {len(enumeration) - unmapped_total:>6,}/"
          f"{len(enumeration):<6,} mapped  {unmapped_total:>6,} listed   "
          f"[{consumers_note}]")
    if not counts_present and "not-observed-in-data" in reasons:
        print(f"    WARN  {reasons['not-observed-in-data']} row(s) claim "
              f"not-observed-in-data, but the occurrence counts are absent so "
              f"that reason cannot be re-verified here")
    for failure in failures:
        print(f"    FAIL  {failure}")
    return failures, unmapped_total


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
    print(f"maps:           {', '.join(f for f, _, _ in populations)}")
    print(f"streams:        {len(streams.STREAMS)}")
    print(f"built releases: {len(releases)}  "
          f"({', '.join(sorted(f'{u.rsplit('/', 1)[-1]}|{v}' for u, v in releases))})")
    print(f"PCS non-leaf concepts (collision set): {len(groupers):,}")

    failed = False

    # 8. partition disjointness — before anything reads a stream, because an
    # overlap makes every per-stream number ambiguous.
    for failure in streams.check_disjoint():
        print(f"FAIL  {failure}")
        failed = True

    # Load every map once; the per-stream checks reuse them.
    cms, metas = {}, {}
    for field, _, meta in populations:
        conceptmap = load(args.out_dir / f"ConceptMap-{meta['id']}.json",
                          "ConceptMap")
        cms[field] = cm_entries(conceptmap)
        metas[field] = (meta, conceptmap)

    # Checks 2-5, per map.
    for field, _, meta in populations:
        failures = check_map(field, meta, args.out_dir, releases, groupers,
                             metas[field][1])
        failed |= bool(failures)

    # Checks 1 and 7, per stream.
    consuming = {}
    for field, sources, _ in populations:
        for source in sources:
            consuming.setdefault(source["stream"], []).append(field)
    counts_present = occurrences.load() is not None
    print(f"\n== streams ==")
    unmapped_total = 0
    for name in sorted(streams.STREAMS):
        failures, unmapped = check_stream(
            name, consuming.get(name, []), cms, args.out_dir, counts_present)
        unmapped_total += unmapped
        failed |= bool(failures)

    # 9. partition coverage. Every code the bindings admit belongs to a stream.
    undeclared = streams.undeclared()
    if undeclared:
        print("\n== undeclared populations ==")
        for pop in undeclared:
            unmapped_total += len(pop["concepts"])
            print(f"  {pop['stream']:28s} {0:>6,}/"
                  f"{len(pop['concepts']):<6,} mapped  "
                  f"{len(pop['concepts']):>6,} listed   "
                  f"[bound on {', '.join(pop['bound_on'])}]")
            print(f"    WARN  no stream declares {pop['system']} — "
                  f"build_stream_reports.py carries it as a 0% row and wrote "
                  f"unmapped-{pop['stream']}.csv; declare it in "
                  f"lib/streams.py to make it real")
    else:
        print("\ncoverage:       every bound code belongs to a declared stream")

    if failed:
        sys.exit("\nFAILED: see the checks above. These are correctness "
                 "problems, not data gaps — --allow-unmapped will not bypass them.")
    if unmapped_total and not args.allow_unmapped:
        sys.exit(f"\nREFUSING to pass: {unmapped_total} unmapped code(s). Review "
                 f"the unmapped-<stream>.csv files and output/stream-report.json, "
                 f"then re-run with --allow-unmapped to publish anyway.")
    print("\nOK" + (f" ({unmapped_total} unmapped, explicitly allowed)"
                    if unmapped_total else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
