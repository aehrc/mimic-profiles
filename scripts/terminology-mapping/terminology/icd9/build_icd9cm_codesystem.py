#!/usr/bin/env python3
"""Convert the CDC ICD-9-CM FY2012 (v29) tabular RTFs into a FHIR R4
CodeSystem and upload it to an Ontoserver instance.

Both ICD-9-CM volumes live in ONE CodeSystem. THO assigns diagnoses
(Volumes 1-2) and procedures (Volume 3) the same canonical URL
http://hl7.org/fhir/sid/icd-9-cm, differing only in OID, so a Coding cannot
distinguish them and a server can resolve that URL to exactly one resource.
The two volumes are told apart by the `kind` property (diagnosis|procedure).
This is safe because the dotted forms never collide: diagnosis codes have
three characters before the dot (or a V/E prefix), procedure codes two. The
DOT-LESS forms collide badly (4019 is both 401.9 and 40.19), which is why the
CMS description files are applied per volume and never to a merged code list.

Inputs (in sources/icd9/2012/):
  - Dtab12.rtf (required): the "Disease Tabular" volume of the CDC FY2012
    release (the final ICD-9-CM content update, effective 2011-10-01),
    converted to plain text with the pure-Python `striprtf` library and
    recognised line by line. Supplies the code list, hierarchy, and header
    displays.
  - CMS29_DESC_LONG_DX*.txt (optional): the CMS v29 long descriptions.
    Tabular titles are contextless for subcodes (003.29 is just "Other"),
    so where available the CMS long description becomes the display and
    the tabular title is kept as a Synonym designation.
  - Ptab12.RTF (optional): the "Procedure Tabular" (Volume 3). Same shape as
    the disease tabular but only two digits before the dot, one grouping
    level (chapter) instead of two, and fourth-digit subdivision blocks
    scoped to whole sections (77-80, 90, 91) or to listed subcategories
    (38.x, and 38.4 via its own inline block). Omit it and the CodeSystem is
    diagnosis-only, exactly as before this file grew a procedure half.
  - CMS29_DESC_LONG_SG*.txt (optional): the procedure counterpart of the DX
    long descriptions, applied the same way. SG = surgical.

Codes that require a fourth/fifth digit are not listed individually in the
tabular; they are expanded here from the subdivision notes:
  - "The following fifth-digit subclassification is for use with ..." blocks
    define digit meanings; a "[0-3]"-style bracket line under a code lists
    which of those digits are valid for it.
  - "The following fourth-digit subdivisions are for use with categories
    X-Y" blocks (V30-V39, E800-E845) apply to every category in the range;
    a bracket under the category restricts the digits, otherwise all apply.
  - V30-V39 additionally get fifth digits 0/1 under the .0 fourth digit.
  - procedures: a "The following fourth-digit subclassification is for use
    with ..." block plus a "[0-9]"-style bracket under each covered XX.X
    subcategory. Sections 90 and 91 define no brackets, so every subcategory
    takes every digit the block defines.

Output: output/CodeSystem-icd-9-cm-2012.json.

This script used to also emit output/ValueSet-mimic-diagnosis.json as a
composed value set over the whole ICD releases. That value set is now
enumerated from the ICD ConceptMap and owned entirely by
../../conceptmaps/build_condition_cm_vs.py — nothing about it lives here any
more, so running this script can no longer regress the server to the composed
form.

Conventions follow https://terminology.hl7.org/5.5.0/ICD.html: canonical url
http://hl7.org/fhir/sid/icd-9-cm, diagnosis OID 2.16.840.1.113883.6.103,
version = fiscal year (2012), codes WITH the dot, chapters/sections as
range-coded concepts, billable = leaf (code-to-highest-specificity rule).

Usage (`striprtf` is pinned in the repo's pyproject.toml; run via uv from the repo root):
  uv run scripts/terminology-mapping/terminology/icd9/build_icd9cm_codesystem.py
  uv run scripts/terminology-mapping/terminology/icd9/build_icd9cm_codesystem.py --no-upload
  uv run scripts/terminology-mapping/terminology/icd9/build_icd9cm_codesystem.py --fhir-base https://velonto.dw.csiro.au/fhir
"""

