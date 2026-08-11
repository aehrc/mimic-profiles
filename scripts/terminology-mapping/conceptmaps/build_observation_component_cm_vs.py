#!/usr/bin/env python3
"""Build the Observation.component.code ConceptMap and its target ValueSet.

Two codes, one identity group, and a separate map from Observation.code on
purpose.

MIMIC-ED stores `sbp` and `dbp` as two columns of one row, which FHIR models as
ONE Observation coded 85354-9 |Blood pressure panel| carrying the two numbers in
`component` — about 2M such rows in the warehouse, the largest coded Observation
population measured. The two component codes are already LOINC, so the mapping
is identity: present so a consumer translating that column gets systolic and
diastolic back rather than nothing. "Needs no translation" and "is missing from
the map" are indistinguishable to a consumer, and an identity group is what makes
the first one say so out loud — the same argument as the Procedure map's ED
SNOMED codes.

WHY NOT ONE MAP WITH Observation.code. `Observation.code` and
`Observation.component.code` are different FHIRPath expressions over the same
resource, so a consumer projects them as two columns and injects one $translate
per column. A consumer states, per column, the ConceptMap it projects through
AND the source value set it expects that map to declare. Merging the two
populations leaves no correct `sourceCanonical` to declare: the component codes
are bound to MimicObservationComponentVital, not to the merged
Observation.code value set, and they cannot be folded into the latter because it
is bound with REQUIRED strength — including them there would legalise
`code = 8480-6 |Systolic blood pressure|` on a merged Observation, a code MIMIC
only ever emits inside a component.

The failure that argument prevents is concrete, not theoretical. One merged map
puts 8480-6 in the target value set a consumer searches for the
`Observation.code` column, so a search for "systolic blood pressure" resolves,
projects back, and filters `Observation.code = 8480-6` — which matches nothing,
silently, while every check still passes. Two maps put each code in exactly the
one column that can hold it.

Both maps therefore name a source value set that already exists in the IG and is
published by scripts/publish-conformance.sh, and this repo mints no new source
canonical for either.

Offline: reads only the IG's own resources; touches no network. Publish with
upload.py.

Usage:
  uv run scripts/terminology-mapping/conceptmaps/build_observation_component_cm_vs.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from conceptmaps.lib.canonical import CANONICAL_BASE, MIMIC_BASE  # noqa: E402
from conceptmaps.lib.driver import run                            # noqa: E402
from conceptmaps.lib.streams import sources                       # noqa: E402

FIELD = "observation-component"

# This map's own version. See build_condition_cm_vs.py.
VERSION = "1.0.0"

# One declaration per stream, in lib/streams.py; this map only names
# which streams its facade ValueSet reaches. Order is group order.
SOURCES = sources(
    "observation-component-vital",
)

META = {
    "id": "mimic-observation-component-to-standard",
    "name": "MimicObservationComponentToStandard",
    "title": "MIMIC Observation component codes to LOINC",
    "element": "Observation.component.code",
    # The bound value set itself: this element admits exactly these two codes,
    # so the map's source scope and the binding are the same set.
    "source_valueset": f"{MIMIC_BASE}/ValueSet/mimic-observation-component-vital",
    "target_valueset":
        f"{CANONICAL_BASE}/ValueSet/mimic-observation-component-standard",
    "description":
        "Maps every code the merged MIMIC Observation profile admits on "
        "Observation.component.code — the systolic and diastolic codes of the "
        "blood-pressure panel — onto standard terminology. Both are already "
        "LOINC and map to themselves, so translating the component column "
        "preserves the two labels that tell systolic from diastolic instead of "
        "dropping them. Separate from "
        "ConceptMap/mimic-observation-merged-to-standard because "
        "Observation.component.code is a separate column with a separate "
        "binding: these codes are not legal values of Observation.code.",
    "purpose":
        "Lets a consumer translate the Observation.component.code column with a "
        "single $translate, the same way it translates Observation.code through "
        "its own map. The mappings are identity and are stated rather than "
        "omitted because a consumer cannot otherwise tell a code that needs no "
        "translation from one the map is missing — $translate returns nothing "
        "in both cases. They are coded 'equivalent' rather than 'equal', "
        "matching the other maps, because consumers that pin the equivalence "
        "they accept filter 'equal' out.",
    "target_title": "MIMIC Observation component codes as standard terminology",
    "target_description":
        "The two LOINC codes the merged MIMIC Observation profile admits on "
        "Observation.component.code. Derived from "
        "ConceptMap/mimic-observation-component-to-standard, whose "
        "targetCanonical this is, so membership here and reachability by "
        "$translate are the same set. Deliberately narrow: it is the search "
        "space for the component column alone, and a consumer that searched "
        "these codes against Observation.code would match nothing, because "
        "MIMIC only ever emits them inside a component. The LOINC include "
        "carries no version: this repo builds no LOINC release, so pinning one "
        "would name something it cannot reproduce.",
    "cli_description": __doc__,
}


if __name__ == "__main__":
    sys.exit(run(FIELD, SOURCES, META, VERSION))
