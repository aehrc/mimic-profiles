#!/usr/bin/env python3
"""Convert CMS ICD-10-PCS release files into FHIR R4 CodeSystem resources and
upload them to an Ontoserver instance.

Inputs per release year (in a folder named after the year, e.g. ./2018/):
  - icd10pcs_order_<year>.txt   (required)  CMS order file, same fixed-width
    layout as the ICD-10-CM one: every valid 7-character code (flag 1) plus
    the 873 three-character table headers (flag 0), with short + long
    descriptions. This is the spine: code list, header/leaf split, displays.
  - icd10pcs_tables_<year>.xml  (optional)  the PCS tables. Supplies the axis
    labels used as displays for the intermediate tiers (section, body system,
    body part) and the formal root-operation definitions.
  - icd10pcs_index_<year>.xml   (optional)  the alphabetic index. Supplies
    designations: the clinical vernacular ("Abdominohysterectomy") that does
    not appear anywhere in the generated displays.

PCS is NOT like ICD-10-CM. Codes are exactly seven characters, every valid
code is billable, and there are no dotted category codes - so there is no
`billable` property here (it would be true for every concept that exists) and
no dot insertion. What PCS has instead is a positional hierarchy, which is
what this script builds:

    0        Medical and Surgical                    (section,     char 1)
    00       Central Nervous System and Cranial ...  (body system, char 2)
    001      ... and Cranial Nerves, Bypass          (CMS header,  char 3)
    0016     Cerebral Ventricle                      (body part,   char 4)
    0016070  Bypass Cerebral Ventricle to Nasoph...  (valid code,  char 7)

Only the 7-character leaves are real codes. Every shorter concept carries the
standard `notSelectable` property so it can be navigated but never returned;
ValueSets built off this CodeSystem must contain leaves only.

The 3-character tier is CMS's own (it is exactly the flag-0 rows in the order
file, one per pcsTable). The 1-, 2- and 4-character tiers are derived here
from the tables XML - CMS does not publish them as codes.

Index designations attach where the index points, which is overwhelmingly the
4-character body-part tier (11,439 of 11,878 references). Because consumers
typically expand a ValueSet holding only leaves, those designations are also
propagated down to the leaf descendants unless --no-propagate is given.
The index's ~2,000 bare synonym redirects ("Abdominal aortic plexus -> use
Abdominal Sympathetic Nerve") are applied only where the target names a
body-part label, which is the tier the rest of the index already targets.

Output: output/CodeSystem-icd-10-pcs-<year>.json, then PUT to
<fhir-base>/CodeSystem/icd-10-pcs-<year> followed by $lookup smoke tests.

Canonical url http://www.cms.gov/Medicare/Coding/ICD10 and OID
2.16.840.1.113883.6.4 per terminology.hl7.org's icd10PCS entry; note PCS is
NOT under hl7.org/fhir/sid/ the way ICD-10-CM and ICD-9-CM are.

Usage (run via uv from the repo root):
  uv run scripts/terminology-mapping/terminology/icd10pcs/build_icd10pcs_codesystem.py 2018
  uv run .../build_icd10pcs_codesystem.py 2018 --no-upload
  uv run .../build_icd10pcs_codesystem.py 2018 --no-propagate
"""

import argparse
import json
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from common import paths  # noqa: E402
from common.cli import add_common_args, resolve  # noqa: E402
from common.fhirclient import upload_and_verify  # noqa: E402

SYSTEM_URI = "http://www.cms.gov/Medicare/Coding/ICD10"
OID = "urn:oid:2.16.840.1.113883.6.4"
SYNONYM_USE = {
    "system": "http://snomed.info/sct",
    "code": "900000000000013009",
    "display": "Synonym",
}


# --------------------------------------------------------------------------
# order file: the spine
# --------------------------------------------------------------------------