import argparse
import json
import re
import sys
from pathlib import Path

import striprtf.striprtf

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from common import paths  # noqa: E402
from common.cli import add_common_args, resolve  # noqa: E402
from common.fhirclient import upload_and_verify  # noqa: E402

SYSTEM_URI = "http://hl7.org/fhir/sid/icd-9-cm"
# THO lists ICD-9-CM twice under the one URL: .103 is Volumes 1-2 (diagnosis),
# .104 is Volume 3 (procedure). Both are carried as CodeSystem.identifier.
DX_OID = "urn:oid:2.16.840.1.113883.6.103"
PROC_OID = "urn:oid:2.16.840.1.113883.6.104"
VERSION = "2012"
FY_START = "2011-10-01"

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


# ---------------------------------------------------------------------------
# Volume 3 (procedures), from Ptab12.RTF
#
# Simpler than the disease tabular: two digits before the dot, one grouping
# level (chapter) rather than chapter+section, only fourth digits to expand,
# and no equivalent of the V30-V39 special case. Kept as its own parser rather
# than parameterising the diagnosis one, because almost every regex differs.
# ---------------------------------------------------------------------------

# Same tab-separator tolerance as CODE_RE: 26 subcategory lines lost the tab
# entirely (07.83Thoracoscopic..., 92.4Intra-operative...) and 17.52 carries a
# stray space before it. That tolerance is limited to DOTTED codes: a bare
# two-digit category always has its tab, and allowing the fallback there
# swallows inclusion terms that open with a number, e.g. "14 C-Urea breath
# test" (carbon-14, under 89.39) parsing as category 14.
PROC_CODE_RE = re.compile(r"^(\d{2}\.\d{1,2}) *(?:\t\s*|(?=[A-Z]))(.+?)\s*$")
PROC_CATEGORY_RE = re.compile(r"^(\d{2}) *\t\s*(.+?)\s*$")
# "0.  OPERATIONS ... (00)", "3A.  OTHER ... (17)", "10.OPERATIONS ... (55-59)"
PROC_CHAPTER_RE = re.compile(
    r"^\d{1,2}[A-Z]?\.\s*(.+?)\s*\((\d{2}(?:-\d{2})?)\)\s*$")
PROC_DIGIT_BLOCK_RE = re.compile(
    r"^The following fourth-digit subclassification is for use with\s+(.+?)\s*$")
# 38.4 defines its digits after its own code line instead of section-wide.
PROC_DIGIT_BLOCK_INLINE_RE = re.compile(
    r"^Requires the use of one of the following fourth-digit subclassifications")
PROC_SCOPE_TOKEN_RE = re.compile(r"\d{2}(?:\.\d)?")


def parse_procedure_scope(spec: str) -> list[str]:
    """Codes/sections a fourth-digit block applies to.

    Never split on "." here — it would cut "38.0, 38.1" apart. The trailing
    prose ("... according to site. Valid fourth-digits are in [brackets] ...")
    is dropped by the phrase split instead.
    """
    spec = re.split(r";|:| according to| to identify| to denote| to indicate",
                    spec)[0]
    return PROC_SCOPE_TOKEN_RE.findall(spec)


def proc_scope_covers(scope: list[str], code: str) -> bool:
    """A bare "77" covers every 77.x subcategory; "38.4" covers only itself."""
    return any(code == tok or code.startswith(tok + ".") for tok in scope)


def find_procedure_block(blocks, code: str, pos: int, digit: str = None):
    for b in reversed(blocks):
        if b["pos"] < pos and proc_scope_covers(b["scope"], code):
            if digit is None or digit in b["digits"]:
                return b
    return None


