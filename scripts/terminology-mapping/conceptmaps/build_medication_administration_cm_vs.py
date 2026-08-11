#!/usr/bin/env python3
"""Build the MedicationAdministration.medication[x] ConceptMap and target ValueSet.

The seventh bound element, the last one in issue #18 with nothing built, and the
largest remaining by data volume: 6,135 distinct codes carrying 36,733,071
occurrences — twenty times the sibling MedicationRequest field and second only to
Observation.code. Declaration only: everything that computes lives in lib/, and
the per-code answers live in the committed tables. See the field's issue (#27 in
fhnaumann/master_thesis_pipeline) for the evidence behind every setting here.

WHY A SEPARATE MAP FROM MedicationRequest.medication[x]. Same argument as
Observation.component.code: these are different FHIRPath expressions, so a
consumer projects them as two columns and injects one $translate per column,
stating per column the map it projects through AND the source value set it
expects that map to name. The two bindings are genuinely different sets —
MedicationAdministration is bound to mimic-medication-administration-merged-code,
which adds v3-NullFlavor#UNK on top of mimic-medication — so one map spanning
both would have no correct `sourceCanonical` to declare.

They are also different POPULATIONS of the same union, which is the part that is
easy to miss. mimic-medication admits five CodeSystems because it serves several
medication columns, and the warehouse splits them almost disjointly: the
prescription drug names dominate MedicationRequest, while the pharmacy formulary
codes and the ICU flowsheet labels appear only here. Mapping one element would
have said nothing about the other.

ALL FIVE STREAMS ARE PRESENT, added one at a time in the order issue #27
records:

    v3-NullFlavor                          1 code,        931 occ, identity
    mimic-medication-poe-iv                2 codes,   186,248 occ, declared unmapped
    mimic-medication-name              3,620 codes, 1,254,612 occ, shared table
    mimic-medication-formulary-drug-cd 2,188 codes, 26,312,387 occ, own table
    mimic-medication-icu                 324 codes,  8,978,893 occ, own table

Complete does not mean fully mapped, and on this element the difference is
large: the ICU stream declines about a fifth of its own occurrences BY DESIGN
because a fifth of what MIMIC files under `medication[x]` there is not a drug.
Every one of those is a declared `unmatched` element with a reason.

TWO TABLES ARE SHARED WITH THE SIBLING FIELD, which is why this map costs far
less than its size suggests. `mimic-medication-poe-iv` is the same two codes on
both elements, so it added no rows at all. `mimic-medication-name` is bound to
both and observed as 2,888 codes there against 3,620 here, overlapping in 2,600:
one table over the union of 3,908, so the 2,600 shared codes cannot receive
different RxNorm concepts in the two published maps. A table is keyed on its
source CodeSystem rather than on the field that reads it precisely for this; see
lib/curated.py and lib/builders.py.

WHY `UNK` GETS AN IDENTITY GROUP rather than being declared unmapped. It is
tempting to read `UNK` as unmappable — RxNorm has no concept for an unknown
product, and SNOMED CT's unknown/unspecified concepts are qualifier values that
would put a qualifier in a column whose FHIRPath is `medication[x]`. But that
asks the wrong question. `UNK` is not a MIMIC-local code awaiting a standard
counterpart: it is HL7 v3 NullFlavor, published by THO, resolvable on the
terminology server, and already the standard way to say "this is not known".
The question an identity group answers is "does this code need translating?",
and the answer is no.

This is the same argument the Procedure map makes for its two ED SNOMED codes
and the Observation map for its nine LOINC ones. "Needs no translation" and "is
missing from the map" are indistinguishable to a consumer — $translate returns
nothing in both cases — so the identity group is what makes the first one say so
out loud. Declaring it `unmatched` instead would be strictly worse for the data:
a consumer correctly dropping codeless Codings would turn 931 explicit "the drug
is unknown" records into 931 empty cells, losing the distinction between a
recorded unknown and a row the map never considered.

No targetVersion, and v3-NullFlavor is therefore on UNVERSIONED_SYSTEMS: this
repo builds no THO release and pinning one it neither publishes nor controls is
what verify_mappings check 3 exists to catch.

STREAMS, DECLARED ONCE. Every source CodeSystem here is a stream in
lib/streams.py, resolved identically for this map and both sibling medication
maps, so no two published maps can assert different concepts for one MIMIC
code. Table generation is still narrowed — to the codes the warehouse uses on
ANY bound element (lib/builders.table_population) — so never-used labels cost
no model calls; they stay in the map as `unmatched` with reason
`not-observed-in-data`, and codes used somewhere without a table row yet are
`no-row-in-curated-table`. Per-element usage lives in the statistics
(output/stream-report.json), not in the map's content.

TARGETS ARE RxNorm AND SNOMED CT for the four MIMIC-local streams, the pair #25
settled on. RxNorm carries the drug products; SNOMED CT answers only the labels
naming a drug CLASS, and only inside `<<105590001 |Substance|`. Substances
emphatically, never procedures: a procedure concept in a column whose FHIRPath is
`medication[x]` resolves correctly and makes the data mean something else.

EQUIVALENCE is not this file's concern; the resolver fixes it in lib/assemble.py.
The one identity mapping is `equivalent`, which is a fact about the same code
twice. Every mapping the four MIMIC-local streams supply will be `relatedto`,
so a consumer filtering on `equivalence = equivalent` keeps only the null
flavour and drops every drug in the field.

Offline: reads the IG's own resources and the committed tables, writes four
files, touches no network.

Usage:
  uv run scripts/terminology-mapping/conceptmaps/build_medication_administration_cm_vs.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from conceptmaps.lib.canonical import CANONICAL_BASE, MIMIC_BASE  # noqa: E402
from conceptmaps.lib.driver import run                            # noqa: E402
from conceptmaps.lib.streams import sources                       # noqa: E402

FIELD = "medication-administration"

VERSION = "1.0.0"

# One declaration per stream, in lib/streams.py; this map only names
# which streams its facade ValueSet reaches. Order is group order.
SOURCES = sources(
    "medication-with-unknown",
    "medication-poe-iv",
    "medication-name",
    "formulary-drug",
    "medication-icu",
    "medication-ndc",
)

META = {
    "id": "mimic-medication-administration-to-standard",
    "name": "MimicMedicationAdministrationToStandard",
    "title": "MIMIC MedicationAdministration.medication[x] to RxNorm and SNOMED CT",
    "element": "MedicationAdministration.medication[x]",
    # The merged bound value set, exactly. MedicationRequest.medication[x] has
    # its own binding and its own map; this repo mints no new source canonical.
    "source_valueset":
        f"{MIMIC_BASE}/ValueSet/mimic-medication-administration-merged-code",
    "target_valueset":
        f"{CANONICAL_BASE}/ValueSet/mimic-medication-administration-standard",
    "description": (
        "Maps the codes the merged MIMIC MedicationAdministration profile "
        "admits on MedicationAdministration.medication[x] onto standard "
        "terminology, so a consumer can translate the whole column through a "
        "single ConceptMap. RxNorm carries the drug products; SNOMED CT "
        "substances answer the labels that name a drug class rather than a "
        "product. "
        "SEPARATE FROM ConceptMap/mimic-medication-to-standard, which maps "
        "MedicationRequest.medication[x]. The two elements are different "
        "columns with different bindings — this one additionally admits "
        "v3-NullFlavor UNK — and the warehouse fills them from almost "
        "disjoint code populations, so neither map describes the other. "
        "SCOPE: every code the binding admits has an entry, with the "
        "answers shared stream-for-stream with the two sibling medication "
        "maps (see lib/streams.py). The bound ValueSet admits 20,289 codes "
        "because it is a union serving several medication columns; a code "
        "with no answer is present as `unmatched` with a reason, so a "
        "consumer that meets one is told why rather than getting no "
        "answer. "
        "ALL FIVE CODE POPULATIONS ARE PRESENT: the v3-NullFlavor code, the two "
        "POE order flags, the MIMIC drug names, the pharmacy formulary codes "
        "and the ICU flowsheet items. Complete is not the same as fully "
        "mapped, and the gap is concentrated rather than spread: about a fifth "
        "of the ICU stream's volume is route, container and intake-category "
        "labels that are not drugs at all, and a further 190,000 occurrences "
        "are branded enteral tube feeds for which RxNorm holds no concept at "
        "any term type. A code this map does not resolve is declared as an "
        "unmatched element with a reason, never silently omitted."),
    "purpose": (
        "Lets a consumer translate the MedicationAdministration.medication[x] "
        "column with a single $translate, the same way it translates "
        "MedicationRequest.medication[x] through that element's own map. "
        "CONSUMERS MUST READ THREE THINGS. "
        "First, apart from the single v3-NullFlavor identity mapping, every "
        "mapping here comes from a generated table and is `relatedto`: not one "
        "MIMIC drug code in this population is already standard terminology. A "
        "MIMIC pharmacy formulary code and an RxNorm concept are related, and "
        "the direction is not something this repo establishes. Filtering on "
        "`equivalence = equivalent` therefore keeps only the null flavour and "
        "drops every drug in the field. Test instead for a target code being "
        "PRESENT, and accept `relatedto`. "
        "Second, targets are deliberately mixed in granularity and mixed in "
        "system. The search is not constrained to one RxNorm term type, so a "
        "label stating a strength gets a clinical-drug target while a bare "
        "ingredient name gets an ingredient target — MIMIC records those as "
        "different codes and collapsing them would destroy a distinction the "
        "source data carries. A target may equally be a SNOMED CT substance, "
        "for the labels naming a drug class RxNorm does not model as a "
        "concept. "
        "Third, a target here is not always a medication concept, and the "
        "v3-NullFlavor code is why. `UNK` records that the administered drug "
        "is not known, and it maps to itself so that translating the column "
        "preserves that statement instead of emptying the cell. A consumer "
        "that assumes every target is an RxNorm or SNOMED CT concept will be "
        "wrong for those 931 rows; check the target's own system rather than "
        "the field it was mapped from. Beyond it, a substantial share of this "
        "element's volume has no target and never will, and each such code is "
        "declared `unmatched` with its reason rather than mapped to something "
        "that would read correctly and mean something else."),
    "target_title":
        "MIMIC MedicationAdministration medications as RxNorm and SNOMED CT",
    "target_description": (
        "The RxNorm and SNOMED CT concepts every mapped MIMIC "
        "MedicationAdministration code resolves to. Derived from "
        "ConceptMap/mimic-medication-administration-to-standard, whose "
        "targetCanonical this is, so membership here and reachability by "
        "$translate are the same set. "
        "Three systems, because one does not suffice: RxNorm carries the drug "
        "products and is the target for nearly every code, SNOMED CT "
        "substances cover the labels naming a drug CLASS, which RxNorm does "
        "not model, and HL7 v3 NullFlavor carries `UNK` for the "
        "administrations whose drug was never known. That last one is a "
        "member because it is what the column holds and what translation "
        "returns, not because it is a medication — a consumer building a "
        "drug picker from this value set should exclude it, and a consumer "
        "reverse-translating a search must not be surprised by it. The SNOMED "
        "members are all inside `<<105590001 |Substance|` and in the "
        "international core, which is what keeps this value set resolvable on "
        "a server other than the one it was built against. "
        "No include carries a version. This repo builds no RxNorm, SNOMED or "
        "THO release, so pinning one would name something it cannot "
        "reproduce; the RxNorm release each table was generated against is "
        "recorded in that stream's generation log, where it is evidence "
        "rather than a promise. "
        "The SNOMED CT members are not all drug substances: the ICU stream "
        "contributes blood components — packed red cells, fresh frozen plasma, "
        "platelets, cryoprecipitate — because MIMIC records those on this "
        "element and RxNorm has no concept for them. A consumer that assumes "
        "every non-RxNorm member is a drug class will be wrong for those."),
    "cli_description": __doc__,
}


def main():
    return run(FIELD, SOURCES, META, VERSION)


if __name__ == "__main__":
    sys.exit(main())