def parse_order_file(path: Path):
    """Parse the fixed-width CMS order file.

    Layout (1-based columns): 1-5 order number, 7-13 code, 15 valid flag
    (0 = table header, 1 = valid code), 17-76 short description,
    78-end long description.

    Returns (leaves, headers), each a dict code -> {"display", "short"}.
    """
    leaves, headers = {}, {}
    with open(path, encoding="utf-8", errors="replace") as f:
        for lineno, line in enumerate(f, 1):
            if not line.strip():
                continue
            code = line[6:13].strip()
            flag = line[14]
            short = line[16:76].strip()
            long_ = line[77:].strip()
            if not code or flag not in "01":
                raise ValueError(f"{path}:{lineno}: unexpected line format: {line!r}")
            entry = {"display": long_ or short, "short": short}
            if flag == "1":
                if len(code) != 7:
                    raise ValueError(
                        f"{path}:{lineno}: valid code {code!r} is not 7 characters")
                leaves[code] = entry
            else:
                headers[code] = entry
    return leaves, headers


# --------------------------------------------------------------------------
# tables XML: tier displays and root-operation definitions
# --------------------------------------------------------------------------

def parse_tables(path: Path):
    """Collect the axis labels that name the derived tiers.

    Returns (displays, definitions, body_part_labels) where displays maps a
    1-, 2- or 4-character prefix to its axis label, definitions maps a
    3-character table code to the formal root-operation definition, and
    body_part_labels maps a body-part label back to the 4-character codes
    that carry it (used for the index's synonym redirects).
    """
    displays, definitions = {}, {}
    body_part_labels = defaultdict(set)
    for table in ET.parse(path).getroot().findall("pcsTable"):
        axes = {a.get("pos"): a for a in table.findall("axis")}
        try:
            sec = axes["1"].find("label")
            sys_ = axes["2"].find("label")
            op = axes["3"].find("label")
        except KeyError as exc:  # malformed table; surface rather than skip
            raise ValueError(f"{path}: table missing axis {exc}") from exc

        prefix1 = sec.get("code")
        prefix2 = prefix1 + sys_.get("code")
        prefix3 = prefix2 + op.get("code")
        displays.setdefault(prefix1, (sec.text or "").strip())
        displays.setdefault(prefix2, (sys_.text or "").strip())
        definition = axes["3"].findtext("definition")
        if definition and definition.strip():
            definitions.setdefault(prefix3, definition.strip())

        for row in table.findall("pcsRow"):
            axis4 = next((a for a in row.findall("axis") if a.get("pos") == "4"), None)
            if axis4 is None:
                continue
            for label in axis4.findall("label"):
                text = (label.text or "").strip()
                prefix4 = prefix3 + label.get("code")
                displays.setdefault(prefix4, text)
                if text:
                    body_part_labels[text].add(prefix4)
    return displays, definitions, body_part_labels


# --------------------------------------------------------------------------
# index XML: designations
# --------------------------------------------------------------------------

def parse_index(path: Path, body_part_labels):
    """Map code (4- or 7-character) -> set of index terms.

    The printed index reads as a path: a main term plus nested sub-terms, e.g.
    "Bypass, Artery, Coronary". That joined path is the searchable phrase, so
    it is what becomes the designation. <codes> holds a 4-character partial
    target, <code> a full 7-character one, and <use> redirects a synonym to
    another entry's label rather than to a code.
    """
    terms = defaultdict(set)
    redirects = 0

    def walk(node, trail):
        nonlocal redirects
        title = node.findtext("title")
        if title and title.strip():
            trail = trail + [title.strip()]
        phrase = ", ".join(trail)

        for tag in ("codes", "code"):
            for ref in node.findall(tag):
                target = (ref.text or "").strip()
                if target and phrase:
                    terms[target].add(phrase)
        # <see>Resection, Uterus<codes>0UT9</codes></see>: the cross-reference
        # text names the target entry, so the useful synonym is still our path.
        for see in node.findall("see"):
            for ref in list(see.findall("codes")) + list(see.findall("code")):
                target = (ref.text or "").strip()
                if target and phrase:
                    terms[target].add(phrase)
        # <use>Abdominal Sympathetic Nerve</use>: a label, not a code.
        for use in node.findall("use"):
            label = (use.text or "").strip()
            if not (label and phrase):
                continue
            for prefix4 in body_part_labels.get(label, ()):
                terms[prefix4].add(phrase)
                redirects += 1

        for child in node.findall("term"):
            walk(child, trail)

    for main in ET.parse(path).getroot().iter("mainTerm"):
        walk(main, [])
    return terms, redirects