def parse_procedure_tabular(lines: list[str]):
    chapters, codes, blocks = [], [], []
    cur_chapter = None
    collecting = None  # block currently accepting "digit<TAB>meaning" lines

    for pos, raw in enumerate(lines):
        line = raw.rstrip()
        if not line.strip():
            continue

        m = PROC_CHAPTER_RE.match(line)
        if m and line.upper() == line:
            collecting = None
            cur_chapter = m.group(2)
            chapters.append({"code": cur_chapter,
                             "display": f"{m.group(1).strip()} ({cur_chapter})"})
            continue

        m = PROC_CODE_RE.match(line) or PROC_CATEGORY_RE.match(line)
        if m:
            collecting = None
            code = m.group(1)
            codes.append({"code": code, "display": m.group(2),
                          "parent": cur_chapter if "." not in code else None,
                          "bracket": None, "pos": pos})
            continue

        m = BRACKET_RE.match(line)
        if m and codes:
            codes[-1]["bracket"] = parse_bracket(m.group(1))
            continue

        m = PROC_DIGIT_BLOCK_RE.match(line)
        if m:
            block = {"scope": parse_procedure_scope(m.group(1)), "digits": {},
                     "pos": pos}
            blocks.append(block)
            collecting = block
            continue

        if PROC_DIGIT_BLOCK_INLINE_RE.match(line) and codes:
            # Anchored to the code it follows (38.4). Its own line number is
            # *after* that code, so record the anchor's position instead or
            # find_procedure_block's "defined before use" test would miss it.
            anchor = codes[-1]
            blocks.append({"scope": [anchor["code"]], "digits": {},
                           "pos": anchor["pos"] - 1})
            collecting = blocks[-1]
            continue

        if collecting is not None:
            dm = DIGIT_LINE_RE.match(line)
            if dm:
                collecting["digits"].setdefault(dm.group(1), dm.group(2))
                # prose interleaved with the digit definitions is ignored; the
                # next code line ends the block

    return chapters, codes, blocks


def expand_procedure_codes(codes, blocks):
    """Materialise the fourth-digit codes the procedure tabular only implies."""
    warnings, out = [], []
    has_children = {c["code"][:4] for c in codes if len(c["code"]) == 5}

    # Sections 38 and 77-80 mark the valid digits with a bracket line under
    # each subdivided subcategory; sections 90 and 91 define no brackets at all
    # and apply to every subcategory they cover. So an unbracketed code under a
    # bracket-using block takes no fourth digit and is a leaf in its own right
    # (80.6, "Excision of semilunar cartilage of knee").
    for c in codes:
        if c["bracket"] is not None and len(c["code"]) == 4:
            b = find_procedure_block(blocks, c["code"], c["pos"])
            if b is not None:
                b["uses_brackets"] = True

    for c in codes:
        out.append(c)
        code, digits = c["code"], c["bracket"]
        if len(code) != 4 or code in has_children:
            continue  # only XX.X subcategories, and only implied children
        block = find_procedure_block(blocks, code, c["pos"])
        if block is None:
            continue
        if digits is None:
            if block.get("uses_brackets"):
                continue
            digits = sorted(block["digits"])
        else:
            digits = [d for d in digits if d in block["digits"]]
        for d in digits:
            b = find_procedure_block(blocks, code, c["pos"], d)
            if b is None:
                warnings.append(f"{code}: no fourth-digit meaning for [{d}]")
                display = c["display"]
            else:
                display = f"{c['display']}, {b['digits'][d]}"
            out.append({"code": code + d, "display": display, "parent": code,
                        "bracket": None, "pos": c["pos"]})
    return out, warnings


def resolve_procedure_parents(codes):
    by_code = {c["code"]: c for c in codes}
    dupes = len(codes) - len(by_code)
    for c in by_code.values():
        # chapters 00 and 17 span a single category, so the chapter and the
        # category are the same string; that category is a root instead.
        if c["parent"] == c["code"]:
            c["parent"] = None
        if c["parent"] is not None:
            continue
        stem = c["code"][:-1].rstrip(".")
        while stem and stem not in by_code:
            stem = stem[:-1].rstrip(".")
        c["parent"] = stem or None
    return list(by_code.values()), dupes


