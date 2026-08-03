#!/usr/bin/env python3
"""Build the enumerated target ValueSets from the ConceptMaps (stage 4).

The flow, for each bound field:

    for every code in the MIMIC ValueSet:
        translate it through the ConceptMap
        hit  -> write (system, version, code, display) into the new ValueSet
        miss -> write a row into unmapped-<field>.csv

Because the value set is the ConceptMap's `targetCanonical`, deriving it from
that map's target side makes "member of the value set" and "reachable by
$translate" the same set by construction. There is no second source of truth,
and no mapping rule is applied here — the rules live only in
../conceptmaps/build_conceptmap.py, and this script consumes their output.

This REPLACES the stage-2 scaffold at the same canonical URL: the scaffold
admits every code in the built ICD releases, this admits exactly the codes MIMIC
uses, written as official dotted codes and pinned to a release.

Why the version comes from the ConceptMap, not from $translate
--------------------------------------------------------------
Ontoserver (6.27.3) does NOT echo `group.targetVersion` into the `match.concept`
Coding returned by ConceptMap/$translate. Translation gives the right system,
code and display, but the release is dropped — and a value set needs the
release, because `compose.include` is per (system, version) and 43 diagnosis
codes exist only in the icd-10-cm 2024 release. So the map is fetched once and
indexed by (source system, source code); $translate then supplies the code and
display, and the index restores the version.

The index is keyed per CODE, not per (source, target) pair: one source system
maps into several releases of the same target system (mimic-diagnosis-icd10
alone spans icd-10-cm 2016, 2017, 2018, 2019 and 2024), so the pair is not
unique and would pick an arbitrary release.

Modes
-----
Default calls ConceptMap/$translate once per code, which exercises the deployed
map and proves the server serves what the file claims. --offline skips the
server and projects straight from the local ConceptMap, giving identical output
in seconds; use it while iterating on the unmapped list.

Usage:
  uv run scripts/terminology-mapping/valuesets/build_final_valueset.py --offline --no-upload
  uv run scripts/terminology-mapping/valuesets/build_final_valueset.py --insecure
"""

import argparse
import csv
import datetime
import json
import sys
import urllib.parse
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.cli import add_common_args, resolve  # noqa: E402
from common.fhirclient import http, upload  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "conceptmaps"))
from build_conceptmap import (  # noqa: E402
    CANONICAL_BASE, FIELDS, RESOURCES, VERSION, default_date,
)


# --------------------------------------------------------------------------- #
# The ConceptMap, as an index
# --------------------------------------------------------------------------- #

def fetch_conceptmap(field, out_dir, fhir_base, offline):
    """The map, from the server when online.

    _summary=false matters: a plain ConceptMap search returns a SUBSETTED
    resource with no `group` at all, which would silently index to nothing.
    """
    if offline or not fhir_base:
        path = out_dir / f"ConceptMap-{field['id']}.json"
        if not path.is_file():
            sys.exit(f"{path} not found — run the conceptmaps stage first")
        print(f"  reading {path.name} (offline)")
        return json.loads(path.read_text())
    url = f"{fhir_base.rstrip('/')}/ConceptMap/{field['id']}?_summary=false"
    print(f"  GET {url}")
    status, resource = http("GET", url)
    if status != 200 or not resource or resource.get("resourceType") != "ConceptMap":
        sys.exit(f"  could not fetch ConceptMap/{field['id']}: HTTP {status}. "
                 "Upload it first, or pass --offline.")
    if not resource.get("group"):
        sys.exit("  fetched ConceptMap has no groups — the server returned a "
                 "SUBSETTED resource. This script needs _summary=false.")
    return resource


def index_map(conceptmap):
    """(source system, source code) -> (target system, version, code, display).

    Skips `unmatched` targets: they carry no code — only the system that was
    searched — and exist to record that a source code was considered and
    deliberately not mapped. Including them would put a codeless entry in the
    value set. The codeless check below is what excludes them; their group
    does name a target system, so the group-level check cannot.
    """
    index = {}
    for group in conceptmap["group"]:
        if not group.get("target"):
            continue
        for element in group["element"]:
            for concept in element.get("target", []):
                if not concept.get("code"):
                    continue
                index[(group["source"], element["code"])] = (
                    group["target"], group["targetVersion"],
                    concept["code"], concept.get("display", ""))
    return index


def translate(fhir_base, conceptmap_url, system, code):
    """ConceptMap/$translate -> (target system, code, display) or None.

    The returned Coding carries no version; the caller restores it from the
    map's group. See the module docstring.
    """
    query = urllib.parse.urlencode(
        {"url": conceptmap_url, "system": system, "code": code})
    status, body = http("GET", f"{fhir_base.rstrip('/')}/ConceptMap/$translate?{query}")
    if status != 200 or not body or body.get("resourceType") != "Parameters":
        return None
    result, match = False, None
    for parameter in body.get("parameter", []):
        if parameter["name"] == "result":
            result = bool(parameter.get("valueBoolean"))
        elif parameter["name"] == "match":
            for part in parameter.get("part", []):
                if part["name"] == "concept":
                    coding = part.get("valueCoding", {})
                    match = (coding.get("system"), coding.get("code"),
                             coding.get("display", ""))
    return match if result else None


# --------------------------------------------------------------------------- #
# Build
# --------------------------------------------------------------------------- #