# --------------------------------------------------------------------------
# assembly
# --------------------------------------------------------------------------

def build_codesystem(year, leaves, headers, displays, definitions,
                     index_terms, propagate):
    """Assemble the 1/2/3/4/7-character tree as CodeSystem.concept entries."""
    tiers = {1: set(), 2: set(), 4: set()}
    for code in leaves:
        for n in (1, 2, 4):
            tiers[n].add(code[:n])

    missing_headers = {c[:3] for c in leaves} - set(headers)
    if missing_headers:
        raise ValueError(
            f"{len(missing_headers)} 3-character tables referenced by codes are "
            f"absent from the order file: {sorted(missing_headers)[:10]}")

    concepts = []
    stats = defaultdict(int)

    def add(code, display, parent=None, definition=None, short=None,
            selectable=False, designations=()):
        entry = {"code": code, "display": display}
        if definition:
            entry["definition"] = definition
        desigs = []
        if short and short != display:
            desigs.append({"use": SYNONYM_USE, "value": short})
        desigs += [{"use": SYNONYM_USE, "value": v} for v in sorted(designations)]
        if desigs:
            entry["designation"] = desigs
            stats["designations"] += len(desigs)
        props = []
        if parent:
            props.append({"code": "parent", "valueCode": parent})
        if not selectable:
            props.append({"code": "notSelectable", "valueBoolean": True})
        if props:
            entry["property"] = props
        concepts.append(entry)
        stats[f"tier{len(code)}"] += 1

    for code in sorted(tiers[1]):
        add(code, displays.get(code) or f"Section {code}")
    for code in sorted(tiers[2]):
        add(code, displays.get(code) or f"Section {code[0]} body system {code[1]}",
            parent=code[0])
    for code in sorted(headers):
        add(code, headers[code]["display"], parent=code[:2],
            definition=definitions.get(code), short=headers[code]["short"])
    for code in sorted(tiers[4]):
        add(code, displays.get(code) or f"{code[:3]} body part {code[3]}",
            parent=code[:3], designations=index_terms.get(code, ()))
    for code in sorted(leaves):
        inherited = set(index_terms.get(code, ()))
        if propagate:
            inherited |= index_terms.get(code[:4], set())
        add(code, leaves[code]["display"], parent=code[:4],
            short=leaves[code]["short"], selectable=True,
            designations=inherited)

    fy_start = f"{int(year) - 1}-10-01"
    return {
        "resourceType": "CodeSystem",
        "id": f"icd-10-pcs-{year}",
        "url": SYSTEM_URI,
        "identifier": [{"system": "urn:ietf:rfc:3986", "value": OID}],
        "version": year,
        "name": "ICD10PCS",
        "title": ("International Classification of Diseases, Tenth Revision, "
                  f"Procedure Coding System, FY{year}"),
        "status": "active",
        "experimental": False,
        "date": fy_start,
        "publisher": "Centers for Medicare & Medicaid Services (CMS)",
        "description": (
            f"ICD-10-PCS FY{year} release (effective {fy_start}), generated from "
            "the CMS order file, with the section/body-system/body-part tiers and "
            "root-operation definitions from the PCS tables and designations from "
            "the alphabetic index. Only the 7-character concepts are valid codes; "
            "shorter concepts are navigational and carry notSelectable."),
        "copyright": ("ICD-10-PCS is maintained by CMS as a work of the United "
                      "States government and is in the public domain."),
        "caseSensitive": True,
        "valueSet": f"{SYSTEM_URI}?fhir_vs",
        "hierarchyMeaning": "is-a",
        # Combinatorial, but the valid set is closed and enumerated here: only
        # the axis combinations published in the tables are codes, so this is
        # not a post-coordination grammar.
        "compositional": False,
        "versionNeeded": False,
        "content": "complete",
        "count": len(concepts),
        "property": [
            {
                "code": "parent",
                "uri": "http://hl7.org/fhir/concept-properties#parent",
                "description": "Parent concept (is-a)",
                "type": "code",
            },
            {
                "code": "notSelectable",
                "uri": "http://hl7.org/fhir/concept-properties#notSelectable",
                "description": "Navigational concept only (section, body system, "
                               "table or body part); not a valid ICD-10-PCS code.",
                "type": "boolean",
            },
        ],
        "concept": concepts,
    }, stats


