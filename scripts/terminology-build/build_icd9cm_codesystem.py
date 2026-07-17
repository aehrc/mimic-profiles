#!/usr/bin/env python3
"""Convert the CDC ICD-9-CM FY2012 (v29) disease tabular RTF into a FHIR R4
CodeSystem, build the combined MIMIC diagnosis ValueSet, and upload both to
an Ontoserver instance.

Inputs (in ./2012_icd9/):
  - Dtab12.rtf (required): the "Disease Tabular" volume of the CDC FY2012
    release (the final ICD-9-CM content update, effective 2011-10-01),
    converted to plain text with the pure-Python `striprtf` library and
    recognised line by line. Supplies the code list, hierarchy, and header
    displays.
  - CMS29_DESC_LONG_DX*.txt (optional): the CMS v29 long descriptions.
    Tabular titles are contextless for subcodes (003.29 is just "Other"),
    so where available the CMS long description becomes the display and
    the tabular title is kept as a Synonym designation.

Codes that require a fourth/fifth digit are not listed individually in the
tabular; they are expanded here from the subdivision notes:
  - "The following fifth-digit subclassification is for use with ..." blocks
    define digit meanings; a "[0-3]"-style bracket line under a code lists
    which of those digits are valid for it.
  - "The following fourth-digit subdivisions are for use with categories
    X-Y" blocks (V30-V39, E800-E845) apply to every category in the range;
    a bracket under the category restricts the digits, otherwise all apply.
  - V30-V39 additionally get fifth digits 0/1 under the .0 fourth digit.

Output: output/CodeSystem-icd-9-cm-2012.json and the combined
output/ValueSet-mimic-diagnosis.json (ICD-9-CM 2012 + the pinned ICD-10-CM
versions), which replaces ValueSet mimic-diagnosis-icd10cm (deleted from
disk and from the server).

Conventions follow https://terminology.hl7.org/5.5.0/ICD.html: canonical url
http://hl7.org/fhir/sid/icd-9-cm, diagnosis OID 2.16.840.1.113883.6.103,
version = fiscal year (2012), codes WITH the dot, chapters/sections as
range-coded concepts, billable = leaf (code-to-highest-specificity rule).

Usage (`striprtf` is pinned in the repo's pyproject.toml; run via uv from the repo root):
  uv run scripts/terminology-build/build_icd9cm_codesystem.py
  uv run scripts/terminology-build/build_icd9cm_codesystem.py --no-upload
  uv run scripts/terminology-build/build_icd9cm_codesystem.py --fhir-base https://velonto.dw.csiro.au/fhir
"""

import argparse
import json
import os
import re
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import striprtf.striprtf

DEFAULT_FHIR_BASE = os.environ.get("ONTOSERVER_URL")
SYSTEM_URI = "http://hl7.org/fhir/sid/icd-9-cm"
OID = "urn:oid:2.16.840.1.113883.6.103"
VERSION = "2012"
FY_START = "2011-10-01"

ICD10_SYSTEM_URI = "http://hl7.org/fhir/sid/icd-10-cm"
ICD10_VERSIONS = ["2016", "2017", "2018", "2019", "2024"]
OLD_VS_ID = "mimic-diagnosis-icd10cm"

SSL_CONTEXT = ssl.create_default_context()
SSL_CONTEXT.check_hostname = False
SSL_CONTEXT.verify_mode = ssl.CERT_NONE

# separator is a tab, but a few lines have a stray space (538) or lost the
# tab entirely (066.40West Nile fever, 707.0x)
CODE_RE = re.compile(r"^(\d{3}|V\d{2}|E\d{3})(\.\d{1,2})? *(?:\t\s*|(?=[A-Z]))(.+?)\s*$")
BRACKET_RE = re.compile(r"^\[([\d,\s-]+)\]\s*$")
CHAPTER_RE = re.compile(r"^\d{1,2}\.\s+([A-Z].*?)\s*\(((?:\d{3})-(?:\d{3}))\)\s*$")
SUPP_CHAPTER_RE = re.compile(
    r"^(SUPPLEMENTARY CLASSIFICATION OF .*?)\s*\((([VE])[\dA-Z]+-\3[\dA-Z]+)\)\s*$")
