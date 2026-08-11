#!/usr/bin/env python3
"""Build the MedicationDispense.medication[x] ConceptMap and its target ValueSet.

THE LARGEST CODED MEDICATION POPULATION IN THE WAREHOUSE, and until now the one
with no map. 14,240,367 codings on 14,275,819 resources — more than
MedicationRequest.medication[x] and MedicationAdministration.medication[x]
combined — and it is where nearly the whole drug-name CodeSystem is actually
used: 9,372 of the 9,971 `mimic-medication-name` codes appear here, against
2,888 on MedicationRequest. See issue #29.

THE ELEMENT SPANS TWO SUB-TYPES THAT BIND AT DIFFERENT DEPTHS, which is why it
needed a facade. `mimic-medication-dispense` binds the whole medication[x]
CodeableConcept to `mimic-medication` (the hosp prescriptions population), while
`mimic-medication-dispense-ed` binds medicationCodeableConcept.coding to
`mimic-medication-gsn` (the ED pyxis table). Neither is a superset of the other,
so there was no single sourceCanonical to declare — the same shape as
MedicationStatement.medication[x], and resolved the same way:
`mimic-medication-dispense-merged-code`, a grouping ValueSet in input/fsh/ whose
whole compose is the union of the two. It is never bound in place of the
sub-type bindings and must not be; what it buys is a canonical identity for the
element. See VS_MimicMedicationDispenseMerged.fsh.

Being FSH-authored, it reaches a server through the IG build and
scripts/publish-conformance.sh rather than through upload.py, and
verify_mappings check 6 reads it from fsh-generated/ — so a clean checkout needs
`sushi .` before `make mappings`.

EVERY CODE THE BINDING ADMITS IS IN THIS MAP, all 29,635 — the 20,288 of
`mimic-medication` plus the 9,347 of `mimic-medication-gsn`. Under a `required`
binding a conformant MedicationDispense may carry any of them, so anything less
leaves a consumer with silence for the difference. Where the answer is known it
is resolved; where it is not, the code is present as `unmatched` carrying which
KIND of gap it is:

    no-suitable-concept        a stream considered the code and declined it
    no-row-in-curated-table    the code sits in a stream whose table has no row
                               for it yet — a backlog, not a finding
    not-observed-in-data       used on NO bound element anywhere

WHAT THE DATA ACTUALLY CARRIES IS TWO OF THE SIX STREAMS, and the map covers all
six anyway. The 2026-08-10 counts measured `mimic-medication-name` (9,372 codes,
12,689,766 codings, 89.1%) and `mimic-medication-gsn` (704 codes, 1,550,601
codings, 10.9%) and NOTHING else — no NDC, no formulary code, no ICU item, no
POE flag ever appears on a dispense. Those four are still declared, because the
binding admits them and a consumer holding one gets a declared non-answer rather
than silence; they land in the worklist as `not-observed-in-data`, which is a
statement about the warehouse rather than about terminology. The per-element
facts live in the statistics (output/stream-report.json, occurrence-buckets.csv)
and do not change what this map contains.

Note the 35,452 resources with a CodeableConcept and no coding: ED pyxis rows
with no gsn, which `mimic-medication-dispense-ed` permits (`text` 1..1, `coding`
0..*). They are outside every coded population by construction, not a gap.

THE STREAMS AND THEIR TABLES ARE THE SIBLING FIELDS', NOT COPIES
(lib/streams.py). Five of the six populations already have committed tables
generated for MedicationRequest.medication[x], Medication.code and
MedicationAdministration.medication[x], and they are declared here unchanged:
one per-code answer, one place to change it, and no way for two published maps to
assert different RxNorm concepts for the same MIMIC drug code. That is what
lib/curated.py's shared-table support exists for, and it is why this map — the
biggest population in the inventory — costs exactly ONE new generation run.

THAT ONE RUN IS `medication-gsn`, and it is the reason this file can exist at
all. Before it, the 9,347 GSN codes belonged to no stream: they were the last
`no-stream-yet` population in the repo, so a map naming this element's facade as
its sourceCanonical would have failed verify check 6 with 9,347 codes absent —
the state build_medication_statement_cm_vs.py documented and lived with while
that stream was unbuilt. The stream is now declared with a committed table, so
both consuming maps answer for it, identically, from the same rows.

Offline: reads the IG's own resources and the committed tables, writes four
files, touches no network.

Usage:
  uv run scripts/terminology-mapping/conceptmaps/build_medication_dispense_cm_vs.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from conceptmaps.lib.canonical import CANONICAL_BASE, MIMIC_BASE  # noqa: E402
from conceptmaps.lib.driver import run                            # noqa: E402
from conceptmaps.lib.streams import sources                       # noqa: E402

FIELD = "medication-dispense"

VERSION = "1.0.0"

# One declaration per stream, in lib/streams.py; this map only names which
# streams its facade ValueSet reaches. Order is group order — the two
# populations the data actually carries first.
SOURCES = sources(
    "medication-name",
    "medication-gsn",
    "formulary-drug",
    "medication-icu",
    "medication-poe-iv",
    "medication-ndc",
)

META = {
    "id": "mimic-medication-dispense-to-standard",
    "name": "MimicMedicationDispenseToStandard",
    "title": "MIMIC MedicationDispense.medication[x] to RxNorm and SNOMED CT",
    "element": "MedicationDispense.medication[x]",
    # The element's own facade, unioning the two sub-type bindings that sit at
    # different depths. Not `mimic-medication` alone: that would classify the
    # 704 observed GSN codes as violations of a required binding, when each is
    # conformant to the ED profile that produced it. See
    # VS_MimicMedicationDispenseMerged.fsh.
    "source_valueset": (f"{MIMIC_BASE}/ValueSet/"
                        f"mimic-medication-dispense-merged-code"),
    "target_valueset": (f"{CANONICAL_BASE}/ValueSet/"
                        f"mimic-medication-dispense-standard"),
    "description": (
        "Maps the codes bound to MedicationDispense.medication[x] — MIMIC's "
        "hospital drug dispensations and the MIMIC-ED pyxis records — onto "
        "RxNorm, and onto SNOMED CT for the labels that name a drug class "
        "rather than a drug product. "
        "THIS IS THE LARGEST CODED MEDICATION POPULATION IN MIMIC: 14,240,367 "
        "codings, more than MedicationRequest.medication[x] and "
        "MedicationAdministration.medication[x] together, and the element where "
        "9,372 of the 9,971 MIMIC drug-name codes are actually used. "
        "SCOPE: every one of the 29,635 codes the binding admits has an entry — "
        "the 20,288 of mimic-medication plus the 9,347 FDB Generic Sequence "
        "Numbers of mimic-medication-gsn. Where a target is known it is given; "
        "where it is not, the code is present as `unmatched` with a reason "
        "distinguishing a code that was considered and declined from one whose "
        "stream has no table row for it yet and one the warehouse never records "
        "on any bound element. A $translate for any code the binding admits "
        "therefore returns an answer rather than nothing. "
        "Two of the six source systems carry all the data. mimic-medication-name "
        "accounts for 12,689,766 codings (89.1%) and mimic-medication-gsn for "
        "1,550,601 (10.9%); no NDC, formulary, ICU or POE code has ever been "
        "observed on a dispense, and those four populations are present here "
        "because the binding admits them, marked `not-observed-in-data`. "
        "The per-code answers come from the same committed tables that serve "
        "MedicationRequest.medication[x], Medication.code, "
        "MedicationAdministration.medication[x] and "
        "MedicationStatement.medication[x], so no two of the maps can assert "
        "different concepts for the same MIMIC code."),
    "purpose": (
        "One ConceptMap per bound element, so a consumer starting from "
        "MedicationDispense.medication[x] resolves exactly one map. "
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
        "Third, the GSN population — the ED pyxis codings — reads its targets "
        "from a table whose deterministic tier answers 61.4% of it by joining "
        "FDB drug names against RxNorm's own designations. Where a GSN display "
        "names a drug two ways, as `lamotrigine [Lamictal]`, it is mapped to the "
        "GENERIC it names first and not to the brand, and the table's "
        "`join_rung` column records which rung answered. GSN is also the one "
        "population here with no SNOMED CT target at all: a GSN code naming a "
        "drug class is declared unmapped rather than mapped into the substance "
        "hierarchy. "
        "Fourth, an `unmatched` element is not all one thing. Read its comment: "
        "`no-suitable-concept` means a stream considered the code and no "
        "target exists, `no-row-in-curated-table` means a backlog rather than a "
        "finding, and `not-observed-in-data` means the code is admitted by the "
        "binding but has never appeared on any bound element — which is true of "
        "every NDC, formulary, ICU and POE code on this element. "
        "Fifth, `IV therapy` and `TPN` are declined by decision, not by "
        "failure: they are POE order flags rather than substances, so no RxNorm "
        "concept exists for either, and a SNOMED procedure code would put a "
        "procedure in a column whose FHIRPath is medication[x]. That is a "
        "modelling defect one layer down, in the ETL — see issue #26. On this "
        "element they are also never observed."),
    "target_title": "MIMIC MedicationDispense.medication[x] as RxNorm and SNOMED CT",
    "target_description": (
        "The RxNorm and SNOMED CT concepts every mapped MIMIC dispense code "
        "resolves to. Derived from "
        "ConceptMap/mimic-medication-dispense-to-standard, whose targetCanonical "
        "this is, so membership here and reachability by $translate are the same "
        "set. "
        "Two systems, because one does not suffice. RxNorm carries the drug "
        "products and is the target for all but a handful of codes; SNOMED CT "
        "substances cover the labels naming a drug CLASS, which RxNorm does not "
        "model — `Insulin` is the largest, and RxNorm 20231106 has 49 specific "
        "insulins and no generic ingredient for it — and the blood components "
        "recorded as ICU medication items, for which RxNorm has no concept at "
        "all. The GSN population contributes RxNorm targets only. "
        "Neither include carries a version. This repo builds no RxNorm or "
        "SNOMED release, so pinning one would name something it cannot "
        "reproduce; the RxNorm release each table was generated against is "
        "recorded in the matching output/*-generation-log.json, where it is "
        "evidence rather than a promise. "
        "Note that several MIMIC codes legitimately share a member, and on this "
        "element more than on any other: MIMIC records case variants as "
        "distinct codes, so `LORazepam` and `Lorazepam` both resolve to RxCUI "
        "6470, and a drug name and the GSN for the same drug resolve to one "
        "concept across the two systems. Codes cannot be told apart after "
        "translation."),
    "cli_description": __doc__,
}


def main():
    return run(FIELD, SOURCES, META, VERSION)


if __name__ == "__main__":
    sys.exit(main())
