#!/usr/bin/env python3
"""Build the scaffold target ValueSets (stage 2).

These exist to break a circular dependency. The ConceptMap needs a
`targetCanonical` to point at, and the real target ValueSet is derived FROM the
ConceptMap in stage 4 — so at stage 3 the thing the map points at does not
exist yet. The scaffold is that URL's first tenant: a deliberately over-broad
"every code in the ICD releases we built" value set, ~1 KB, replaced in stage 4
by the enumerated version holding exactly the codes MIMIC uses.

Deliberately NOT enumerated. A 1:1 enumeration of the built CodeSystems is
~700,000 concepts and tens of megabytes; a bare `compose.include` of
{system, version} means the same thing in a few hundred bytes. Nothing should
expand this — it is scaffolding, and stage 4 overwrites it at the same
canonical URL.

ICD-9-CM carries a `kind` filter because THO assigns diagnoses (Vol 1-2) and
procedures (Vol 3) the same canonical URL; without it the diagnosis scaffold
would claim every procedure code and vice versa.

Usage:
  uv run scripts/terminology-mapping/valuesets/build_scaffold_valueset.py --no-upload
  uv run scripts/terminology-mapping/valuesets/build_scaffold_valueset.py
"""

import argparse
import datetime
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common import paths  # noqa: E402
from common.cli import add_common_args, resolve  # noqa: E402
from common.fhirclient import upload  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "conceptmaps"))
from build_conceptmap import (  # noqa: E402
    CANONICAL_BASE, FIELDS, ICD9_CM, MIMIC_BASE, VERSION, default_date,
    load_built,
)

# Which target systems each field draws on, and the kind filter needed when a
# system serves both fields. Mirrors the target tables in build_conceptmap.py.
SCOPE = {
    "diagnosis": {"kind": "diagnosis"},
    "procedure": {"kind": "procedure"},
}


def build_scaffold(field_key, field, built, date, version):
    kind = SCOPE[field_key]["kind"]
    systems = sorted({t["system"] for s in field["sources"] for t in s["targets"]})

    includes = []
    for system in systems:
        for release in sorted(v for (url, v) in built if url == system):
            include = {"system": system, "version": release}
            if system == ICD9_CM:
                include["filter"] = [
                    {"property": "kind", "op": "=", "value": kind}]
            includes.append(include)

    valueset_url = field["target_valueset"]
    return {
        "resourceType": "ValueSet",
        "id": valueset_url.rsplit("/", 1)[-1],
        "url": valueset_url,
        "version": version,
        "name": "".join(p.capitalize() for p in
                        valueset_url.rsplit("/", 1)[-1].split("-")),
        "title": f"MIMIC {field_key} codes as standard ICD (scaffold)",
        "status": "draft",
        "experimental": True,
        "date": date,
        "publisher": "CSIRO",
        "description":
            "SCAFFOLD ONLY. Placeholder for the targetCanonical of "
            f"ConceptMap/{field['id']}, admitting every code in the built ICD "
            "releases rather than only the codes MIMIC uses. Replaced at the "
            "same canonical URL by the enumerated value set that stage 4 "
            "derives from that ConceptMap. Do not expand this.",
        "compose": {"include": includes},
    }


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("fields", nargs="*", choices=sorted(FIELDS) + [[]],
                    default=sorted(FIELDS), help="which scaffolds (default: all)")
    ap.add_argument("--version", default=VERSION)
    ap.add_argument("--date")
    add_common_args(ap)
    args = ap.parse_args()
    do_upload = resolve(args)

    date = args.date or default_date(args.out_dir)
    built = load_built(args.out_dir)

    for key in args.fields:
        field = FIELDS[key]
        resource = build_scaffold(key, field, built, date, args.version)
        path = args.out_dir / f"ValueSet-{resource['id']}-scaffold.json"
        path.write_text(json.dumps(resource, indent=1) + "\n")
        print(f"  wrote {path.name}: {resource['url']} "
              f"({len(resource['compose']['include'])} include blocks, "
              f"{path.stat().st_size} bytes)")
        for inc in resource["compose"]["include"]:
            flt = inc.get("filter")
            print(f"    {inc['system']} | {inc['version']}"
                  + (f"  filter kind = {flt[0]['value']}" if flt else ""))
        if do_upload:
            upload(resource, args.fhir_base)
    return 0


if __name__ == "__main__":
    sys.exit(main())
