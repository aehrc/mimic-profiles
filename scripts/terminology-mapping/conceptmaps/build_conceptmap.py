#!/usr/bin/env python3
"""Build the MIMIC -> standard ICD notation ConceptMaps (stage 3).

THIS FILE IS THE ONLY PLACE MAPPING RULES LIVE. Everything downstream — the
per-field ValueSets, the coverage verifier, any consumer — reads the generated
ConceptMap and never re-derives a mapping. Historically the dot-insertion rules
were reimplemented in three scripts that drifted apart; if you find yourself
writing `code[:3] + "." + code[3:]` anywhere else in this repo, that is the bug.

What the maps are
-----------------
NOTATION maps, not crosswalks: every mapping is `equivalent` and changes only
the code's spelling (0389 -> 038.9), its display, and which release it belongs
to. The one exception is a handful of codes MIMIC filed under icd_version 9
that are really ICD-10-CM (I509, J45901, ...); those relabel across systems and
land in their own group.

One map per bound field, so a consumer starting from a bound element resolves
exactly one map via `ConceptMap?source-uri=<bound VS>&_summary=true`:

  Condition.code -> mimic-diagnosis-icd  =>  ConceptMap/mimic-diagnosis-icd-to-sid
  Procedure.code -> mimic-procedure-icd  =>  ConceptMap/mimic-procedure-icd-to-sid

Where the answers come from
---------------------------
The built CodeSystems in output/, which stage 1 wrote and uploaded, so the
files and the server hold the same content. Reading them locally costs nothing,
which keeps the phase-3 refine loop instant. Each code is mapped into the
EARLIEST release containing it, because `group.targetVersion` is the only place
R4 lets a target release be recorded (there is no version on group.element.target).

Disambiguation — read before touching the target tables
-------------------------------------------------------
MIMIC stores every ICD code dot-less, and the dot-less form is genuinely
ambiguous: '4019' is both diagnosis 401.9 and procedure 40.19. Two mechanisms
keep that straight, and both matter:

1. `kind`. ICD-9-CM diagnoses (Vol 1-2) and procedures (Vol 3) share one
   canonical URL per THO, so a Coding cannot distinguish them. The built
   CodeSystem carries a `kind` property ('diagnosis' / 'procedure') and each
   field only matches its own volume.

2. NO cross-target fallback for procedures. Diagnosis sources fall back to
   ICD-10-CM when a code misses ICD-9-CM, which is how the relabels are found.
   Applying the same fallback to procedures is actively harmful: 64 of MIMIC's
   2,544 ICD-9 procedure codes are verbatim valid 4-character ICD-10-PCS
   body-part groupers. MIMIC procedure 0095 means ICD-9 00.95, but as a raw
   string it matches PCS 0095 "Subarachnoid Space, Intracranial" — an anatomical
   structure, not a procedure. Worse, it would map silently and the unmapped
   report would read zero. Procedure sources therefore have exactly one target
   each, and PCS matches only 7-character leaves.

Usage:
  uv run scripts/terminology-mapping/conceptmaps/build_conceptmap.py            # both
  uv run scripts/terminology-mapping/conceptmaps/build_conceptmap.py diagnosis
  uv run scripts/terminology-mapping/conceptmaps/build_conceptmap.py --no-upload
"""

import argparse
import datetime
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common import paths  # noqa: E402
from common.cli import add_common_args, resolve  # noqa: E402
from common.fhirclient import upload  # noqa: E402

REPO = paths.ROOT.parent.parent
RESOURCES = REPO / "input" / "resources"

ICD9_CM = "http://hl7.org/fhir/sid/icd-9-cm"
ICD10_CM = "http://hl7.org/fhir/sid/icd-10-cm"
ICD10_PCS = "http://www.cms.gov/Medicare/Coding/ICD10"

MIMIC_BASE = "http://mimic.mit.edu/fhir/mimic"

# Our own canonical base. NOT mimic.mit.edu/fhir/mimic — that namespace belongs
# to the upstream IG's publisher (KinD Lab), and minting resources there risks a
# canonical collision on a shared terminology server. Referencing their
# canonicals is fine; creating new ones under their base is not. Consequence:
# resources under this base must NOT live in input/resources/, because the IG
# publisher requires every contained resource's url to start with the IG
# canonical.
CANONICAL_BASE = "http://fhnaumann.github.io/mimic-profiles/fhir"

VERSION = "1.0.0"


# --------------------------------------------------------------------------- #
# Dot insertion. Where the dot goes depends on BOTH the revision and whether the
# code is a diagnosis or a procedure — which is why the dot-less form alone can
# never tell you what it is.
# --------------------------------------------------------------------------- #

def dot_icd10cm(code):
    """ICD-10-CM: dot after the 3rd character, only when longer than 3."""
    return code[:3] + "." + code[3:] if len(code) > 3 else code