SECTION_RE = re.compile(
    r"^([^a-z\t]*?)\s*\(((?:\d{3}|V\d{2}|E\d{3})(?:\.\d)?(?:-(?:\d{3}|V\d{2}|E\d{3})(?:\.\d)?)?)\)\s*$")
DIGIT_BLOCK_RE = re.compile(
    r"^The following .*?\b(fourth|fifth)s?[ -]digits?\b.*?"
    r"(?:for use with|to be used for)\s+(.+?):?\s*$")
# 634-637 define their stage fifth digits inline, scoped to that category.
DIGIT_BLOCK_INLINE_RE = re.compile(
    r"^Requires (?:following )?fifth digit to identify stage:?\s*$")
DIGIT_LINE_RE = re.compile(r"^(\d)\t(.+?)\s*$")
# A code or range token inside a block's "for use with ..." spec; ".4-.9"
# style tokens are relative to the previous full category in the spec.
SCOPE_TOKEN_RE = re.compile(
    r"(?:(\d{3}|V\d{2}|E\d{3})(\.\d{1,2})?|(\.\d{1,2}))"
    r"(?:\s*-\s*(?:(\d{3}|V\d{2}|E\d{3})(\.\d{1,2})?|(\.\d{1,2})))?")


def rtf_to_text(path: Path) -> list[str]:
    # latin-1 round-trips the raw bytes; striprtf resolves the \'xx escapes
    # itself from the RTF codepage. striprtf renders \line as "\n" where
    # textutil used U+2028, but splitlines() splits both the same way, so
    # the line list is identical to the old `textutil -convert txt` path.
    text = striprtf.striprtf.rtf_to_text(path.read_text(encoding="latin-1"))
    return text.splitlines()


def parse_scope(spec: str):
    """Parse a digit-block spec into (lo, hi) code-string ranges."""
    spec = re.split(r";| to denote| to identify| to indicate", spec)[0]
    ranges, last_cat = [], None
    for m in SCOPE_TOKEN_RE.finditer(spec):
        cat, sub, rel, cat2, sub2, rel2 = m.groups()
        lo = f"{cat}{sub or ''}" if cat else (last_cat + rel if last_cat else None)
        if lo is None:
            continue
        last_cat = cat or last_cat
        if cat2:
            hi = f"{cat2}{sub2 or ''}"
        elif rel2:
            hi = (cat or last_cat) + rel2
        else:
            hi = lo
        ranges.append((lo, hi))
    return ranges


def scope_covers(ranges, code: str) -> bool:
    cat = code.split(".")[0]
    for lo, hi in ranges:
        if lo == hi:
            if code == lo or code.startswith(lo + "."):
                return True
        elif "." in lo:  # dotted range like 493.0-493.2, within one length
            if len(code) == len(lo) and lo <= code <= hi:
                return True
        elif len(cat) == len(lo) == len(hi) and lo <= cat <= hi:
            return True
    return False


def parse_bracket(text: str) -> list[str]:
    digits = []
    for part in text.replace(" ", "").split(","):
        if "-" in part:
            a, b = part.split("-")
            digits.extend(str(d) for d in range(int(a), int(b) + 1))
        elif part:
            digits.append(part)
    return digits