def volume_concepts(chapters, sections, codes, kind):
    """Concepts for one ICD-9-CM volume, tagged with the `kind` property."""
    children = {c["parent"] for c in codes if c["parent"]}
    concept = []
    for ch in chapters:
        concept.append({"code": ch["code"], "display": ch["display"],
                        "property": [{"code": "kind", "valueCode": kind}]})
    for sec in sections:
        concept.append({"code": sec["code"], "display": sec["display"],
                        "property": [{"code": "parent", "valueCode": sec["parent"]},
                                     {"code": "kind", "valueCode": kind}]})
    for c in codes:
        props = []
        if c["parent"]:
            props.append({"code": "parent", "valueCode": c["parent"]})
        props.append({"code": "billable",
                      "valueBoolean": c["code"] not in children})
        props.append({"code": "kind", "valueCode": kind})
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
    return concept


def build_codesystem(chapters, sections, codes, proc_chapters, proc_codes):
    concept = volume_concepts(chapters, sections, codes, "diagnosis")
    concept += volume_concepts(proc_chapters, [], proc_codes, "procedure")
    volumes = "1-3" if proc_codes else "1-2"
    return {
        "resourceType": "CodeSystem",
        "id": f"icd-9-cm-{VERSION}",
        "url": SYSTEM_URI,
        "identifier": [{"system": "urn:ietf:rfc:3986", "value": DX_OID}]
                      + ([{"system": "urn:ietf:rfc:3986", "value": PROC_OID}]
                         if proc_codes else []),
        "version": VERSION,
        "name": "ICD9CM",
        "title": ("International Classification of Diseases, Ninth Revision, "
                  f"Clinical Modification, FY{VERSION} (Volumes {volumes})"),
        "status": "active",
        "experimental": False,
        "date": FY_START,
        "publisher": "Centers for Medicare & Medicaid Services (CMS) and "
                     "National Center for Health Statistics (NCHS)",
        "description": (f"ICD-9-CM FY{VERSION} codes (v29, effective {FY_START}; "
                        "the final content update before the ICD-9-CM freeze), "
                        "generated from the CDC tabular RTFs with fourth/fifth-"
                        "digit subdivisions expanded and the chapter/section "
                        "hierarchy preserved; displays for valid codes are the "
                        "CMS v29 long descriptions, with the tabular title as a "
                        "synonym. Carries both volumes, which THO assigns to this "
                        "one canonical URL: diagnoses (Volumes 1-2, OID "
                        "...6.103) and procedures (Volume 3, OID ...6.104), told "
                        "apart by the `kind` property. The dotted forms never "
                        "collide, but the dot-less forms do (4019 is both 401.9 "
                        "and 40.19), so a dot-less lookup must also carry `kind`."),
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
            {
                "code": "kind",
                "description": "Which ICD-9-CM volume the concept belongs to: "
                               "'diagnosis' (Volumes 1-2, OID ...6.103) or "
                               "'procedure' (Volume 3, OID ...6.104). Both share "
                               "this canonical URL per THO, so this property is "
                               "the only thing that separates them.",
                "type": "code",
            },
        ],
        "concept": concept,
    }


PROBE_CODES = ["250.00", "038.9", "V30.01", "E812.0", "001-139",
               "38.93", "96.04", "77.29"]


def build_procedures(source: Path):
    """Parse the procedure tabular and apply the CMS SG long descriptions.

    Returns ([], []) when the RTF is absent, which keeps the CodeSystem
    diagnosis-only rather than failing the build.
    """
    if not source.exists():
        print(f"  no {source.name}; building diagnoses only")
        return [], []

    lines = rtf_to_text(source)
    chapters, codes, blocks = parse_procedure_tabular(lines)
    codes, warnings = expand_procedure_codes(codes, blocks)
    codes, dupes = resolve_procedure_parents(codes)
    # A single-category chapter (00, 17) has the same code string as the
    # category itself, so the category stands in for it.
    chapters = [ch for ch in chapters if "-" in ch["code"]]

    # Applied to the procedure codes ONLY. Running the DX and SG maps over one
    # merged list would cross-assign: both files are keyed dot-less, where
    # 4019 means 401.9 to one and 40.19 to the other.
    sg_files = sorted(source.parent.glob("CMS29_DESC_LONG_SG*.txt"))
    if sg_files:
        applied = apply_cms_descriptions(codes, sg_files[0])
        print(f"  CMS long descriptions applied to {applied} procedure codes "
              f"({sg_files[0].name})")
    else:
        print("  no CMS29_DESC_LONG_SG file; keeping tabular titles as displays")
    for w in warnings[:20]:
        print(f"  WARNING: {w}")
    if len(warnings) > 20:
        print(f"  ... and {len(warnings) - 20} more warnings")
    if dupes:
        print(f"  NOTE: {dupes} duplicate procedure code lines collapsed")
    return chapters, codes