def locate_inputs(year_dir: Path, year: str):
    def one(pattern, required):
        hits = sorted(year_dir.rglob(pattern))
        if not hits and required:
            raise FileNotFoundError(f"no {pattern} found in {year_dir}")
        return hits[0] if hits else None

    return (one(f"*order*{year}*.txt", True),
            one(f"*tables*{year}*.xml", False),
            one(f"*index*{year}*.xml", False))


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("years", nargs="+", help="release year folders, e.g. 2018")
    ap.add_argument("--base-dir", type=Path, default=paths.SOURCES / "icd10pcs",
                    help=f"directory containing the year folders "
                         f"(default: {paths.SOURCES / 'icd10pcs'})")
    ap.add_argument("--no-propagate", action="store_true",
                    help="keep index designations on the 4-character body-part "
                         "tier only, instead of also copying them to leaves")
    add_common_args(ap)
    args = ap.parse_args()
    do_upload = resolve(args)

    failures = []
    for year in args.years:
        print(f"== ICD-10-PCS FY{year} ==")
        order_file, tables_file, index_file = locate_inputs(
            args.base_dir / year, year)
        print(f"  order file: {order_file.name}")
        leaves, headers = parse_order_file(order_file)
        print(f"  codes: {len(leaves)} valid, {len(headers)} table headers")

        if tables_file:
            print(f"  tables:     {tables_file.name}")
            displays, definitions, body_part_labels = parse_tables(tables_file)
            print(f"  tiers named from tables: {len(displays)} labels, "
                  f"{len(definitions)} root-operation definitions")
        else:
            print("  tables:     none found; tiers get placeholder displays")
            displays, definitions, body_part_labels = {}, {}, {}

        if index_file:
            print(f"  index:      {index_file.name}")
            index_terms, redirects = parse_index(index_file, body_part_labels)
            print(f"  index terms: {sum(len(v) for v in index_terms.values())} "
                  f"across {len(index_terms)} targets "
                  f"({redirects} via synonym redirects)")
        else:
            print("  index:      none found; no designations")
            index_terms = {}

        cs, stats = build_codesystem(year, leaves, headers, displays,
                                     definitions, index_terms,
                                     propagate=not args.no_propagate)
        print(f"  concepts: {cs['count']} "
              f"({stats['tier1']} sections, {stats['tier2']} body systems, "
              f"{stats['tier3']} tables, {stats['tier4']} body parts, "
              f"{stats['tier7']} codes), {stats['designations']} designations")

        out = args.out_dir / f"CodeSystem-icd-10-pcs-{year}.json"
        payload = json.dumps(cs, indent=1)
        out.write_text(payload)
        print(f"  wrote {out} ({len(payload.encode()) / 1e6:.1f} MB)")

        if do_upload:
            probes = ["0016070", sorted(leaves)[0], sorted(headers)[0]]
            if not upload_and_verify(cs, args.fhir_base, SYSTEM_URI, year, probes):
                failures.append(year)

    if failures:
        sys.exit(f"FAILED years: {', '.join(failures)}")


if __name__ == "__main__":
    main()