def parse_tabular(lines: list[str]):
    """Single pass over the text: collect chapters, sections, codes (with any
    bracket line), and fourth/fifth-digit definition blocks."""
    chapters, sections, codes = [], [], []  # codes: dicts in document order
    single_sections = []  # single-category sections, e.g. "(042)", "(E849)"
    blocks = []  # {kind, ranges, digits{d: meaning}, pos}
    v3x_fifth = None  # the "two fifths-digits ... fourth-digit .0" block
    cur_chapter = cur_section = None
    collecting = None  # block currently accepting "digit<TAB>meaning" lines

    for pos, raw in enumerate(lines):
        line = raw.rstrip()
        if not line.strip():
            continue

        m = CODE_RE.match(line)
        if m:
            collecting = None
            code = m.group(1) + (m.group(2) or "")
            if "." not in code:
                parent = cur_section if cur_section else cur_chapter
            else:
                parent = None  # resolved from the dotted prefix later
            codes.append({"code": code, "display": m.group(3), "parent": parent,
                          "bracket": None, "pos": pos})
            continue

        m = BRACKET_RE.match(line)
        if m and codes:
            codes[-1]["bracket"] = parse_bracket(m.group(1))
            continue

        m = DIGIT_BLOCK_RE.match(line)
        if m:
            kind, spec = m.groups()
            if "fourth-digit .0" in spec:  # V30-V39 fifth digits on .0
                block = {"kind": "v3x-fifth", "ranges": [], "digits": {}, "pos": pos}
                v3x_fifth = block
            else:
                block = {"kind": kind, "ranges": parse_scope(spec),
                         "digits": {}, "pos": pos}
                blocks.append(block)
            collecting = block
            continue

        if DIGIT_BLOCK_INLINE_RE.match(line) and codes:
            cat = codes[-1]["code"]
            block = {"kind": "fifth", "ranges": [(cat, cat)], "digits": {},
                     "pos": pos}
            blocks.append(block)
            collecting = block
            continue

        if collecting is not None:
            dm = DIGIT_LINE_RE.match(line)
            if dm:
                collecting["digits"].setdefault(dm.group(1), dm.group(2))
                continue
            # prose interleaved with digit definitions is skipped, but a
            # heading ends the block (falls through to the checks below)

        m = CHAPTER_RE.match(line) or SUPP_CHAPTER_RE.match(line)
        if m and line.upper() == line:
            collecting = None
            cur_chapter, cur_section = m.group(2), None
            chapters.append({"code": m.group(2),
                             "display": f"{m.group(1).strip()} ({m.group(2)})"})
            continue

        m = SECTION_RE.match(line)
        if m and line.upper() == line and cur_chapter and "\t" not in line:
            collecting = None
            cur_section = m.group(2)
            display = f"{m.group(1).strip()} ({m.group(2)})"
            if "-" not in cur_section:
                # single-category section: the category hangs off the chapter;
                # if the tabular has no code line for it (E849), synthesise one
                single_sections.append({"code": cur_section, "display": display,
                                        "parent": cur_chapter, "pos": pos})
                cur_section = None
            else:
                sections.append({"code": cur_section, "display": display,
                                 "parent": cur_chapter})

    explicit = {c["code"] for c in codes}
    for s in single_sections:
        if s["code"] not in explicit:
            title, _, rng = s["display"].rpartition(" (")
            codes.append({"code": s["code"], "display": title.capitalize(),
                          "parent": s["parent"], "bracket": None, "pos": s["pos"]})
    codes.sort(key=lambda c: c["pos"])
    return chapters, sections, codes, blocks, v3x_fifth


def find_block(blocks, kind: str, code: str, pos: int, digit: str = None):
    """Latest block of `kind` defined before `pos` that covers `code` (and
    defines `digit`, when given)."""
    for b in reversed(blocks):
        if b["pos"] < pos and b["kind"] == kind and scope_covers(b["ranges"], code):
            if digit is None or digit in b["digits"]:
                return b
    return None


def expand_codes(codes, blocks, v3x_fifth):
    """Materialise the fourth/fifth-digit codes the tabular only implies."""
    warnings = []
    out = []
    has_children = {c["code"].split(".")[0] for c in codes if "." in c["code"]}

    def add_children(parent, digits, kind, scope_code):
        for d in digits:
            block = find_block(blocks, kind, scope_code, parent["pos"], d)
            if block is None:
                warnings.append(f"{parent['code']}: no {kind}-digit meaning "
                                f"for [{d}]")
                display = parent["display"]
            else:
                display = f"{parent['display']}, {block['digits'][d]}"
            sep = "" if "." in parent["code"] else "."
            child = {"code": f"{parent['code']}{sep}{d}", "display": display,
                     "parent": None, "bracket": None, "pos": parent["pos"]}
            out.append(child)
            if (v3x_fifth is not None and kind == "fourth" and d == "0"
                    and parent["code"].startswith("V3")):
                for d5, meaning in sorted(v3x_fifth["digits"].items()):
                    out.append({"code": f"{child['code']}{d5}",
                                "display": f"{child['display']}, {meaning}",
                                "parent": None, "bracket": None,
                                "pos": parent["pos"]})

    for c in codes:
        out.append(c)
        code, digits = c["code"], c["bracket"]
        if "." in code:
            if digits is not None:  # fifth digits for a subcategory
                add_children(c, digits, "fifth", code)
            continue
        if digits is not None and find_block(blocks, "fifth", code, c["pos"]):
            # bracket on a category holding fifth digits (657, 672): the
            # fourth digit is an implied 0 (".. Use 0 as fourth digit ..")
            mid = {"code": f"{code}.0", "display": c["display"],
                   "parent": None, "bracket": None, "pos": c["pos"]}
            out.append(mid)
            add_children(mid, digits, "fifth", code)
            continue
        block = find_block(blocks, "fourth", code, c["pos"])
        if block is None or (digits is None and code in has_children):
            continue  # ordinary category, children are explicit
        if digits is None:
            digits = sorted(block["digits"])
        else:
            # the defined subdivisions are authoritative; brackets can be
            # loose (E826 says [0-9] but .5-.7 are not defined codes)
            digits = [d for d in digits if d in block["digits"]]
        add_children(c, digits, "fourth", code)
    return out, warnings


