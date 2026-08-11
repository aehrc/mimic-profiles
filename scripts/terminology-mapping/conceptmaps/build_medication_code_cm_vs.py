#!/usr/bin/env python3
"""Build the Medication.code ConceptMap and its target ValueSet.

THE MAP THE REFERENCE BRANCH NEEDS. `mimic-medication-request` leaves
medication[x] as `CodeableConcept | Reference(MimicMedication)` — the only
medication profile in this IG that does not narrow it — and MIMIC's ETL puts a
prescription's drug, gsn, ndc and formulary_drug_cd on a shared Medication
resource, referenced (input/includes/map-mimic-hosp-meds.md; the IG's own
example instance uses medicationReference). The 2026-08-10 shape count settled the
proportion exactly: of 15,416,901 MedicationRequests, 13,533,220 (87.78%) take the
Reference branch and 1,883,681 (12.22%) carry an inline coding, with no resource
taking neither and none carrying text without a coding.

THIS IS THE LOAD-BEARING MAP FOR THE MEDICATION DOMAIN, and the resource-level
numbers say so. Following every reference and translating what it reaches:

    11,673,623 (75.72%) of prescriptions reach a Medication that has a code
     1,859,597 (12.06%) reach one with NO code, or no Medication at all — those
                        prescriptions have no drug code anywhere in the warehouse
       547,639 ( 3.55%) reach a code THIS map currently resolves

Combined with the inline branch, 14.33% of MIMIC prescriptions are translatable
today. The element-level figure the statistics report for
MedicationRequest.medication[x] is 88.19%, and both are correct: that one is over
the codings present on that element, this one is over prescriptions. The gap
between them is this element.

Almost all of it is ONE stream. Weighted by referring prescriptions, NDC carries
11,000,655 of them — 94.2% of the reference branch, 71.4% of every prescription
in MIMIC. It went unresolved until build_medication_ndc_table.py; see the NDC
note below for what that stream does and does not answer.

A consumer that dereferences medicationReference, reads Medication.code and calls
$translate is translating THIS element. Before this map existed it got nothing
back — not `unmatched`, nothing — because the only medication map was scoped to
MedicationRequest.medication[x] and, until this change, declared a shared
sourceCanonical it had no business answering for. That is what this file fixes.

WHY IT IS A SEPARATE MAP AND NOT A WIDENING OF THE OTHER ONE. $translate takes a
Coding; a Reference carries none, so nothing on medication[x] can be resolved
through the reference branch and no code reached through it belongs to that
element. One ConceptMap per bound element is the repo's rule, and the two
elements here really are different populations: MedicationRequest.medication[x]
records 2,888 drug names and 2 order flags, while this element is the drug
dictionary itself and is the only element anywhere in the inventory that can
carry the 5,733 `mimic-medication-ndc` codes.

Note also that the `required` binding on medication[x] is INERT on the Reference
branch — a validator has nothing coded to check. For the majority of MIMIC
prescriptions the terminology guarantee is carried entirely by THIS element's
binding, which makes this map the load-bearing one for the medication domain.

EVERY CODE THE BINDING ADMITS IS IN THIS MAP, all 20,288. Under a `required`
binding a conformant Medication may carry any of them, so anything less leaves a
consumer with silence for the difference. Where the answer is known it is
resolved; where it is not, the code is present as `unmatched` with a reason that
says WHICH KIND of gap it is:

    no-suitable-concept        a stream considered the code and declined it
    no-row-in-curated-table    the code is in a stream whose table was
                               generated for a SIBLING element's population and
                               has no row for it yet — a backlog, not a finding
    not-observed-in-data       used on NO bound element anywhere

`no-stream-yet` no longer appears on this element. It existed for exactly one
population, NDC, and that stream is built.

THE STREAMS ARE SHARED, NOT COPIES (lib/streams.py): one declaration per
source CodeSystem, one committed table per stream, one resolution consumed by
all three medication maps — so no two published maps can assert different
RxNorm concepts for the same MIMIC code. The 2026-08-10 counts measured 10,916
of the 20,288 admitted codes on this element, across three systems only
(mimic-medication-ndc 5,732, mimic-medication-name 4,696,
mimic-medication-formulary-drug-cd 488); mimic-medication-icu and
mimic-medication-poe-iv appear not at all, so the guess that `order_type`
IV/TPN events reach a Medication through poe was wrong — they stay inline on
the sibling elements. Those per-element facts live in the statistics
(output/stream-report.json and occurrence-buckets.csv); they no longer change
what this map contains.

THE TABLES ARE THE SIBLING FIELDS', NOT COPIES. Three of the five populations
already have committed tables generated for MedicationRequest.medication[x] and
MedicationAdministration.medication[x], and they are declared here unchanged:
one per-code answer, one place to change it, and no way for two published maps to
assert different RxNorm concepts for the same MIMIC drug code. That is what
lib/curated.py's shared-table support exists for, and it is why this map costs no
generation run for 14,555 of its codes.

NDC WAS THE ONE REAL GAP and is now the one model-free stream. 5,733 codes, no
code-search, no confidence threshold: an NDC is a package identifier rather than
a label, and RxNorm publishes the mapping as a property, so tier 1 asks that
property in reverse. Tier 2 joins the NDC's MIMIC label against the committed
drug-name table for what the release no longer carries — NDCs get retired and
repackaged, and MIMIC's span 2008-2019 while the pinned release is 20231106.

Two things that paragraph used to claim and should not. The lookup is
deterministic, but it is NOT complete: on an 80-code sample the property alone
answered 55, the label tier 52, and the two together 71 (88.8%), which is a good
stream and not a solved one. And it is not adjudication-free — where both tiers
answer they disagree by construction (package versus ingredient), and in a
handful of cases they disagree about the SUBSTANCE, which is a MIMIC data defect
this map has to take a position on. It takes one: the NDC wins. The argument,
the measured tier split and the worked Toujeo/Lantus case are all in
build_medication_ndc_table.py, which is where they belong.

Offline: reads the IG's own resources and the committed tables, writes four
files, touches no network.

Usage:
  uv run scripts/terminology-mapping/conceptmaps/build_medication_code_cm_vs.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from conceptmaps.lib.canonical import CANONICAL_BASE, MIMIC_BASE  # noqa: E402
from conceptmaps.lib.driver import run                            # noqa: E402
from conceptmaps.lib.streams import sources                       # noqa: E402

FIELD = "medication-code"

VERSION = "1.0.0"

# One declaration per stream, in lib/streams.py; this map only names
# which streams its facade ValueSet reaches. Order is group order.
SOURCES = sources(
    "medication-name",
    "formulary-drug",
    "medication-icu",
    "medication-poe-iv",
    "medication-ndc",
)

META = {
    "id": "mimic-medication-code-to-standard",
    "name": "MimicMedicationCodeToStandard",
    "title": "MIMIC Medication.code to RxNorm and SNOMED CT",
    "element": "Medication.code",
    # The element's own facade, NOT the shared `mimic-medication` union that is
    # bound on four elements. Identical membership, so nothing validates
    # differently; what it buys is that a $translate call naming this source
    # resolves to the map for the element the Coding actually came from. See
    # VS_MimicMedicationCode.fsh.
    "source_valueset": f"{MIMIC_BASE}/ValueSet/mimic-medication-code",
    "target_valueset": f"{CANONICAL_BASE}/ValueSet/mimic-medication-code-standard",
    "description": (
        "Maps the codes bound to Medication.code — MIMIC's drug dictionary — "
        "onto RxNorm, and onto SNOMED CT for the labels that name a drug class "
        "rather than a drug product. "
        "THIS IS THE MAP TO USE AFTER FOLLOWING A REFERENCE. "
        "MedicationRequest.medication[x] is a choice, and at least 87.8% of "
        "MIMIC MedicationRequests carry medicationReference rather than an "
        "inline CodeableConcept: their drug code is on the referenced "
        "Medication.code and is translated here, not by "
        "ConceptMap/mimic-medication-to-standard. "
        "SCOPE: every one of the 20,288 codes the binding admits has an entry. "
        "Where a target is known it is given; where it is not, the code is "
        "present as `unmatched` with a reason distinguishing a code that was "
        "considered and declined from one whose stream has no table row for it "
        "yet and one the warehouse never records on this element. A "
        "$translate for any code the binding admits therefore returns an "
        "answer rather than nothing. "
        "The per-code answers come from the same committed tables that serve "
        "MedicationRequest.medication[x] and "
        "MedicationAdministration.medication[x], so the three maps cannot "
        "assert different concepts for the same MIMIC code."),
    "purpose": (
        "One ConceptMap per bound element, so a consumer starting from "
        "Medication.code resolves exactly one map — and, for the majority of "
        "MIMIC prescriptions, so that there is a map to resolve at all. "
        "CONSUMERS MUST READ FIVE THINGS. "
        "First, every mapping here is `relatedto`, never `equivalent`: a MIMIC "
        "drug code and an RxNorm concept are related, and the direction is not "
        "something this repo establishes. Filtering on `equivalence = "
        "equivalent` drops this entire population. Test instead for a target "
        "code being PRESENT, and accept `relatedto`. "
        "Second, targets are deliberately mixed in granularity, because the "
        "source codes are: a label that states a strength gets a clinical-drug "
        "target and a bare ingredient name gets an ingredient target, since "
        "MIMIC records those as two different codes and collapsing them would "
        "destroy a distinction the source data carries. The target's own term "
        "type is the record of how specific the source code was. "
        "Third, an `unmatched` element is not all one thing. Read its comment: "
        "`no-suitable-concept` means a stream considered the code and no target "
        "exists, while `no-row-in-curated-table` means the code sits in a "
        "stream whose mapping table was generated for a sibling element and has "
        "no row for it yet — a backlog rather than a finding. "
        "Fourth, the NDC population is mapped by a route no other stream here "
        "uses, and its targets are more specific as a result. An NDC identifies "
        "a package, so RxNorm's own NDC property answers with the packaged "
        "product, brand included where the package is branded. Where that "
        "property has no answer — NDCs are retired and repackaged, and MIMIC's "
        "span 2008-2019 against a 20231106 release — the code falls back to the "
        "drug label MIMIC attached to it, which yields only an ingredient-level "
        "generalisation. Where the two routes disagreed the NDC was followed, "
        "including in a small number of cases where that means this map "
        "contradicts MIMIC's own drug name. "
        "Fifth, the statistics score each stream over the codes the "
        "warehouse actually uses ANYWHERE (see output/stream-report.json); "
        "the map itself answers for everything the binding admits."),
    "target_title": "MIMIC Medication.code as RxNorm and SNOMED CT",
    "target_description": (
        "The RxNorm and SNOMED CT concepts every mapped MIMIC drug code "
        "resolves to. Derived from ConceptMap/mimic-medication-code-to-standard, "
        "whose targetCanonical this is, so membership here and reachability by "
        "$translate are the same set. "
        "Two systems, because one does not suffice. RxNorm carries the drug "
        "products and is the target for all but a handful of codes; SNOMED CT "
        "substances cover the labels naming a drug CLASS, which RxNorm does not "
        "model — `Insulin` is the largest, and RxNorm 20231106 has 49 specific "
        "insulins and no generic ingredient for it — and the blood components "
        "recorded as ICU medication items, for which RxNorm has no concept at "
        "all. "
        "Neither include carries a version. This repo builds no RxNorm or "
        "SNOMED release, so pinning one would name something it cannot "
        "reproduce; the RxNorm release each table was generated against is "
        "recorded in the matching output/*-generation-log.json, where it is "
        "evidence rather than a promise. "
        "Note that several MIMIC codes legitimately share a member: MIMIC "
        "records case variants as distinct codes, so `LORazepam` and "
        "`Lorazepam` both resolve to RxCUI 6470 and cannot be told apart after "
        "translation. The same holds across CodeSystems here — a drug name and "
        "the formulary code for the same product resolve to one concept."),
    "cli_description": __doc__,
}


def main():
    return run(FIELD, SOURCES, META, VERSION)


if __name__ == "__main__":
    sys.exit(main())
