#!/usr/bin/env python3
"""Phase 0: scan the built MIMIC-on-FHIR IG package for candidate coded elements.

Reads StructureDefinitions straight out of ``output/package.tgz`` and emits the
list of coded fields (CodeableConcept / Coding / code) that *could* carry a
ValueSet binding but do not yet (no binding, or only an ``example`` binding).
Fields that already have a required/extensible/preferred binding are recorded
separately in ``already_bound`` for reference.

Output: ``scripts/binding-analysis/work-items.json`` + a summary table on stdout.

Python 3 stdlib only. See RUNBOOK.md for the surrounding pipeline.
"""

from __future__ import annotations

import argparse
import json
import sys
import tarfile
from pathlib import Path

MIMIC_SD_PREFIX = "http://mimic.mit.edu/fhir/mimic/StructureDefinition/"
CODED_TYPES = ("CodeableConcept", "Coding", "code")
NON_EXAMPLE_STRENGTHS = ("required", "extensible", "preferred")

# PascalCase suffix on a Spark column name -> FHIRPath type token used in
# `.ofType(...)`. Copied verbatim from
# master_thesis_pipeline/orchestration-new/src/services/fhir_polymorphic.py
# (_FHIR_TYPE_SUFFIX_TO_FHIRPATH). Complex FHIR types keep PascalCase,
# primitives go lowercase, per the FHIRPath spec.
_FHIR_TYPE_SUFFIX_TO_FHIRPATH: dict[str, str] = {
    # Complex types
    "CodeableConcept": "CodeableConcept",
    "SampledData": "SampledData",
    "ContactPoint": "ContactPoint",
    "HumanName": "HumanName",
    "Identifier": "Identifier",
    "Annotation": "Annotation",
    "Attachment": "Attachment",
    "Reference": "Reference",
    "Signature": "Signature",
    "Quantity": "Quantity",
    "Duration": "Duration",
    "Distance": "Distance",
    "Timing": "Timing",
    "Period": "Period",
    "Count": "Count",
    "Money": "Money",
    "Range": "Range",
    "Ratio": "Ratio",
    "Coding": "Coding",
    "Address": "Address",
    "Age": "Age",
    # Primitive types
    "Base64Binary": "base64Binary",
    "PositiveInt": "positiveInt",
    "UnsignedInt": "unsignedInt",
    "DateTime": "dateTime",
    "Canonical": "canonical",
    "Markdown": "markdown",
    "Boolean": "boolean",
    "Decimal": "decimal",
    "Instant": "instant",
    "Integer": "integer",
    "String": "string",
    "Date": "date",
    "Time": "time",
    "Uuid": "uuid",
    "Code": "code",
    "Uri": "uri",
    "Url": "url",
    "Oid": "oid",
    "Id": "id",
}


def _read_package(tgz_path: Path) -> tuple[str, list[dict]]:
    """Return ``(package_id, [StructureDefinition, ...])`` from the tarball."""
    package_id = "unknown"
    sds: list[dict] = []
    with tarfile.open(tgz_path, "r:gz") as tar:
        for member in tar.getmembers():
            if not member.isfile() or not member.name.endswith(".json"):
                continue
            fh = tar.extractfile(member)
            if fh is None:
                continue
            try:
                doc = json.load(fh)
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue
            if member.name.endswith("package/package.json") and "name" in doc:
                package_id = f"{doc.get('name')}#{doc.get('version')}"
            elif doc.get("resourceType") == "StructureDefinition":
                sds.append(doc)
    return package_id, sds


def _is_mimic_profile(sd: dict) -> bool:
    return (
        str(sd.get("url", "")).startswith(MIMIC_SD_PREFIX)
        and sd.get("kind") == "resource"
        and sd.get("derivation") == "constraint"
    )


def _path_is_metadata(path: str) -> bool:
    """Paths we never bind: extension segments and the resource plumbing."""
    segments = path.split(".")
    if any(seg in ("extension", "modifierExtension") for seg in segments):
        return True
    if len(segments) >= 2 and segments[1] in ("id", "meta", "contained", "implicitRules", "language", "text"):
        return True
    return False


def _id_is_slice(element_id: str) -> bool:
    """True when the element id carries any slice (``:``). Slice re-statements
    (choice-type slices like ``medication[x]:medicationCodeableConcept`` and
    their children, or extension slices) duplicate the base un-sliced element
    or describe sub-structure that is not an idiomatic binding target."""
    return any(":" in segment for segment in element_id.split("."))


def _coded_types(element: dict) -> list[str]:
    return [t.get("code") for t in element.get("type", []) if t.get("code") in CODED_TYPES]


def _extract_path(path: str, resource_type: str, fhir_type: str) -> str:
    """Element path -> FHIRPath expression to extract the code, resourceType
    prefix stripped. Choice types (`foo[x]`) become `foo.ofType(<Type>)`."""
    rel = path
    prefix = resource_type + "."
    if rel.startswith(prefix):
        rel = rel[len(prefix) :]
    elif rel == resource_type:
        rel = ""

    if rel.endswith("[x]"):
        base = rel[: -len("[x]")]
        token = _FHIR_TYPE_SUFFIX_TO_FHIRPATH.get(fhir_type, fhir_type)
        rel = f"{base}.ofType({token})"

    if fhir_type == "CodeableConcept":
        return rel + ".coding"
    return rel  # Coding and code select directly