def apply_cms_descriptions(codes, path: Path) -> int:
    """Use the CMS long description as display; the (contextless) tabular
    title moves to a designation. CMS codes are dotless."""
    cms = {}
    with open(path, encoding="latin-1") as f:
        for line in f:
            if line.strip():
                code, _, desc = line.rstrip("\n").partition(" ")
                cms[code] = desc.strip()
    applied = 0
    for c in codes:
        desc = cms.get(c["code"].replace(".", ""))
        if desc and desc != c["display"]:
            c["designation"] = c["display"]
            c["display"] = desc
            applied += 1
    return applied


def resolve_parents(codes):
    # last occurrence wins: chapter preambles list some codes (199, E001...)
    # before their real, correctly-sectioned entry appears
    by_code = {c["code"]: c for c in codes}
    dupes = len(codes) - len(by_code)
    for c in by_code.values():
        if c["parent"] is not None or "." not in c["code"]:
            continue
        stem = c["code"]
        while c["parent"] is None and len(stem) > 3:
            stem = stem[:-1].rstrip(".")
            if stem in by_code:
                c["parent"] = stem
    return list(by_code.values()), dupes


def build_codesystem(chapters, sections, codes):
    children = {c["parent"] for c in codes if c["parent"]}
    concept = []
    for ch in chapters:
        concept.append({"code": ch["code"], "display": ch["display"]})
    for sec in sections:
        concept.append({"code": sec["code"], "display": sec["display"],
                        "property": [{"code": "parent", "valueCode": sec["parent"]}]})
    for c in codes:
        props = []
        if c["parent"]:
            props.append({"code": "parent", "valueCode": c["parent"]})
        props.append({"code": "billable",
                      "valueBoolean": c["code"] not in children})
        entry = {"code": c["code"], "display": c["display"], "property": props}
        if c.get("designation"):
            entry["designation"] = [{
                "use": {
                    "system": "http://snomed.info/sct",
                    "code": "900000000000013009",
                    "display": "Synonym",
                },
                "value": c["designation"],
            }]
            entry = {k: entry[k] for k in
                     ("code", "display", "designation", "property")}
        concept.append(entry)
    return {
        "resourceType": "CodeSystem",
        "id": f"icd-9-cm-{VERSION}",
        "url": SYSTEM_URI,
        "identifier": [{"system": "urn:ietf:rfc:3986", "value": OID}],
        "version": VERSION,
        "name": "ICD9CM",
        "title": ("International Classification of Diseases, Ninth Revision, "
                  f"Clinical Modification, FY{VERSION}"),
        "status": "active",
        "experimental": False,
        "date": FY_START,
        "publisher": "Centers for Medicare & Medicaid Services (CMS) and "
                     "National Center for Health Statistics (NCHS)",
        "description": (f"ICD-9-CM FY{VERSION} diagnosis codes (v29, effective "
                        f"{FY_START}; the final content update before the ICD-9-CM "
                        "freeze), generated from the CDC Disease Tabular RTF with "
                        "fourth/fifth-digit subdivisions expanded and the "
                        "chapter/section hierarchy preserved; displays for valid "
                        "codes are the CMS v29 long descriptions, with the "
                        "tabular title as a synonym."),
        "copyright": ("ICD-9-CM is maintained by NCHS/CMS as a work of the "
                      "United States government and is in the public domain."),
        "caseSensitive": True,
        "valueSet": f"{SYSTEM_URI}?fhir_vs",
        "hierarchyMeaning": "is-a",
        "compositional": False,
        "versionNeeded": False,
        "content": "complete",
        "count": len(concept),
        "property": [
            {
                "code": "parent",
                "uri": "http://hl7.org/fhir/concept-properties#parent",
                "description": "Parent concept (is-a)",
                "type": "code",
            },
            {
                "code": "billable",
                "description": "Whether the code is a valid (billable) code for "
                               "HIPAA-covered transactions. Derived: a code is "
                               "billable iff it has no children (code-to-highest-"
                               "specificity rule); false = header/category code.",
                "type": "boolean",
            },
        ],
        "concept": concept,
    }


