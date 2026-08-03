#!/usr/bin/env python3
"""Convert CMS ICD-10-CM release files into FHIR R4 CodeSystem resources and
upload them to an Ontoserver instance.

Inputs per release year (in a folder named after the year, e.g. ./2016/):
  - icd10cm_order_<year>.txt  (required)  CMS "Code Descriptions in Tabular
    Order" fixed-width file: every code incl. pre-expanded 7th-character
    codes, short + long descriptions, and the header/billable flag.
  - a tabular XML (optional)  "Tabular.xml" or "icd10cm_tabular_<year>.xml":
    used only for the chapter/block (section) skeleton so the hierarchy is
    rooted the same way as the existing icd-10-cm-2024 CodeSystem on the
    server (chapter code = its range, e.g. "A00-B99"; block code = section
    id, e.g. "A00-A09").

Output: output/CodeSystem-icd-10-cm-<year>.json, then PUT to
<fhir-base>/CodeSystem/icd-10-cm-<year> followed by $lookup smoke tests.

Conventions follow https://terminology.hl7.org/5.5.0/ICD.html and
CodeSystem-icd10CM.html: canonical url http://hl7.org/fhir/sid/icd-10-cm,
OID 2.16.840.1.113883.6.90, version = release year, codes WITH the dot.

Usage:
  python3 build_icd10cm_codesystem.py 2016 2017 2018 2019
  python3 build_icd10cm_codesystem.py 2016 --no-upload
  python3 build_icd10cm_codesystem.py 2016 --fhir-base https://velonto.dw.csiro.au/fhir
"""

import argparse
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from common import paths  # noqa: E402
from common.cli import add_common_args, resolve  # noqa: E402
from common.fhirclient import upload_and_verify  # noqa: E402

SYSTEM_URI = "http://hl7.org/fhir/sid/icd-10-cm"
OID = "urn:oid:2.16.840.1.113883.6.90"


def add_dot(code: str) -> str:
    return code if len(code) <= 3 else f"{code[:3]}.{code[3:]}"


def parse_order_file(path: Path):
    """Parse the fixed-width CMS order file.

    Layout (1-based columns): 1-5 order number, 7-13 code, 15 level flag
    (0 = header/non-billable, 1 = billable), 17-76 short description,
    78-end long description.
    """
    concepts = {}  # dotless code -> dict
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
            concepts[code] = {
                "code": code,
                "billable": flag == "1",
                "short": short,
                "display": long_ or short,
            }
    return concepts


def find_parents(concepts):
    """Parent = longest strict prefix that exists as a code (dotless)."""
    for code, c in concepts.items():
        c["parent"] = None
        for i in range(len(code) - 1, 2, -1):
            if code[:i] in concepts:
                c["parent"] = code[:i]
                break


RANGE_RE = re.compile(r"\(([A-Z][0-9A-Z]{2}(?:\.[0-9A-Z-]+)?-[A-Z][0-9A-Z]{2}(?:\.[0-9A-Z-]+)?)\)\s*$")


def parse_tabular_skeleton(path: Path):
    """Extract chapters and blocks (sections) plus category->block mapping.

    Returns (chapters, blocks, category_parent) where chapters/blocks are
    lists of {code, display, parent} and category_parent maps a 3-char
    category code to its block (or chapter) code.
    """
    tree = ET.parse(path)
    chapters, blocks, category_parent = [], [], {}
    for chapter in tree.getroot().iter("chapter"):
        desc = (chapter.findtext("desc") or "").strip()
        m = RANGE_RE.search(desc)
        if not m:
            # Derive the chapter range from its sections instead.
            ids = [s.get("id") for s in chapter.findall("section") if s.get("id")]
            first = ids[0].split("-")[0]
            last = ids[-1].split("-")[-1]
            chapter_code = f"{first}-{last}"
        else:
            chapter_code = m.group(1)
        chapters.append({"code": chapter_code, "display": desc, "parent": None})
        for section in chapter.findall("section"):
            sec_id = section.get("id")
            sec_desc = (section.findtext("desc") or "").strip()
            cats = [d.findtext("name").strip() for d in section.findall("diag")]
            if not cats:
                continue  # e.g. empty placeholder sections
            if "-" not in sec_id and len(cats) == 1 and cats[0] == sec_id:
                # Single-category section (e.g. "C7A"): no separate block
                # concept, the category hangs off the chapter directly.
                category_parent[sec_id] = chapter_code
                continue
            blocks.append({"code": sec_id, "display": sec_desc, "parent": chapter_code})
            for cat in cats:
                category_parent[cat] = sec_id
    return chapters, blocks, category_parent