def dot_icd9_diagnosis(code):
    """ICD-9-CM Vol 1-2: E-codes after the 4th (E8500 -> E850.0), numeric and
    V-codes after the 3rd (20500 -> 205.00)."""
    if code[:1] in ("E", "e"):
        return code[:4] + "." + code[4:] if len(code) > 4 else code
    return code[:3] + "." + code[3:] if len(code) > 3 else code


def dot_icd9_procedure(code):
    """ICD-9-CM Vol 3: two digits before the dot (3226 -> 32.26)."""
    return code[:2] + "." + code[2:] if len(code) > 2 else code


def no_dot(code):
    """ICD-10-PCS: seven characters, no dot, ever."""
    return code


def is_pcs_leaf(code, props):
    """Only the 7-character leaves are real PCS codes; the 1/2/3/4-character
    tiers are navigational and carry notSelectable."""
    return len(code) == 7 and not props.get("notSelectable")


# --------------------------------------------------------------------------- #
# Target tables. `targets` is ordered: the first match wins, later entries are
# the cross-system fallback. Procedures deliberately have exactly one target
# each — see the module docstring.
# --------------------------------------------------------------------------- #

Target = dict  # {system, rule, kind, predicate}


def target(system, rule, kind=None, predicate=None):
    return {"system": system, "rule": rule, "kind": kind, "predicate": predicate}


FIELDS = {
    "diagnosis": {
        "id": "mimic-diagnosis-icd-to-sid",
        "name": "MimicDiagnosisIcdToSid",
        "title": "MIMIC local ICD diagnosis codes to ICD-9-CM / ICD-10-CM",
        "element": "Condition.code",
        "source_valueset": f"{MIMIC_BASE}/ValueSet/mimic-diagnosis-icd",
        "target_valueset": f"{CANONICAL_BASE}/ValueSet/mimic-diagnosis",
        "sources": [
            {
                "system": f"{MIMIC_BASE}/CodeSystem/mimic-diagnosis-icd10",
                "file": "CodeSystem-mimic-diagnosis-icd10.json",
                "targets": [target(ICD10_CM, dot_icd10cm)],
            },
            {
                "system": f"{MIMIC_BASE}/CodeSystem/mimic-diagnosis-icd9",
                "file": "CodeSystem-mimic-diagnosis-icd9.json",
                # Fallback to ICD-10-CM finds the codes MIMIC filed under
                # icd_version 9 that are really ICD-10-CM. Safe here because the
                # two revisions' code spaces do not overlap for diagnoses.
                "targets": [
                    target(ICD9_CM, dot_icd9_diagnosis, kind="diagnosis"),
                    target(ICD10_CM, dot_icd10cm),
                ],
            },
        ],
    },
    "procedure": {
        "id": "mimic-procedure-icd-to-sid",
        "name": "MimicProcedureIcdToSid",
        "title": "MIMIC local ICD procedure codes to ICD-9-CM Vol 3 / ICD-10-PCS",
        "element": "Procedure.code",
        "source_valueset": f"{MIMIC_BASE}/ValueSet/mimic-procedure-icd",
        "target_valueset": f"{CANONICAL_BASE}/ValueSet/mimic-procedure",
        "sources": [
            {
                "system": f"{MIMIC_BASE}/CodeSystem/mimic-procedure-icd10",
                "file": "CodeSystem-mimic-procedure-icd10.json",
                "targets": [target(ICD10_PCS, no_dot, predicate=is_pcs_leaf)],
            },
            {
                "system": f"{MIMIC_BASE}/CodeSystem/mimic-procedure-icd9",
                "file": "CodeSystem-mimic-procedure-icd9.json",
                # Exactly one target. Adding ICD-10-PCS here would map 64 codes
                # onto body-part groupers. See the module docstring.
                "targets": [target(ICD9_CM, dot_icd9_procedure, kind="procedure")],
            },
        ],
    },
}


# --------------------------------------------------------------------------- #
# Built CodeSystems
# --------------------------------------------------------------------------- #

def default_date(out_dir):
    """Newest mtime among the inputs, as a date.

    NOT today's date: these artefacts are committed, so a rebuild from
    unchanged inputs must produce a byte-identical file. Dating them 'now'
    would churn the diff every day and make a real change indistinguishable
    from a re-run.
    """
    inputs = list(out_dir.glob("CodeSystem-*.json"))
    inputs += [RESOURCES / s["file"] for f in FIELDS.values()
               for s in f["sources"] if (RESOURCES / s["file"]).is_file()]
    newest = max(p.stat().st_mtime for p in inputs) if inputs else 0
    return datetime.datetime.fromtimestamp(
        newest, datetime.timezone.utc).date().isoformat()