def source_codes(field):
    """Every code in the bound MIMIC ValueSet, as (source system, code, display).

    The bound value sets are bare composes over the two MIMIC CodeSystems, so
    their membership is exactly those CodeSystems' concepts — no $expand needed.
    """
    for source in field["sources"]:
        path = RESOURCES / source["file"]
        if not path.is_file():
            print(f"  {source['file']}: MISSING from input/resources/ — skipped")
            continue
        cs = json.loads(path.read_text())
        for concept in cs.get("concept", []):
            yield source["system"], concept["code"], concept.get("display", "")


def build(field, field_key, out_dir, fhir_base, offline, date, version):
    conceptmap = fetch_conceptmap(field, out_dir, fhir_base, offline)
    index = index_map(conceptmap)
    print(f"  indexed {len(index):,} mappings from "
          f"{len(conceptmap['group'])} group(s)")

    online = not offline and fhir_base
    buckets = defaultdict(dict)   # (system, version) -> {code: display}
    unmapped, mismatches, total = [], [], 0

    for system, code, mimic_display in source_codes(field):
        total += 1
        entry = index.get((system, code))
        if entry is None:
            unmapped.append({
                "field": field["element"], "source_system": system,
                "mimic_code": code, "mimic_display": mimic_display,
                "reason": "no-mapping-in-conceptmap",
            })
            continue
        target_system, target_version, target_code, target_display = entry

        if online:
            got = translate(fhir_base, conceptmap["url"], system, code)
            if got is None:
                unmapped.append({
                    "field": field["element"], "source_system": system,
                    "mimic_code": code, "mimic_display": mimic_display,
                    "reason": "translate-returned-no-match",
                })
                continue
            if (got[0], got[1]) != (target_system, target_code):
                mismatches.append((system, code, entry[:3], got))
                continue
            target_display = got[2] or target_display

        buckets[(target_system, target_version)][target_code] = target_display

    if mismatches:
        print(f"\n  {len(mismatches)} code(s) where the deployed map disagrees "
              f"with the local file, e.g.:")
        for system, code, expected, got in mismatches[:5]:
            print(f"    {code}: file says {expected[2]} ({expected[0]}), "
                  f"server says {got[1]} ({got[0]})")
        sys.exit("  refusing to build from a map that does not match the file")

    includes = []
    for system, release in sorted(buckets):
        concepts = buckets[(system, release)]
        includes.append({
            "system": system,
            "version": release,
            "concept": [{"code": c, "display": d} if d else {"code": c}
                        for c, d in sorted(concepts.items())],
        })

    valueset_url = field["target_valueset"]
    resource = {
        "resourceType": "ValueSet",
        "id": valueset_url.rsplit("/", 1)[-1],
        "url": valueset_url,
        "version": version,
        "name": "".join(p.capitalize()
                        for p in valueset_url.rsplit("/", 1)[-1].split("-")),
        "title": f"MIMIC {field_key} codes as standard ICD",
        "status": "active",
        "experimental": False,
        "date": date,
        "publisher": "CSIRO",
        "description":
            f"Every code MIMIC-IV uses in {field['element']}, written as "
            "official dotted ICD codes and pinned to the earliest release "
            f"containing it. Derived from ConceptMap/{field['id']}, whose "
            "targetCanonical this is, so membership here and reachability by "
            "$translate are the same set. Displays are the official ICD "
            "descriptions, not MIMIC's abbreviated text, so $validate-code "
            "never reports a display mismatch.",
        "compose": {"include": includes},
    }
    return resource, unmapped, total


def write_unmapped(field_key, unmapped, out_dir):
    path = out_dir / f"unmapped-{field_key}.csv"
    columns = ["field", "source_system", "mimic_code", "mimic_display", "reason"]
    with open(path, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns)
        writer.writeheader()
        writer.writerows(unmapped)
    return path


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("fields", nargs="*", choices=sorted(FIELDS) + [[]],
                    default=sorted(FIELDS), help="which value sets (default: all)")
    ap.add_argument("--offline", action="store_true",
                    help="project from the local ConceptMap instead of calling "
                         "$translate; identical output, no server needed")
    ap.add_argument("--version", default=VERSION)
    ap.add_argument("--date")
    add_common_args(ap)
    args = ap.parse_args()
    do_upload = resolve(args)

    date = args.date or default_date(args.out_dir)

    any_unmapped = False
    for key in args.fields:
        field = FIELDS[key]
        print(f"\n== {key} ({field['element']}) ==")
        resource, unmapped, total = build(
            field, key, args.out_dir, args.fhir_base, args.offline,
            date, args.version)

        path = args.out_dir / f"ValueSet-{resource['id']}.json"
        path.write_text(json.dumps(resource, indent=1) + "\n")
        distinct = sum(len(i["concept"]) for i in resource["compose"]["include"])
        print(f"\n  wrote {path.name} ({path.stat().st_size / 1e6:.1f} MB)")
        print(f"  {total - len(unmapped):,}/{total:,} MIMIC codes translated "
              f"-> {distinct:,} distinct target codes")
        for inc in resource["compose"]["include"]:
            print(f"    {inc['system']} | {inc['version']}   "
                  f"{len(inc['concept']):,} codes")

        csv_path = write_unmapped(key, unmapped, args.out_dir)
        if unmapped:
            any_unmapped = True
            print(f"  UNMAPPED: {len(unmapped)} -> {csv_path.name}")
        else:
            print(f"  unmapped: none ({csv_path.name} is empty)")

        if do_upload:
            upload(resource, args.fhir_base)

    if any_unmapped:
        print("\nSome codes are unmapped. `make upload-mappings` will refuse to "
              "publish until they are resolved or explicitly overridden.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
