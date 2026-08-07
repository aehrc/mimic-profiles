#!/usr/bin/env python3
"""Build the MedicationRequest.medication[x] ConceptMap and its target ValueSet.

MIMIC's local prescription drug names -> RxNorm, with SNOMED CT for the handful
of labels that name a drug CLASS rather than a product. Declaration only:
everything that computes lives in lib/, and the per-code answers live in the
committed table. See the field's issue (#25 in fhnaumann/master_thesis_pipeline)
for the probe evidence behind every setting named here.

THE FIRST STREAM TARGETING RxNorm, and the first that is not primarily
code-search. Roughly three fifths of the population is resolved by an exact
normalised-term join against RxNorm's own designations — deterministic, zero
ambiguity, no model and no confidence threshold — and code-search answers only
what the join cannot. build_medication_name_table.py owns both tiers.

WHY THIS MAP IS SCOPED TO OBSERVED CODES. `mimic-medication` is a union of five
MIMIC CodeSystems admitting 20,288 codes, but the warehouse only ever puts two
of them on THIS element: 2,888 drug names and the 2 `poe-iv` order flags. The
other three — NDC, formulary-drug-cd, ICU — carry 10,315 codes that appear on
MedicationAdministration.medication[x] instead, a different binding that gets
its own map. Sending 17,398 never-used labels through an LLM-backed service to
populate entries no $translate call can reach would cost hours and would report
a coverage percentage whose denominator is seven times the real population.

So both sources declare `observed_only`, and lib/igsource.py does the narrowing
once, where every stage reads it. The codes it sets aside are NOT dropped: each
one still gets an `unmatched` element carrying a comment that states the
assumption out loud, so a consumer translating a code this map did not expect to
exist is told why rather than met with silence. What the flag changes is only
the coverage denominator — see lib/assemble.py NOT_OBSERVED.

The binding itself is correct and must not be narrowed to "fix" this.
binding-analysis/FINDINGS.md chose `mimic-medication` because it covers 100% of
the 2,890 codes actually seen, which is the right call under a `required`
strength: a tighter ValueSet fails validation the first time a re-extract
surfaces an unseen drug name.

WHAT RxNorm STRUCTURALLY CANNOT ANSWER, and why the coverage ceiling here is a
property of the code system rather than of the method. Five labels carrying
332,767 occurrences — 17.7% of the element — have no RxNorm concept at any TTY:

    IV therapy (150,815)   an order modality, not a substance
    Insulin (122,879)      a drug CLASS; RxNorm 20231106 has 49 specific
                           insulins and no generic ingredient. RxCUI 5856 404s
    Influenza Vaccine      only season-dated concepts exist, and MIMIC records
      Quadrivalent (41,424)  no season, so any target invents one
    TPN (16,329)           a patient-specific compounded admixture
    Influenza Virus
      Vaccine (1,320)      as above

`Insulin` is the case SNOMED CT answers — `67866001 |Insulin|` is a substance
concept naming exactly the class MIMIC recorded — which is why this table is
mixed-target. `IV therapy` and `TPN` are NOT: they are a modelling defect one
layer below terminology (see issue #26), and giving them a SNOMED procedure code
would put a procedure in a column whose FHIRPath is `medication[x]`. They are
declared unmapped, which is the honest answer, and #26 tracks the real fix.

EQUIVALENCE is not this file's concern. Every mapping a table supplies is
`relatedto`, set by lib/assemble.py. A MIMIC drug name and an RxNorm concept are
related and this repo does not claim to know the direction — `Acetaminophen IV`
onto `acetaminophen 10 MG/ML Injection` adds a strength the label did not state,
even though it is the only IV strength RxNorm has.

Offline: reads the IG's own resources and the committed table, writes four
files, touches no network.

Usage:
  uv run scripts/terminology-mapping/conceptmaps/build_medication_cm_vs.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from conceptmaps.lib.assemble import target                       # noqa: E402
from conceptmaps.lib.canonical import (CANONICAL_BASE, MIMIC_BASE,  # noqa: E402
                                       RXNORM, SNOMED, TABLE_DIR)
from conceptmaps.lib.curated import MIXED_TARGET_COLUMNS          # noqa: E402
from conceptmaps.lib.driver import run                            # noqa: E402

FIELD = "medication"

VERSION = "1.0.0"

SOURCES = [
    {
        # The whole stream. 9,971 enumerated drug names, 2,888 of them ever
        # used on this element.
        "system": f"{MIMIC_BASE}/CodeSystem/mimic-medication-name",
        "file": "CodeSystem-mimic-medication-name.json",
        "observed_only": True,
        "table": TABLE_DIR / "medication-name-standard.csv",
        # Mixed-target because a few labels name a drug class rather than a
        # product, and SNOMED CT has the class concept where RxNorm has only
        # the specific products. Chosen at the table's creation deliberately:
        # a single-target table is never migrated to this shape later.
        "table_columns": MIXED_TARGET_COLUMNS,
        "targets": [target(RXNORM, None), target(SNOMED, None)],
    },
    {
        # Two codes, both declared unmapped, and no network call is made for
        # them. `IV therapy` and `TPN` are not medications — see the module
        # docstring and issue #26. They are declared here rather than left out
        # so that the 167,144 occurrences they carry are visibly accounted for.
        "system": f"{MIMIC_BASE}/CodeSystem/mimic-medication-poe-iv",
        "file": "CodeSystem-mimic-medication-poe-iv.json",
        "observed_only": True,
        # A stream reporting 0% coverage owes the reader a reason, or it reads
        # as a stream nobody finished. This one is complete: it maps nothing
        # BY DECISION, and the decision is not this repo's to reverse. The note
        # is carried through by_stream into the statistics so the number and
        # its explanation cannot drift apart.
        "blocked_upstream": True,
        "note": (
            "Maps nothing by design. `IV therapy` and `TPN` are POE order "
            "flags, not substances, so no RxNorm concept exists for either at "
            "any term type — and a SNOMED procedure code, which does exist, "
            "would put a procedure in a column whose FHIRPath is "
            "medication[x]. The 0% is the honest result of a modelling defect "
            "one layer down, in the ETL, not of a mapping that failed."),
        "note_url": "https://github.com/fhnaumann/master_thesis_pipeline/issues/26",
        "table": TABLE_DIR / "medication-poe-iv-standard.csv",
        "table_columns": MIXED_TARGET_COLUMNS,
        "targets": [target(RXNORM, None), target(SNOMED, None)],
    },
]

META = {
    "id": "mimic-medication-to-standard",
    "name": "MimicMedicationToStandard",
    "title": "MIMIC MedicationRequest.medication[x] to RxNorm and SNOMED CT",
    "element": "MedicationRequest.medication[x]",
    "source_valueset": f"{MIMIC_BASE}/ValueSet/mimic-medication",
    "target_valueset": f"{CANONICAL_BASE}/ValueSet/mimic-medication-standard",
    "description": (
        "Maps the MIMIC prescription drug names bound to "
        "MedicationRequest.medication[x] onto RxNorm, and onto SNOMED CT for "
        "the labels that name a drug class rather than a drug product. "
        "Two tiers produce it and both are recorded per row in the committed "
        "table: an exact normalised-term join against RxNorm's own "
        "designations, which is deterministic and unambiguous, and "
        "code-search for the remainder, gated on membership of the search "
        "constraint and on a confidence threshold. "
        "SCOPE: this map covers the codes the MIMIC warehouse actually "
        "records on this element. The bound ValueSet mimic-medication admits "
        "20,288 codes because it is a union serving several medication "
        "columns; only 2,890 of them ever appear here. The rest are present "
        "in this map as declared `unmatched` elements explaining that they "
        "were never observed, so a consumer that meets one is told the "
        "assumption rather than getting no answer."),
    "purpose": (
        "One ConceptMap per bound element, so a consumer starting from "
        "MedicationRequest.medication[x] resolves exactly one map. "
        "CONSUMERS MUST READ THREE THINGS. "
        "First, every mapping here is `relatedto`, never `equivalent`: a MIMIC "
        "drug name and an RxNorm concept are related, and the direction is not "
        "something this repo establishes. Filtering on `equivalence = "
        "equivalent` drops this entire population. Test instead for a target "
        "code being PRESENT, and accept `relatedto`. "
        "Second, targets are deliberately mixed in granularity. The search was "
        "not constrained to one RxNorm term type, so a label that states a "
        "strength gets a clinical-drug target and a bare ingredient name gets "
        "an ingredient target: `Acetaminophen` maps to the ingredient and "
        "`Acetaminophen IV` to a 10 MG/ML injection, because MIMIC records "
        "those as two different codes and collapsing them would destroy a "
        "distinction the source data carries. The target's own term type is "
        "the record of how specific the source label was. "
        "Third, roughly a sixth of this element's data volume has no target "
        "and never will. `IV therapy` and `TPN` are not medications at all; "
        "`Insulin` names a class RxNorm does not carry as a concept; the "
        "influenza vaccine labels record no season where RxNorm has only "
        "season-dated products. Each is declared `unmatched` with its reason "
        "rather than mapped to something that would read correctly and mean "
        "something else."),
    "target_title": "MIMIC MedicationRequest medications as RxNorm and SNOMED CT",
    "target_description": (
        "The RxNorm and SNOMED CT concepts every mapped MIMIC drug name "
        "resolves to. Derived from ConceptMap/mimic-medication-to-standard, "
        "whose targetCanonical this is, so membership here and reachability by "
        "$translate are the same set. "
        "Two systems, because one does not suffice. RxNorm carries the drug "
        "products and is the target for all but a handful of codes; SNOMED CT "
        "substances cover the labels naming a drug CLASS, which RxNorm does "
        "not model — `Insulin` is the largest, and RxNorm 20231106 has 49 "
        "specific insulins and no generic ingredient for it. "
        "The RxNorm members were drawn from the ingredient, brand and "
        "generic-product term types and deliberately NOT from branded drug "
        "products: that term type is where the search reliably asserted a "
        "brand, pack size or strength the MIMIC record never stated. The "
        "SNOMED members are all inside `<<105590001 |Substance|` and in the "
        "international core, which is what keeps this value set resolvable on "
        "a server other than the one it was built against. "
        "Neither include carries a version. This repo builds no RxNorm or "
        "SNOMED release, so pinning one would name something it cannot "
        "reproduce; the RxNorm release the table was generated against is "
        "recorded in output/medication-name-generation-log.json, where it is "
        "evidence rather than a promise. "
        "Note that several MIMIC codes legitimately share a member: MIMIC "
        "records case variants as distinct codes, so `LORazepam` and "
        "`Lorazepam` both resolve to RxCUI 6470 and cannot be told apart "
        "after translation."),
    "cli_description": __doc__,
}


def main():
    return run(FIELD, SOURCES, META, VERSION)


if __name__ == "__main__":
    sys.exit(main())