def _binding_info(binding: dict | None) -> tuple[str | None, str | None]:
    if not binding:
        return None, None
    return binding.get("strength"), binding.get("valueSet")


def analyze(sd: dict, candidates: list, already_bound: list) -> None:
    resource_type = sd.get("type", "")
    profile_id = sd.get("id", "")
    profile_url = sd.get("url", "")
    elements = sd.get("snapshot", {}).get("element", [])

    # Map every element path to a non-example binding sitting on its `.coding`
    # child (the GSN-style wart): parent CodeableConcept must not be a candidate.
    coding_child_binding: dict[str, dict] = {}
    for el in elements:
        path = el.get("path", "")
        if not path.endswith(".coding"):
            continue
        strength, value_set = _binding_info(el.get("binding"))
        if strength in NON_EXAMPLE_STRENGTHS:
            coding_child_binding[path[: -len(".coding")]] = {
                "strength": strength,
                "value_set": value_set,
            }

    seen_extract: set[str] = set()
    for el in elements:
        path = el.get("path", "")
        element_id = el.get("id", "")
        if el.get("max") == "0":
            continue
        if _path_is_metadata(path) or _id_is_slice(element_id):
            continue
        types = _coded_types(el)
        if not types:
            continue

        strength, value_set = _binding_info(el.get("binding"))

        # GSN wart: binding lives on the `.coding` child, not here.
        wart = coding_child_binding.get(path)
        if wart is not None:
            already_bound.append({
                "profile_id": profile_id,
                "element_id": element_id,
                "binding_strength": wart["strength"],
                "value_set": wart["value_set"],
                "note": "binding on .coding child (non-idiomatic)",
            })
            continue

        # Already bound: required / extensible / preferred (own or inherited).
        if strength in NON_EXAMPLE_STRENGTHS:
            already_bound.append({
                "profile_id": profile_id,
                "element_id": element_id,
                "binding_strength": strength,
                "value_set": value_set,
                "note": None,
            })
            continue

        # Candidate: no binding, or example binding. One item per matching type.
        existing_binding = {"strength": strength, "value_set": value_set} if strength else None
        for fhir_type in types:
            extract_path = _extract_path(path, resource_type, fhir_type)
            dedup_key = f"{profile_id}|{extract_path}"
            if dedup_key in seen_extract:
                continue
            seen_extract.add(dedup_key)
            candidates.append({
                "profile_id": profile_id,
                "profile_url": profile_url,
                "resource_type": resource_type,
                "element_id": element_id,
                "element_path": path,
                "type": fhir_type,
                "extract_path": extract_path,
                "system_in_data": fhir_type != "code",
                "existing_binding": existing_binding,
            })


def _print_summary(profiles: list[dict], candidates: list, already_bound: list) -> None:
    by_profile: dict[str, dict] = {}
    for c in candidates:
        p = by_profile.setdefault(c["profile_id"], {"cand": 0, "bound": 0})
        p["cand"] += 1
    for b in already_bound:
        p = by_profile.setdefault(b["profile_id"], {"cand": 0, "bound": 0})
        p["bound"] += 1

    print(f"\n{'PROFILE':<40} {'CANDIDATES':>11} {'ALREADY_BOUND':>14}")
    print("-" * 67)
    for pid in sorted(by_profile):
        row = by_profile[pid]
        print(f"{pid:<40} {row['cand']:>11} {row['bound']:>14}")
    print("-" * 67)
    print(f"{'TOTAL (' + str(len(by_profile)) + ' profiles)':<40} "
          f"{len(candidates):>11} {len(already_bound):>14}\n")

    print("Candidate elements (profile / element / type / extract_path):")
    for c in candidates:
        print(f"  {c['profile_id']:<38} {c['element_id']:<48} {c['type']:<16} {c['extract_path']}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "package",
        nargs="?",
        default="output/package.tgz",
        help="path to the built IG package tarball (default: output/package.tgz)",
    )
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[2]
    tgz_path = Path(args.package)
    if not tgz_path.is_absolute():
        tgz_path = repo_root / tgz_path
    if not tgz_path.exists():
        print(f"error: package not found: {tgz_path}", file=sys.stderr)
        return 1

    package_id, sds = _read_package(tgz_path)
    profiles = [sd for sd in sds if _is_mimic_profile(sd)]

    candidates: list[dict] = []
    already_bound: list[dict] = []
    for sd in sorted(profiles, key=lambda s: s.get("id", "")):
        analyze(sd, candidates, already_bound)

    output = {
        "generated_from": package_id,
        "candidates": candidates,
        "already_bound": already_bound,
    }

    out_path = Path(__file__).resolve().parent / "work-items.json"
    out_path.write_text(json.dumps(output, indent=2) + "\n")

    print(f"generated_from: {package_id}")
    print(f"scanned {len(profiles)} MIMIC resource profiles "
          f"(of {len(sds)} StructureDefinitions in package)")
    _print_summary(profiles, candidates, already_bound)
    print(f"wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