def check_against_cms(codes, source: Path):
    """The CMS SG file is the authority on which procedure codes exist, so the
    expanded leaf set must match it exactly. Any drift is an expansion bug."""
    sg_files = sorted(source.parent.glob("CMS29_DESC_LONG_SG*.txt"))
    if not sg_files:
        return
    official = set()
    with open(sg_files[0], encoding="latin-1") as f:
        for line in f:
            code = line[:4].strip()
            if code:
                official.add(code[:2] + "." + code[2:] if len(code) > 2 else code)
    parents = {c["parent"] for c in codes if c["parent"]}
    leaves = {c["code"] for c in codes if c["code"] not in parents}
    extra, missing = sorted(leaves - official), sorted(official - leaves)
    if extra or missing:
        print(f"  WARNING: leaf codes disagree with {sg_files[0].name}: "
              f"{len(extra)} not in CMS {extra[:8]}, "
              f"{len(missing)} missing {missing[:8]}")
    else:
        print(f"  leaf codes match {sg_files[0].name} exactly ({len(leaves)})")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    default_source = paths.SOURCES / "icd9" / "2012" / "Dtab12.rtf"
    default_proc = paths.SOURCES / "icd9" / "2012" / "Ptab12.RTF"
    ap.add_argument("--source", type=Path, default=default_source,
                    help=f"CDC FY2012 Disease Tabular RTF (default: {default_source})")
    ap.add_argument("--proc-source", type=Path, default=default_proc,
                    help=f"CDC FY2012 Procedure Tabular RTF (default: {default_proc})")
    add_common_args(ap)
    args = ap.parse_args()
    do_upload = resolve(args)

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

    proc_chapters, proc_codes = build_procedures(args.proc_source)
    if proc_codes:
        check_against_cms(proc_codes, args.proc_source)
        # The merge is only safe because the dotted forms are disjoint. Assert
        # it rather than trust it: a duplicate code would silently give one
        # concept two meanings.
        clash = ({c["code"] for c in codes} | {c["code"] for c in chapters}
                 | {c["code"] for c in sections}) & (
                     {c["code"] for c in proc_codes}
                     | {c["code"] for c in proc_chapters})
        if clash:
            sys.exit(f"FAILED: {len(clash)} codes collide across volumes: "
                     f"{sorted(clash)[:10]}")

    cs = build_codesystem(chapters, sections, codes, proc_chapters, proc_codes)
    billable = sum(1 for c in cs["concept"]
                   if any(p["code"] == "billable" and p["valueBoolean"]
                          for p in c.get("property", [])))
    print(f"  concepts: {cs['count']} ({len(chapters)} chapters, "
          f"{len(sections)} sections, {len(codes)} diagnosis codes, "
          f"{len(proc_chapters)} procedure chapters, "
          f"{len(proc_codes)} procedure codes, {billable} billable)")

    cs_out = args.out_dir / f"CodeSystem-icd-9-cm-{VERSION}.json"
    cs_out.write_text(json.dumps(cs, indent=1))
    print(f"  wrote {cs_out}")

    if do_upload and not upload_and_verify(cs, args.fhir_base, SYSTEM_URI,
                                           VERSION, PROBE_CODES):
        sys.exit("FAILED: upload or smoke tests")


if __name__ == "__main__":
    main()
