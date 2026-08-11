#!/usr/bin/env python3
"""Build the MedicationStatement.medication[x] ConceptMap and its target ValueSet.

The ED medication-reconciliation population, and the last bound element in
occurrences/elements.json to get a map at all. 2,586,657 coded resources,
8,143,620 codings. See issue #28.

THIS ELEMENT BINDS AT THE CODING SLICES, which is why it needed a facade before
it could have a map. `mimic-medication-statement-ed` slices
medicationCodeableConcept.coding on `system` and binds each slice separately —
`gsn` to mimic-medication-gsn (required), `etc` to mimic-medication-etc
(required) — and leaves the `ndc` slice deliberately unbound, because no
terminology server hosts http://hl7.org/fhir/sid/ndc
(scripts/binding-analysis/FINDINGS.md D3; note occurrences/elements.json cites
the same file by its short path). Two bound ValueSets on one element, and neither a superset of
the other, so there was no single sourceCanonical to declare and the repo's
one-map-per-element rule had no answer here.

`mimic-medication-statement-code` is that answer: a grouping ValueSet whose
whole compose is the union of the two slice bindings, minted in input/fsh/ for
the same reason mimic-medication-request-code and mimic-medication-code were —
canonical identity for an element, with membership that changes nothing. It is
never bound in place of the slice bindings and must not be: a slice-level
`required` binding validates each coding against its OWN system, while binding
this union at the CodeableConcept level would legalise a GSN code in the `etc`
slice. See VS_MimicMedicationStatementCode.fsh.

Being FSH-authored, it reaches a server through the IG build and
scripts/publish-conformance.sh rather than through upload.py, and
verify_mappings check 5 reads it from fsh-generated/ — so a clean checkout needs
`sushi .` before `make mappings`.

COMPLETE AGAINST BOTH BINDINGS AS OF THE `medication-gsn` STREAM. All 10,548
codes the two slice bindings admit have an entry here: the 1,201 `etc` codes and
the 9,347 `mimic-medication-gsn` ones. This file previously documented the map as
incomplete on purpose, because GSN had no stream — no constraint, no template, no
threshold — and this repo does not declare a resolver it has not built. It now
has one, with a committed table, so verify_mappings check 5 passes on this field
and a consumer holding any admitted code gets an answer or a declared
non-answer rather than silence.

Two alternatives were rejected while that gap was open, and they are recorded
because both would have made the check pass without answering anything. Narrowing
`sourceCanonical` to mimic-medication-etc alone would have described the map as
answering for half a column. Declaring a table-less `medication-gsn` stream so
its codes became `unmatched` with reason `no-row-in-curated-table` would have
asserted that a stream existed whose table had merely not caught up — false, and
it would have moved 9,347 codes out of the `no-stream-yet` bucket that was then
telling the truth about them. Building the stream is what closed it.

THE GSN STREAM IS SHARED WITH MedicationDispense.medication[x] (704 codes there,
the ED pyxis population; 9,178 here; union 9,347), so its table belongs to the
stream and both maps read the same rows. Its shape is unlike the `etc` one
below: GSN displays are drug NAMES, so 61.4% of the enumeration is settled by a
deterministic join against RxNorm's own designations with no model involved, and
only the residual is asked of code-search. It is also the one medication stream
with no SNOMED CT target at all — see build_medication_gsn_table.py.

THE ETC STREAM IS UNLIKE EVERY OTHER MEDICATION POPULATION HERE. FDB's Enhanced
Therapeutic Classification names a drug CLASS and never a product, so its target
is SNOMED CT alone: RxNorm publishes no class concepts at any term type, and
ATC — which would be the natural target — is hosted on no server this repo can
reach. It is the substance hierarchy rather than the medicinal-product one for a
measured reason: `<<763158003` contains no diuretic and no dihydropyridine
concept whatsoever, and those two families alone are 4.66% of this element's
occurrences. build_medication_etc_table.py carries the full evidence, including
the 57 source codes that are not medications at all.

Offline: reads the IG's own resources and the committed table, writes four
files, touches no network.

Usage:
  uv run scripts/terminology-mapping/conceptmaps/build_medication_statement_cm_vs.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from conceptmaps.lib.canonical import CANONICAL_BASE, MIMIC_BASE  # noqa: E402
from conceptmaps.lib.driver import run                            # noqa: E402
from conceptmaps.lib.streams import sources                       # noqa: E402

FIELD = "medication-statement"

VERSION = "1.0.0"

# One declaration per stream, in lib/streams.py; this map only names which
# streams its facade ValueSet reaches. Order is group order — one per coding
# slice of the source CodeableConcept.
SOURCES = sources(
    "medication-gsn",
    "medication-etc",
)

META = {
    "id": "mimic-medication-statement-to-standard",
    "name": "MimicMedicationStatementToStandard",
    "title": ("MIMIC MedicationStatement.medication[x] to RxNorm and "
              "SNOMED CT"),
    "element": "MedicationStatement.medication[x]",
    # The element's own facade, unioning the two coding-slice bindings. Not
    # either slice ValueSet alone: a map naming one of them would describe
    # itself as answering for half the column. See
    # VS_MimicMedicationStatementCode.fsh.
    "source_valueset": f"{MIMIC_BASE}/ValueSet/mimic-medication-statement-code",
    "target_valueset": (f"{CANONICAL_BASE}/ValueSet/"
                        f"mimic-medication-statement-standard"),
    "description": (
        "Maps the codes bound to MedicationStatement.medication[x] — MIMIC-ED's "
        "medication-reconciliation records — onto RxNorm and SNOMED CT. "
        "SCOPE: every one of the 10,548 codes the element's two slice bindings "
        "admit has an entry. They are two quite different populations. The "
        "`gsn` coding slice carries 9,347 FDB Generic Sequence Numbers, which "
        "name a drug and map to RxNorm; the `etc` slice carries 1,201 FDB "
        "Enhanced Therapeutic Classification codes, which name a drug CLASS and "
        "map to SNOMED CT substances. Where a target is known it is given; where "
        "it is not, the code is present as `unmatched` carrying the reason it "
        "was declined, so a $translate for any admitted code returns an answer "
        "rather than nothing. "
        "A third system appears on this element and is absent from both "
        "bindings by decision: the `ndc` coding slice is left unbound because "
        "no terminology server hosts http://hl7.org/fhir/sid/ndc, so its "
        "9,312 codes (2,581,349 codings) are outside every bound enumeration "
        "on purpose and are not a mapping backlog. "
        "The GSN answers come from the same committed table that serves "
        "MedicationDispense.medication[x], so the two maps cannot assert "
        "different RxNorm concepts for the same GSN code."),
    "purpose": (
        "One ConceptMap per bound element, so a consumer starting from "
        "MedicationStatement.medication[x] resolves exactly one map. "
        "CONSUMERS MUST READ FIVE THINGS. "
        "First, WHICH SLICE A CODING CAME FROM DECIDES WHAT ITS TARGET MEANS, "
        "and the two are not interchangeable. A `gsn` coding names a drug, and "
        "its RxNorm target is that drug — at whatever specificity the FDB label "
        "stated, so a label carrying a strength reaches the clinical drug and a "
        "bare name reaches only the ingredient. An `etc` coding names a drug "
        "CLASS and never a product, so `00000224 ACE Inhibitors` resolves to a "
        "SNOMED CT concept meaning angiotensin-converting enzyme inhibitor as a "
        "substance class — it does not say which ACE inhibitor the patient was "
        "taking. The two codings sit on the SAME CodeableConcept and describe "
        "the same medication at two levels; reading the `etc` target as the drug "
        "is the mistake this element invites. "
        "Second, every mapping here is `relatedto`, never `equivalent`: a MIMIC "
        "code and an RxNorm or SNOMED CT concept are related, and the direction "
        "is not something this repo establishes. Filtering on `equivalence = "
        "equivalent` drops this entire population. Test instead for a target "
        "code being PRESENT, and accept `relatedto`. "
        "Third, a SNOMED CT target here is a SUBSTANCE, not a medicinal "
        "product, and that is deliberate rather than sloppy. SNOMED CT's "
        "product hierarchy does not carry these classes at all — it contains no "
        "diuretic and no dihydropyridine concept — while the substance "
        "hierarchy carries them exactly as FDB divides them. A consumer that "
        "assumes every SNOMED CT target is `<< 763158003 |Medicinal product|` "
        "will be wrong for every one of them. "
        "Fourth, the GSN population has no SNOMED CT target at all: where an "
        "RxNorm concept could not be reached, the code is declared unmapped "
        "rather than mapped into the substance hierarchy, which was measured to "
        "answer garbled FDB drug names with unrelated chemicals. So a GSN code "
        "naming a class resolves to nothing while the `etc` coding beside it "
        "resolves to that class — read them together. "
        "Fifth, 57 of the 1,201 `etc` source codes are not medications at all: FDB "
        "files devices, supplies and bulk chemicals in the same column "
        "(`Medical Supply, FDB Superset` alone carries 47,776 codings). They "
        "are declared unmapped rather than given the confident device concept a "
        "string match returns for them — with one known exception, "
        "`00001123 Chemicals - Solvents`, which maps to a laboratory reagent "
        "and should be dropped. See output/unmapped-medication-etc.csv."),
    "target_title": ("MIMIC MedicationStatement.medication[x] as RxNorm and "
                     "SNOMED CT"),
    "target_description": (
        "The RxNorm and SNOMED CT concepts every mapped MIMIC "
        "medication-reconciliation code resolves to. Derived from "
        "ConceptMap/mimic-medication-statement-to-standard, whose "
        "targetCanonical this is, so membership here and reachability by "
        "$translate are the same set. "
        "TWO SYSTEMS MEANING TWO DIFFERENT THINGS, because the element's two "
        "coding slices do. The RxNorm members are DRUGS, reached from the `gsn` "
        "slice, at mixed granularity — clinical drugs where the FDB label stated "
        "a strength, ingredients where it did not. The SNOMED CT members are "
        "SUBSTANCE concepts — drug CLASSES — reached from the `etc` slice, and "
        "not medicinal products: FDB therapeutic classes are what those source "
        "codes are, and SNOMED CT's product hierarchy does not model them. "
        "A drug picker must not be built from the SNOMED CT half: it names "
        "categories, and several MIMIC codes legitimately share a member where "
        "FDB draws a distinction SNOMED CT does not. "
        "Neither include carries a version. This repo builds no RxNorm or SNOMED "
        "CT release, so pinning one would name something it cannot reproduce; "
        "the release each table was generated against is recorded in "
        "output/medication-etc-generation-log.json and "
        "output/medication-gsn-generation-log.json, where it is evidence rather "
        "than a promise."),
    "cli_description": __doc__,
}


def main():
    return run(FIELD, SOURCES, META, VERSION)


if __name__ == "__main__":
    sys.exit(main())