def concept_properties(concept):
    """Flatten CodeSystem.concept.property into a plain dict."""
    out = {}
    for prop in concept.get("property", []):
        for key in ("valueBoolean", "valueCode", "valueString"):
            if key in prop:
                out[prop["code"]] = prop[key]
                break
    return out


def load_built(out_dir):
    """(url, version) -> {code: (display, properties)}, from every built release."""
    built = {}
    for path in sorted(out_dir.glob("CodeSystem-*.json")):
        cs = json.loads(path.read_text())
        # Skip MIMIC's own CodeSystems if they ever land here; only standard
        # ICD releases are mapping targets.
        if cs["url"].startswith(MIMIC_BASE):
            continue
        built[(cs["url"], cs["version"])] = {
            c["code"]: (c.get("display", ""), concept_properties(c))
            for c in cs["concept"]
        }
        print(f"  loaded {path.name}: {cs['url']} v{cs['version']}, "
              f"{len(cs['concept']):,} concepts", file=sys.stderr)
    if not built:
        sys.exit(f"no CodeSystem-*.json in {out_dir} — run `make terminology` first")
    return built


def releases_of(built, system):
    """Every built release of a system, oldest first."""
    return sorted(v for (url, v) in built if url == system)


def find(built, tgt, official):
    """Earliest release of tgt['system'] holding `official`, honouring the
    target's kind filter and predicate. Returns (version, display) or None."""
    for version in releases_of(built, tgt["system"]):
        entry = built[(tgt["system"], version)].get(official)
        if entry is None:
            continue
        display, props = entry
        if tgt["kind"] and props.get("kind") != tgt["kind"]:
            continue
        if tgt["predicate"] and not tgt["predicate"](official, props):
            continue
        return version, display
    return None


# --------------------------------------------------------------------------- #
# Build
# --------------------------------------------------------------------------- #

def build_groups(field, built):
    """Resolve every MIMIC code, returning (groups, unmapped rows).

    Groups are keyed by (source system, target system, target version) because
    group.targetVersion is the only place R4 records a target release.
    """
    buckets = defaultdict(list)
    unmapped = []

    for source in field["sources"]:
        path = RESOURCES / source["file"]
        if not path.is_file():
            print(f"  {source['file']}: MISSING from input/resources/ — skipped",
                  file=sys.stderr)
            continue
        mimic = json.loads(path.read_text())
        concepts = mimic.get("concept", [])
        hits = 0

        for concept in concepts:
            code = concept["code"]
            for tgt in source["targets"]:
                official = tgt["rule"](code)
                found = find(built, tgt, official)
                if found:
                    version, display = found
                    buckets[(source["system"], tgt["system"], version)].append(
                        (code, concept.get("display", ""), official, display))
                    hits += 1
                    break
            else:
                primary = source["targets"][0]
                unmapped.append({
                    "field": field["element"],
                    "source_system": source["system"],
                    "mimic_code": code,
                    "mimic_display": concept.get("display", ""),
                    "expected_code": primary["rule"](code),
                    "expected_system": primary["system"],
                    "reason": "absent-from-all-built-releases",
                })

        print(f"  {source['file']:45s} {hits:>6,}/{len(concepts):<6,} mapped",
              file=sys.stderr)

    groups = []
    for key in sorted(buckets):
        source_system, target_system, version = key
        elements = []
        for code, mimic_display, official, display in sorted(buckets[key]):
            element = {"code": code}
            if mimic_display:
                element["display"] = mimic_display
            concept = {"code": official, "equivalence": "equivalent"}
            if display:
                concept["display"] = display
            element["target"] = [concept]
            elements.append(element)
        groups.append({
            "source": source_system,
            "target": target_system,
            "targetVersion": version,
            "element": elements,
        })
    return groups, unmapped


def unmatched_groups(unmapped):
    """Codes we looked at and deliberately did NOT map, as R4 `unmatched`.

    Recorded in the map itself so "considered, no target exists" is a
    machine-readable fact rather than only a line in a CSV. One group per
    (source system, system we searched), carrying the searched system as
    group.target but no targetVersion — the code is absent from every built
    release, so no single version is the right one to name. The elements carry
    equivalence `unmatched` and no target.code, which is precisely how R4 says
    to spell "looked, found nothing".

    group.target is required even though R4 itself allows a target-less group:
    Ontoserver rejects the write with `business-rule: ConceptMap.group.target
    is required` because its fallback is to infer the system from
    targetCanonical, and our target ValueSet spans several systems.

    NOT ConceptMap.group.unmapped — that element is a fallback *rule*, not a
    list. Its only plausible mode here, `provided`, would echo the source code
    back as though it were a valid code in the target system, so $translate
    would return a fabricated answer instead of reporting no match. A silent
    wrong answer is worse than a reported gap.
    """
    by_source = defaultdict(list)
    for row in unmapped:
        by_source[(row["source_system"], row["expected_system"])].append(row)

    groups = []
    for source_system, expected_system in sorted(by_source):
        elements = []
        for row in sorted(by_source[(source_system, expected_system)],
                          key=lambda r: r["mimic_code"]):
            element = {"code": row["mimic_code"]}
            if row["mimic_display"]:
                element["display"] = row["mimic_display"]
            element["target"] = [{
                "equivalence": "unmatched",
                "comment": (f"No {row['expected_system']} concept for the "
                            f"expected code {row['expected_code']} in any built "
                            f"release. Reason: {row['reason']}."),
            }]
            elements.append(element)
        groups.append({"source": source_system, "target": expected_system,
                       "element": elements})
    return groups


