#!/usr/bin/env python3
"""Build the Procedure.code ConceptMap and its enumerated target ValueSet.

Three code populations, three methods, one map.

Downstream pipelines merge every Procedure sub-type into one resource type, so
`Procedure.code` is ONE column carrying MIMIC's ICD codes, the two SNOMED CT
codes of mimic-procedure-types-ed, and the local mimic-d-items codes. A consumer
injects exactly one translate() over that column, and a code absent from the map
does not pass through — it yields nothing and the row's code goes null. Mapping
only the ICD population would therefore make every ED and ICU procedure silently
unsearchable. So all three live here, and codes that are ALREADY standard
terminology get an identity group rather than being left out: "needs no
translation" and "is missing from the map" are indistinguishable to a consumer,
and an identity group is what makes the first one say so out loud.

The methods, in the order they appear below:

  notation  ICD-10-PCS and ICD-9-CM Vol 3. Spelling only, every mapping
            `equivalent`.
  identity  the two ED SNOMED codes, which map to themselves, `equivalent`.
  table     the 169 ICU d_items, from conceptmaps/d-items-snomed.csv. Generated,
            not hand-written — see build_d_items_table.py. Every mapping
            `relatedto`: a flowsheet label and a SNOMED procedure are related,
            and the direction between them is not something this repo
            establishes, so it is not asserted.

NO CROSS-TARGET FALLBACK FOR PROCEDURES, unlike the diagnosis map. 64 of MIMIC's
2,544 ICD-9 procedure codes are verbatim valid 4-character ICD-10-PCS body-part
groupers: MIMIC procedure 0095 means ICD-9 00.95, but as a raw string it matches
PCS 0095 "Subarachnoid Space, Intracranial" — an anatomical structure, not a
procedure. Worse, it would map silently and the unmapped report would read zero.
Each procedure source therefore has exactly one target, and PCS matches only
7-character leaves (is_pcs_leaf). verify_mappings.py checks the guard holds.

Offline: reads the built CodeSystems in output/, the IG's own resources and the
committed table; touches no network. Publish with upload.py.

Usage:
  uv run scripts/terminology-mapping/conceptmaps/build_procedure_cm_vs.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from conceptmaps.lib.canonical import CANONICAL_BASE, MIMIC_BASE  # noqa: E402
from conceptmaps.lib.driver import run                            # noqa: E402
from conceptmaps.lib.streams import sources                       # noqa: E402

FIELD = "procedure"

# This map's own version. See build_condition_cm_vs.py.
VERSION = "1.0.0"

# The ICU table. Committed, so the build stays offline and deterministic; it is
# regenerated deliberately by `make d-items-table`, which needs the network and
# an LLM-backed service.

# One declaration per stream, in lib/streams.py; this map only names
# which streams its facade ValueSet reaches. Order is group order.
SOURCES = sources(
    "procedure-icd10",
    "procedure-icd9",
    "procedure-types-ed",
    "d-items",
)

META = {
    "id": "mimic-procedure-merged-to-standard",
    "name": "MimicProcedureMergedToStandard",
    "title": "MIMIC merged Procedure codes to ICD-9-CM Vol 3 / ICD-10-PCS / SNOMED CT",
    "element": "Procedure.code",
    # The MERGED bound value set: one column, three code populations.
    "source_valueset": f"{MIMIC_BASE}/ValueSet/mimic-procedure-merged-code",
    "target_valueset": f"{CANONICAL_BASE}/ValueSet/mimic-procedure-merged-standard",
    "description":
        "Maps every code the merged MIMIC Procedure profile admits onto "
        "standard terminology, so a consumer can translate the whole "
        "Procedure.code column through a single ConceptMap. MIMIC's dot-less "
        "ICD codes become official dotted ICD codes pinned to a release; codes "
        "that are already SNOMED CT map to themselves, so that translating the "
        "column preserves them instead of dropping them.",
    "purpose":
        "Lets a consumer translate the whole Procedure.code column with a "
        "single $translate. The ICD groups are a notation map — every mapping "
        "is 'equivalent' and changes only how the code is written, never which "
        "concept it means, and this is NOT an ICD-9-to-ICD-10 GEM. The SNOMED "
        "CT groups are different in kind: the ED codes are already SNOMED CT "
        "and map to themselves, 'equivalent', while every ICU d_items mapping "
        "is 'relatedto'. A flowsheet item like '16 Gauge' has no SNOMED concept "
        "of equal meaning, and the relationship to the peripheral cannula "
        "insertion it records is not a direction this resource claims to know, "
        "so it is not asserted. Consumers must therefore accept 'relatedto' as "
        "well as 'equivalent', or they will drop the whole ICU population. "
        "Where the code pair alone would mislead, the row carries a comment "
        "saying what the mapping does and does not cover.",
    # How the ICU groups were produced, travelling with the resource rather
    # than in a side file, because ConceptMap.copyright is what a consumer
    # actually receives.
    "copyright":
        "The ICU d_items groups were coded by an automated terminology "
        "search service constrained to procedures, clinical findings and "
        "events, and its answer kept only above a stated confidence "
        "threshold; every target was then checked against a terminology "
        "server and discarded unless it is active and in the SNOMED CT "
        "international core module; target display terms are the server's "
        "preferred term; items the service could not answer are left "
        "unmapped rather than guessed; and every mapping is 'relatedto', "
        "because no direction was established for any of them. SNOMED CT is "
        "distributed by SNOMED "
        "International; this resource references SNOMED CT codes and does "
        "not redistribute the terminology.",
    "target_title": "MIMIC merged Procedure codes as standard terminology",
    "target_description":
        "Every code the merged MIMIC Procedure profile admits, in standard "
        "terminology: MIMIC's ICD codes as official dotted ICD pinned to "
        "the earliest release containing them, plus the SNOMED CT codes "
        "that were already standard and map to themselves. Derived from "
        "ConceptMap/mimic-procedure-merged-to-standard, whose "
        "targetCanonical this is, so membership here and reachability by "
        "$translate are the same set. The SNOMED include carries no "
        "version: this repo builds no SNOMED release, so pinning one would "
        "name something it cannot reproduce.",
    "cli_description": __doc__,
}


if __name__ == "__main__":
    sys.exit(run(FIELD, SOURCES, META, VERSION))