def build_codesystem(year: str, concepts, chapters, blocks, category_parent):
    concept_entries = []

    def entry(code, display, parent=None, billable=None, short=None):
        e = {"code": code, "display": display}
        if short and short != display:
            e["designation"] = [{
                "use": {
                    "system": "http://snomed.info/sct",
                    "code": "900000000000013009",
                    "display": "Synonym",
                },
                "value": short,
            }]
        props = []
        if parent:
            props.append({"code": "parent", "valueCode": parent})
        if billable is not None:
            props.append({"code": "billable", "valueBoolean": billable})
        if props:
            e["property"] = props
        return e

    for ch in chapters:
        concept_entries.append(entry(ch["code"], ch["display"]))
    for bl in blocks:
        concept_entries.append(entry(bl["code"], bl["display"], parent=bl["parent"]))
    for c in concepts.values():
        if c["parent"]:
            parent = add_dot(c["parent"])
        else:
            parent = category_parent.get(c["code"])  # block/chapter, or None
        concept_entries.append(entry(
            add_dot(c["code"]), c["display"], parent=parent,
            billable=c["billable"], short=c["short"],
        ))

    fy_start = f"{int(year) - 1}-10-01"
    return {
        "resourceType": "CodeSystem",
        "id": f"icd-10-cm-{year}",
        "url": SYSTEM_URI,
        "identifier": [{"system": "urn:ietf:rfc:3986", "value": OID}],
        "version": year,
        "name": "ICD10CM",
        "title": ("International Classification of Diseases, Tenth Revision, "
                  f"Clinical Modification, FY{year}"),
        "status": "active",
        "experimental": False,
        "date": fy_start,
        "publisher": "Centers for Medicare & Medicaid Services (CMS) and "
                     "National Center for Health Statistics (NCHS)",
        "description": (f"ICD-10-CM FY{year} release (effective {fy_start}), "
                        "generated from the CMS code-descriptions-in-tabular-order "
                        "file, with chapter/block hierarchy from the tabular XML."),
        "copyright": ("ICD-10-CM is maintained by NCHS/CMS as a work of the "
                      "United States government and is in the public domain."),
        "caseSensitive": True,
        "valueSet": f"{SYSTEM_URI}?fhir_vs",
        "hierarchyMeaning": "is-a",
        "compositional": False,
        "versionNeeded": False,
        "content": "complete",
        "count": len(concept_entries),
        "property": [
            {
                "code": "parent",
                "uri": "http://hl7.org/fhir/concept-properties#parent",
                "description": "Parent concept (is-a)",
                "type": "code",
            },
            {
                "code": "billable",
                "description": "Whether the code is a valid (billable) code "
                               "for HIPAA-covered transactions, per the CMS "
                               "order file flag; false = header/category code.",
                "type": "boolean",
            },
        ],
        "concept": concept_entries,
    }


def locate_inputs(year_dir: Path, year: str):
    order = sorted(year_dir.glob(f"*order*{year}*.txt")) or sorted(year_dir.glob("*order*.txt"))
    if not order:
        raise FileNotFoundError(f"no order file (*order*.txt) found in {year_dir}")
    tabulars = sorted(p for p in year_dir.rglob("*.xml")
                      if p.name.lower() in ("tabular.xml", f"icd10cm_tabular_{year}.xml"))
    return order[0], (tabulars[0] if tabulars else None)


def probe_codes(cs):
    """A dotted 4-char code, the first 7-char code, and a block if present."""
    codes = ["A00.0"]
    seven = next((c["code"] for c in cs["concept"]
                  if "-" not in c["code"] and len(c["code"].replace(".", "")) == 7), None)
    if seven:
        codes.append(seven)
    block = next((c["code"] for c in cs["concept"]
                  if "-" in c["code"] and any(p["code"] == "parent" for p in c.get("property", []))), None)
    if block:
        codes.append(block)
    return codes


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("years", nargs="+", help="release year folders, e.g. 2016 2017")
    ap.add_argument("--base-dir", type=Path, default=paths.SOURCES / "icd10cm",
                    help=f"directory containing the year folders "
                         f"(default: {paths.SOURCES / 'icd10cm'})")
    add_common_args(ap)
    args = ap.parse_args()
    do_upload = resolve(args)

    failures = []
    for year in args.years:
        print(f"== FY{year} ==")
        year_dir = args.base_dir / year
        order_file, tabular_file = locate_inputs(year_dir, year)
        print(f"  order file: {order_file.name}")
        concepts = parse_order_file(order_file)
        find_parents(concepts)
        if tabular_file:
            print(f"  tabular:    {tabular_file.relative_to(year_dir)}")
            chapters, blocks, category_parent = parse_tabular_skeleton(tabular_file)
            missing = [c for c in concepts.values()
                       if not c["parent"] and c["code"] not in category_parent]
            if missing:
                print(f"  WARNING: {len(missing)} categories not found in tabular XML "
                      f"(left as roots): {[c['code'] for c in missing[:10]]}")
        else:
            print("  tabular:    none found; emitting category-rooted forest")
            chapters, blocks, category_parent = [], [], {}
        cs = build_codesystem(year, concepts, chapters, blocks, category_parent)
        n_codes = len(concepts)
        print(f"  concepts: {cs['count']} ({len(chapters)} chapters, "
              f"{len(blocks)} blocks, {n_codes} codes)")
        out = args.out_dir / f"CodeSystem-icd-10-cm-{year}.json"
        out.write_text(json.dumps(cs, indent=1))
        print(f"  wrote {out}")
        if do_upload:
            if not upload_and_verify(cs, args.fhir_base, SYSTEM_URI, year,
                                     probe_codes(cs)):
                failures.append(year)
    if failures:
        sys.exit(f"FAILED years: {', '.join(failures)}")


if __name__ == "__main__":
    main()