def build_conceptmap(field, built, date, version):
    groups, unmapped = build_groups(field, built)
    groups += unmatched_groups(unmapped)
    resource = {
        "resourceType": "ConceptMap",
        "id": field["id"],
        "url": f"{CANONICAL_BASE}/ConceptMap/{field['id']}",
        "version": version,
        "name": field["name"],
        "title": field["title"],
        "status": "active",
        "experimental": False,
        "date": date,
        "publisher": "CSIRO",
        "description":
            f"Maps MIMIC's local dot-less {field['element']} codes onto the "
            "official dotted ICD codes, with the display and the release the "
            "code belongs to. Each group pins the target release in "
            "targetVersion; a code is mapped into the EARLIEST release that "
            "contains it. Lets consumers translate MIMIC codes on the fly "
            "rather than reading a rewritten copy of the source data.",
        "purpose":
            "This is a notation map, not a version crosswalk: every mapping is "
            "'equivalent' and changes only how the code is written, never which "
            "concept it means. It is NOT an ICD-9-to-ICD-10 GEM.",
        "sourceCanonical": field["source_valueset"],
        "targetCanonical": field["target_valueset"],
        "group": groups,
    }
    return resource, unmapped


def write_unmapped(field_key, unmapped, out_dir):
    """One CSV per field, always written — an empty file is a meaningful
    result, and stage 5 refuses to publish while any row remains."""
    import csv
    path = out_dir / f"unmapped-{field_key}.csv"
    columns = ["field", "source_system", "mimic_code", "mimic_display",
               "expected_code", "expected_system", "reason"]
    with open(path, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns)
        writer.writeheader()
        writer.writerows(unmapped)
    return path


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("fields", nargs="*", choices=sorted(FIELDS) + [[]],
                    default=sorted(FIELDS),
                    help="which maps to build (default: all)")
    ap.add_argument("--version", default=VERSION,
                    help="ConceptMap.version (default: %(default)s)")
    ap.add_argument("--date",
                    help="ConceptMap.date (default: newest input mtime, so "
                         "rebuilds from unchanged inputs stay byte-identical)")
    add_common_args(ap)
    args = ap.parse_args()
    do_upload = resolve(args)

    date = args.date or default_date(args.out_dir)

    print("loading built CodeSystems ...", file=sys.stderr)
    built = load_built(args.out_dir)

    failed = False
    for key in args.fields:
        field = FIELDS[key]
        print(f"\n== {key} ({field['element']}) ==", file=sys.stderr)
        resource, unmapped = build_conceptmap(field, built, date, args.version)

        total = sum(len(g["element"]) for g in resource["group"])
        print(f"\n  {resource['url']}", file=sys.stderr)
        for group in resource["group"]:
            # The unmatched groups are the versionless ones: they searched
            # every built release of their target system rather than one.
            target = group["target"].rsplit("/", 1)[-1]
            version = group.get("targetVersion", "(any)")
            suffix = "" if "targetVersion" in group else "  unmatched"
            print(f"    {group['source'].rsplit('/', 1)[-1]:26s} -> "
                  f"{target:12s} {version:6s}"
                  f"{len(group['element']):>7,} element(s){suffix}",
                  file=sys.stderr)

        path = args.out_dir / f"ConceptMap-{field['id']}.json"
        path.write_text(json.dumps(resource, indent=1) + "\n")
        print(f"  wrote {path.name} ({path.stat().st_size / 1e6:.1f} MB, "
              f"{len(resource['group'])} groups, {total:,} elements)", file=sys.stderr)

        csv_path = write_unmapped(key, unmapped, args.out_dir)
        if unmapped:
            failed = True
            print(f"  UNMAPPED: {len(unmapped)} code(s) -> {csv_path.name}",
                  file=sys.stderr)
        else:
            print(f"  unmapped: none ({csv_path.name} is empty)", file=sys.stderr)

        if do_upload:
            upload(resource, args.fhir_base)

    if failed:
        print("\nSome codes are unmapped. Review the CSVs; `make upload-mappings` "
              "will refuse to publish until they are resolved or explicitly "
              "overridden.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
