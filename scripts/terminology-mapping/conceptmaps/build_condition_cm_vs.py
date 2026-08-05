#!/usr/bin/env python3
"""Build the Condition.code ConceptMap and its enumerated target ValueSet.

MIMIC's local dot-less ICD diagnosis codes -> official dotted ICD-9-CM /
ICD-10-CM, pinned to the earliest built release containing each code.

This is a NOTATION map, not a version crosswalk: every mapping is `equivalent`
and changes only the code's spelling (0389 -> 038.9), its display, and which
release it belongs to. It is NOT an ICD-9-to-ICD-10 GEM. The one wrinkle is a
handful of codes MIMIC filed under icd_version 9 that are really ICD-10-CM
(I509, J45901, ...); the ICD-9 source falls back to ICD-10-CM, which is how they
are found, and they land in their own group. That fallback is safe here because
the two revisions' diagnosis code spaces do not overlap — see
build_procedure_cm_vs.py for why the same fallback is forbidden for procedures.

Offline: reads the built CodeSystems in output/ and the IG's own resources,
writes four files, touches no network. Publish with upload.py.

Usage:
  uv run scripts/terminology-mapping/conceptmaps/build_condition_cm_vs.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from conceptmaps.lib.assemble import target                      # noqa: E402
from conceptmaps.lib.canonical import (CANONICAL_BASE, ICD9_CM,  # noqa: E402
                                       ICD10_CM, MIMIC_BASE)
from conceptmaps.lib.driver import run                           # noqa: E402
from conceptmaps.lib.notation import (dot_icd9_diagnosis,        # noqa: E402
                                      dot_icd10cm)

# The BOUND ELEMENT, not the source terminology. Every population is named for
# what it maps — procedure, observation, observation-component — so `make
# condition`, `unmapped-condition.csv` and `upload.py --only condition` all say
# the same word. It was `diagnosis` while the map was thought of as "the ICD
# diagnosis codes"; that named MIMIC's input rather than the column, and made
# this the one population whose make target and artefacts disagreed.
#
# The published canonicals are deliberately NOT renamed with it:
# ConceptMap/mimic-diagnosis-icd-to-sid and ValueSet/mimic-diagnosis are
# deployed and referenced by consumers, and a canonical is an identity, not a
# label. Only the local file names change.
FIELD = "condition"

# This map's own version. Deliberately not shared with the other builders: they
# are regenerated independently, and one global constant meant re-running one
# population silently relabelled every other population's artefacts.
VERSION = "1.0.0"

SOURCES = [
    {
        "system": f"{MIMIC_BASE}/CodeSystem/mimic-diagnosis-icd10",
        "file": "CodeSystem-mimic-diagnosis-icd10.json",
        "targets": [target(ICD10_CM, dot_icd10cm)],
    },
    {
        "system": f"{MIMIC_BASE}/CodeSystem/mimic-diagnosis-icd9",
        "file": "CodeSystem-mimic-diagnosis-icd9.json",
        # Ordered: ICD-9-CM first, ICD-10-CM as the cross-system fallback that
        # finds the mis-filed relabels. `kind` is required because THO gives
        # ICD-9-CM diagnoses (Vol 1-2) and procedures (Vol 3) the same canonical
        # URL, so without it this source would claim procedure codes.
        "targets": [
            target(ICD9_CM, dot_icd9_diagnosis, kind="diagnosis"),
            target(ICD10_CM, dot_icd10cm),
        ],
    },
]

META = {
    "id": "mimic-diagnosis-icd-to-sid",
    "name": "MimicDiagnosisIcdToSid",
    "title": "MIMIC local ICD diagnosis codes to ICD-9-CM / ICD-10-CM",
    "element": "Condition.code",
    # One map per bound field, so a consumer starting from a bound element
    # resolves exactly one map via ConceptMap?source-uri=<bound VS>.
    "source_valueset": f"{MIMIC_BASE}/ValueSet/mimic-diagnosis-icd",
    "target_valueset": f"{CANONICAL_BASE}/ValueSet/mimic-diagnosis",
    "description":
        "Maps MIMIC's local dot-less Condition.code codes onto the official "
        "dotted ICD codes, with the display and the release the code belongs "
        "to. Each group pins the target release in targetVersion; a code is "
        "mapped into the EARLIEST release that contains it. Lets consumers "
        "translate MIMIC codes on the fly rather than reading a rewritten copy "
        "of the source data.",
    "purpose":
        "This is a notation map, not a version crosswalk: every mapping is "
        "'equivalent' and changes only how the code is written, never which "
        "concept it means. It is NOT an ICD-9-to-ICD-10 GEM.",
    "target_title": "MIMIC diagnosis codes as standard ICD",
    "target_description":
        "Every code MIMIC-IV uses in Condition.code, written as official dotted "
        "ICD codes and pinned to the earliest release containing it. Derived "
        "from ConceptMap/mimic-diagnosis-icd-to-sid, whose targetCanonical this "
        "is, so membership here and reachability by $translate are the same "
        "set. Displays are the official ICD descriptions, not MIMIC's "
        "abbreviated text, so $validate-code never reports a display mismatch.",
    "cli_description": __doc__,
}


if __name__ == "__main__":
    sys.exit(run(FIELD, SOURCES, META, VERSION))