def build_valueset(today: str):
    return {
        "resourceType": "ValueSet",
        "id": "mimic-diagnosis",
        "url": "http://mimic.mit.edu/fhir/mimic/ValueSet/mimic-diagnosis",
        "version": "1.0.0",
        "name": "MimicDiagnosis",
        "title": "MIMIC Diagnosis (ICD-9-CM and ICD-10-CM)",
        "status": "active",
        "experimental": False,
        "date": today,
        "publisher": "CSIRO",
        "description": (
            "All diagnosis codes usable in MIMIC-IV: ICD-9-CM from the FY2012 "
            "release (v29, the final content update before the ICD-9-CM freeze, "
            "covering the whole MIMIC ICD-9 coding era) plus ICD-10-CM from the "
            "release years spanning the MIMIC-IV ICD-10 coding period "
            "(FY2016-FY2019 for the admission era, plus FY2024 covering codes "
            "introduced by later re-coding). Replaces the "
            "mimic-diagnosis-icd10cm ValueSet as the Condition.code source, "
            "with full is-a hierarchy support for both systems."),
        "compose": {
            "include": [
                {"system": SYSTEM_URI, "version": VERSION},
                *[{"system": ICD10_SYSTEM_URI, "version": v}
                  for v in ICD10_VERSIONS],
            ]
        },
    }


def http(method, url, data=None):
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Accept": "application/fhir+json",
        **({"Content-Type": "application/fhir+json; charset=utf-8"} if data else {}),
    })
    with urllib.request.urlopen(req, context=SSL_CONTEXT, timeout=600) as resp:
        body = resp.read()
        return resp.status, json.loads(body) if body else None


def upload(resource, fhir_base):
    url = f"{fhir_base}/{resource['resourceType']}/{resource['id']}"
    body = json.dumps(resource).encode("utf-8")
    print(f"  PUT {url} ({len(body) / 1e6:.1f} MB) ...")
    status, _ = http("PUT", url, body)
    print(f"  -> HTTP {status}")


