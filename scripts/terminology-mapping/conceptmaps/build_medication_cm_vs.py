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

THIS ELEMENT IS A CHOICE, AND MOST MIMIC PRESCRIPTIONS DO NOT USE THE BRANCH
THIS MAP SERVES. `mimic-medication-request` leaves medication[x] as
`CodeableConcept | Reference(MimicMedication)` — the only medication profile in
the IG that does not narrow it — and the ETL puts prescriptions' drug, gsn, ndc
and formulary_drug_cd on a shared Medication resource (see
input/includes/map-mimic-hosp-meds.md; the IG's own example instance uses
medicationReference). The full-data extract found 1,883,681 inline codings
against 15,416,901 MedicationRequest rows, so AT LEAST 87.8% of prescriptions
carry their drug code on Medication.code, which has its own map.

This map is not widened to cover them, and that is the correct answer rather
than a gap. $translate takes a Coding; a Reference carries none. A consumer
holding a medicationReference has nothing to translate until it dereferences,
and once it has, the Coding it holds came from Medication.code — a different
element with its own required binding. Folding those codes in here would assert
they are present on an element that does not carry them, and would compute a
coverage percentage against a population that does not exist.

Note also that the `required` binding on this element is INERT on the Reference
branch: a validator has nothing coded to check. For the majority of MIMIC
prescriptions the terminology guarantee is carried entirely by Medication.code's
binding, which is why that element is in occurrences/elements.json.

STREAMS, NOT PER-ELEMENT POPULATIONS. Each of the five source CodeSystems the
binding admits is one stream, declared once in lib/streams.py and resolved
identically for every map that consumes it — this one,
build_medication_code_cm_vs.py and build_medication_administration_cm_vs.py.
The generation population of each stream's table is still narrowed to the
codes the warehouse uses SOMEWHERE (lib/builders.table_population): sending
thousands of never-used labels through an LLM-backed service would cost hours
to populate rows no $translate call can reach. But the narrowing is by the
UNION across every bound element, not by this element's own usage, so a code
observed only behind a medicationReference resolves here exactly as it does on
Medication.code. Codes used nowhere stay `unmatched` with reason
`not-observed-in-data`; codes used somewhere but missing from a table are
`no-row-in-curated-table`, the signal to extend the table's generation
population.

The binding itself is correct and must not be narrowed to "fix" anything.
binding-analysis/FINDINGS.md chose `mimic-medication` because it covers 100%
of the codes actually seen, which is the right call under a `required`
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

from conceptmaps.lib.canonical import CANONICAL_BASE, MIMIC_BASE  # noqa: E402
from conceptmaps.lib.driver import run                            # noqa: E402
from conceptmaps.lib.streams import sources                       # noqa: E402

FIELD = "medication"

VERSION = "1.0.0"

# One declaration per stream, in lib/streams.py; this map only names
# which streams its facade ValueSet reaches. Order is group order.
SOURCES = sources(
    "medication-name",
    "medication-poe-iv",
    "formulary-drug",
    "medication-icu",
    "medication-ndc",
)

META = {
    "id": "mimic-medication-to-standard",
    "name": "MimicMedicationToStandard",
    "title": "MIMIC MedicationRequest.medication[x] to RxNorm and SNOMED CT",
    "element": "MedicationRequest.medication[x]",
    # The element's own facade, NOT the shared `mimic-medication` union. That
    # union is bound on four elements and each has its own map, so a shared
    # sourceCanonical leaves $translate unable to say which element a Coding came
    # from — and each map would then answer for
    # populations it was never scoped against. Identical membership, so no
    # instance validates differently. See VS_MimicMedicationRequestCode.fsh.
    "source_valueset": f"{MIMIC_BASE}/ValueSet/mimic-medication-request-code",
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
        "SCOPE: every one of the 20,288 codes the binding admits has an "
        "entry, and the answers are the STREAMS' — one shared resolution per "
        "source CodeSystem (see lib/streams.py), so this map, "
        "ConceptMap/mimic-medication-code-to-standard and "
        "ConceptMap/mimic-medication-administration-to-standard return the "
        "identical target for the same Coding. Where no answer exists the "
        "code is present as `unmatched` with a reason distinguishing a code "
        "that was considered and declined from one whose stream's table has "
        "no row for it yet and one the warehouse records nowhere at all. A "
        "$translate for any code the binding admits therefore returns an "
        "answer rather than nothing. "
        "IF YOUR CODING CAME FROM medicationReference you are not translating "
        "this element: resolve the reference and translate Medication.code "
        "against ConceptMap/mimic-medication-code-to-standard instead. Most "
        "MIMIC prescriptions take that branch."),
    "purpose": (
        "One ConceptMap per bound element, so a consumer starting from "
        "MedicationRequest.medication[x] resolves exactly one map. "
        "CONSUMERS MUST READ FOUR THINGS. "
        "Zeroth, and most likely to matter: medication[x] is a CHOICE, and this "
        "map serves the medicationCodeableConcept branch only. At least 87.8% "
        "of MIMIC MedicationRequests use medicationReference instead, where "
        "there is no Coding to translate at all — resolve the reference and "
        "translate Medication.code against "
        "ConceptMap/mimic-medication-code-to-standard. A pipeline that reads "
        "only medicationCodeableConcept will silently see an eighth of the "
        "prescriptions. "
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