def smoke_test(fhir_base):
    ok = True
    for code in ["250.00", "038.9", "V30.01", "E812.0", "001-139"]:
        q = urllib.parse.urlencode(
            {"system": SYSTEM_URI, "version": VERSION, "code": code})
        try:
            _, result = http("GET", f"{fhir_base}/CodeSystem/$lookup?{q}")
            display = next(p["valueString"] for p in result["parameter"]
                           if p["name"] == "display")
            print(f"  $lookup {code} -> {display}")
        except Exception as exc:  # noqa: BLE001
            print(f"  $lookup {code} FAILED: {exc}")
            ok = False
    for system, version, code in [(SYSTEM_URI, VERSION, "428.0"),
                                  (ICD10_SYSTEM_URI, "2019", "I50.9")]:
        q = urllib.parse.urlencode({
            "url": "http://mimic.mit.edu/fhir/mimic/ValueSet/mimic-diagnosis",
            "system": system, "systemVersion": version, "code": code})
        try:
            _, result = http("GET", f"{fhir_base}/ValueSet/$validate-code?{q}")
            valid = next(p["valueBoolean"] for p in result["parameter"]
                         if p["name"] == "result")
            print(f"  $validate-code {code} ({system.rsplit('/', 1)[-1]}) -> {valid}")
            ok = ok and valid
        except Exception as exc:  # noqa: BLE001
            print(f"  $validate-code {code} FAILED: {exc}")
            ok = False
    return ok


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", type=Path,
                    default=Path(os.environ.get("ICD_SOURCE_DIR",
                                                Path(__file__).parent))
                            / "2012_icd9" / "Dtab12.rtf",
                    help="CDC FY2012 Disease Tabular RTF "
                         "(default: $ICD_SOURCE_DIR/2012_icd9/Dtab12.rtf)")
    ap.add_argument("--out-dir", type=Path, default=Path(__file__).parent / "output")
    ap.add_argument("--fhir-base", default=DEFAULT_FHIR_BASE,
                    help="terminology server base URL (default: $ONTOSERVER_URL; "
                         "no upload when unset)")
    ap.add_argument("--no-upload", action="store_true", help="convert only")
    args = ap.parse_args()

    print(f"== ICD-9-CM FY{VERSION} ==")
    lines = rtf_to_text(args.source)
    chapters, sections, codes, blocks, v3x_fifth = parse_tabular(lines)
    codes, warnings = expand_codes(codes, blocks, v3x_fifth)
    codes, dupes = resolve_parents(codes)
    cms_files = sorted(args.source.parent.glob("CMS29_DESC_LONG_DX*.txt"))
    if cms_files:
        applied = apply_cms_descriptions(codes, cms_files[0])
        print(f"  CMS long descriptions applied to {applied} codes "
              f"({cms_files[0].name})")
    else:
        print("  no CMS29_DESC_LONG_DX file; keeping tabular titles as displays")
    for w in warnings[:20]:
        print(f"  WARNING: {w}")
    if len(warnings) > 20:
        print(f"  ... and {len(warnings) - 20} more warnings")
    orphans = [c["code"] for c in codes if not c["parent"]]
    if orphans:
        print(f"  WARNING: {len(orphans)} codes without a parent: {orphans[:10]}")
    if dupes:
        print(f"  NOTE: {dupes} duplicate code lines collapsed")

    cs = build_codesystem(chapters, sections, codes)
    billable = sum(1 for c in cs["concept"]
                   if any(p["code"] == "billable" and p["valueBoolean"]
                          for p in c.get("property", [])))
    print(f"  concepts: {cs['count']} ({len(chapters)} chapters, "
          f"{len(sections)} sections, {len(codes)} codes, {billable} billable)")

    args.out_dir.mkdir(parents=True, exist_ok=True)
    cs_out = args.out_dir / f"CodeSystem-icd-9-cm-{VERSION}.json"
    cs_out.write_text(json.dumps(cs, indent=1))
    print(f"  wrote {cs_out}")

    from datetime import date
    vs = build_valueset(date.today().isoformat())
    vs_out = args.out_dir / "ValueSet-mimic-diagnosis.json"
    vs_out.write_text(json.dumps(vs, indent=1))
    print(f"  wrote {vs_out}")
    old_vs_file = args.out_dir / f"ValueSet-{OLD_VS_ID}.json"
    if old_vs_file.exists():
        old_vs_file.unlink()
        print(f"  removed {old_vs_file} (superseded by ValueSet-mimic-diagnosis)")

    if args.no_upload:
        return
    if not args.fhir_base:
        print("  skipping upload: no --fhir-base and ONTOSERVER_URL unset")
        return
    try:
        upload(cs, args.fhir_base)
        upload(vs, args.fhir_base)
        try:
            status, _ = http("DELETE", f"{args.fhir_base}/ValueSet/{OLD_VS_ID}")
            print(f"  DELETE ValueSet/{OLD_VS_ID} -> HTTP {status}")
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                print(f"  DELETE ValueSet/{OLD_VS_ID} -> already absent")
            else:
                raise
        if not smoke_test(args.fhir_base):
            sys.exit("FAILED: smoke tests")
    except urllib.error.HTTPError as exc:
        sys.exit(f"UPLOAD FAILED: HTTP {exc.code}: "
                 f"{exc.read()[:2000].decode(errors='replace')}")


if __name__ == "__main__":
    main()
