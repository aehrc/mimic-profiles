#!/usr/bin/env python3
"""Build the Specimen.type ConceptMap and its enumerated target ValueSet.

The fifth bound element to get a map, and the cheapest one left in the backlog:
116 codes across two MIMIC CodeSystems, carrying 14,963,903 occurrences — the
third-largest occurrence count of any bound element, larger than
`Condition.code`, `Procedure.code` and `Observation.component.code` combined.
One target system, one constraint, and no terminology that has to be loaded
first.

WHY SNOMED CT `<<123038009 |Specimen|`, AND WHY NOT THE R4 BINDING. FHIR R4
names HL7 v2 table 0487 on `Specimen.type`, at EXAMPLE strength, so declining it
is conformant. It was addressed rather than ignored, on two independent grounds
recorded in the field's issue: it is not on the terminology server this repo
targets, and it would not be the target even if it were — 315 terse uppercase
abbreviations with no code for `SWAB` (the most frequent microbiology specimen
label), none for `ASCITES`, `THROAT`, `ARTHROPOD` or `FOREIGN BODY`, and
deprecation notes carried inside display strings. LOINC's System-axis Parts were
rejected as ILLEGAL rather than merely unsuitable: a Part names the system some
measurement observed, not the identity of a specimen, and every Part hangs off
one synthetic flat root, so the hierarchy constraint that rescued the labevents
and micro-org streams is structurally unavailable there. OHDSI's Specimen domain
was rejected for the same reason issue #19 rejected its procedure crosswalk —
opaque OMOP concept_ids and duplicate displays cannot be reviewed from a CSV.

THE CONSTRAINT IS THE WHOLE METHOD HERE, more sharply than in any population
before it. Probing 24 labels unconstrained over all of SNOMED, only 2 of the 24
answers were legal `Specimen.type` codes; the rest were substances, procedures,
disorders, body structures, an organism, a morphologic abnormality, a physical
object and a unit of presentation. Eleven of the wrong answers scored exactly
1.00, against correct constrained answers at 0.85. Two rows should settle the
argument for good, because the wrong concept and the right concept carry the
SAME DISPLAY STRING:

    SWAB           1382308001 |Swab| (unit of presentation)
                   257261003  |Swab| (specimen)              <- the right one
    PLEURAL FLUID  2778004    |Pleural fluid| (substance)
                   418564007  |Pleural fluid specimen|       <- the right one

No reviewer reading the committed table or `unmapped-specimen.csv` would catch
that. It is the `Foley Catheter` lesson from the Procedure map and the
`Sodium, Blood` lesson from the Observation map arriving together: confidence
separates nothing, the constraint separates everything.

TWO SOURCE CODESYSTEMS, TWO `SOURCES` ENTRIES, TWO TABLES — forced by the
machinery rather than chosen. A source entry carries a single `system` and
assemble.build_groups buckets on it, and lib/curated.load_table validates every
row against THAT source's enumeration and is fatal on a row naming a code it
does not have, so one shared 116-row table would fail against both entries.
Two entries also means two ConceptMap GROUPS, because a group is keyed by
(source system, target system, targetVersion) and only the target half is
shared. That is the opposite of the two LOINC identity populations in the
Observation map, which merged into one group because they shared the SOURCE
system too.

BOTH STREAMS ARE PRESENT, so this map now considers every code its
`sourceCanonical` admits. Nothing here is absent-because-unbuilt any more: a
Specimen.type value that translates to nothing is a code this map considered and
declined, and its reason is in unmapped-specimen.csv.

  table     the 12 `mimic-lab-fluid` specimen names — the first population in
            this repo whose SOURCE CODES ARE THE LABELS THEMSELVES. Every stream
            before it keyed on an opaque id (ICU itemids, `d_labitems` itemids,
            the 90xxx microbiology codes), so load_curated's fatal display check
            has been comparing an id's label against the IG; here `mimic_code`
            and `mimic_display` are the same string, which makes that check
            degenerate but not wrong. See build_lab_fluid_table.py.

  table     the 104 `mimic-spec-type-desc` microbiology specimen descriptions.
            Same query setup as the stream above, deliberately: same constraint,
            same identity template, same threshold, because the two are the same
            bound element read off two MIMIC columns and a setting that differed
            between them would make their coverage incomparable for no stated
            reason. What is its own is the CASE-FOLDED FAMILY COLLAPSE — 104
            codes collapse to 93 labels, and MIMIC files 7 itemids as `SWAB` or
            `Swab` — and the fact that it needs NO pre-filter: the ~20 labels
            naming a laboratory TEST rather than a specimen are declined by the
            search itself, most of them returning no candidate at all. See
            build_spec_type_table.py, which also names the one known defect
            (`70024 VIRAL CULTURE: R/O CYTOMEGALOVIRUS`) and the sibling row that
            is one whitespace character away from being the same defect.

QUOTE CODE COVERAGE AND OCCURRENCE COVERAGE TOGETHER, or neither. The two diverge
sharply on this field and in the favourable direction for once: the labels that
have no target are overwhelmingly the rare ones, so a coverage figure over codes
understates how much of the DATA resolves and a figure over occurrences
overstates how much of the DICTIONARY was mapped. This is exactly what
output/occurrence-buckets.csv exists to expose. Take both numbers from the
stream's entry in output/stream-report.json and its row in
output/mapping-statistics.csv rather than from any prose — including this
docstring.

NO IDENTITY GROUPS AND NO NOTATION RULE. Not one MIMIC specimen code is already
SNOMED, and there is no dot to insert, so every mapping here is `relatedto`, set
by lib/assemble.py. A consumer filtering on `equivalence: equivalent` gets
NOTHING from this field at all — not a subset, nothing.

Offline: reads only the IG's own resources and the committed tables; touches no
network. Publish with upload.py.

Usage:
  uv run scripts/terminology-mapping/conceptmaps/build_specimen_cm_vs.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from conceptmaps.lib.canonical import CANONICAL_BASE, MIMIC_BASE  # noqa: E402
from conceptmaps.lib.driver import run                            # noqa: E402
from conceptmaps.lib.streams import sources                       # noqa: E402

FIELD = "specimen"

# This map's own version. See build_condition_cm_vs.py.
VERSION = "1.0.0"

# One table per stream, committed so the build stays offline and deterministic,
# each regenerated deliberately by its own `make` target.

# One declaration per stream, in lib/streams.py; this map only names
# which streams its facade ValueSet reaches. Order is group order.
SOURCES = sources(
    "lab-fluid",
    "spec-type",
)

META = {
    "id": "mimic-specimen-to-standard",
    "name": "MimicSpecimenToStandard",
    "title": "MIMIC Specimen types to SNOMED CT",
    "element": "Specimen.type",
    # The bound value set exactly as the IG already publishes it — a union of
    # mimic-lab-fluid and mimic-spec-type-desc. No new source canonical is
    # minted here.
    "source_valueset": f"{MIMIC_BASE}/ValueSet/mimic-specimen-type",
    "target_valueset": f"{CANONICAL_BASE}/ValueSet/mimic-specimen-standard",
    "description":
        "Maps the codes the MIMIC Specimen profile admits on Specimen.type onto "
        "SNOMED CT specimen concepts, so a consumer can translate the whole "
        "Specimen.type column through a single ConceptMap. Every target is drawn "
        "from `<<123038009 |Specimen|` and nowhere else: MIMIC's specimen labels "
        "name substances, body structures, disorders and physical objects when "
        "read literally, and an unconstrained search returns those confidently "
        "and at higher scores than the correct specimen concepts, so the "
        "hierarchy constraint rather than the confidence score is what makes a "
        "target of this map legal for the element. The FHIR R4 example binding "
        "to HL7 v2 table 0487 is deliberately not used — the binding is example "
        "strength, and that table has no code for the most frequent MIMIC "
        "specimen labels. Both source CodeSystems are present, so every one of "
        "the 116 codes this map's sourceCanonical admits has been considered. "
        "Coverage is deliberately partial nonetheless — about a fifth of the "
        "microbiology specimen descriptions name a laboratory TEST rather than "
        "a specimen, and Specimen.type cannot legally hold one — and a code "
        "this map does not resolve is declared as an unmatched element carrying "
        "its reason, never silently omitted.",
    "purpose":
        "Lets a consumer translate the Specimen.type column with a single "
        "$translate. Every mapping here is 'relatedto', because there is no "
        "identity group and no notation rule in this field: not one MIMIC "
        "specimen code is already SNOMED CT, and the relationship between a "
        "MIMIC collection label and a SNOMED specimen concept is one this repo "
        "does not establish a direction for. The consequence is stronger here "
        "than in the other maps and consumers must act on it — filtering on "
        "equivalence 'equivalent' returns NOTHING from this field, not a subset. "
        "Test for a present target code instead, and drop the 'unmatched' "
        "elements, which report 'considered, no target' by carrying a system and "
        "no code. Two further caveats. A target is a SPECIMEN, so a consumer "
        "must not read one as the substance or body site it names — "
        "119297000 |Blood specimen| is not 87612001 |Blood|, and the second is "
        "what an unconstrained search returns for the same label. And the map's "
        "groups now cover both of its source CodeSystems, so a Specimen.type "
        "value that translates to nothing is a code this map considered and "
        "declined rather than a population nobody has built — the reason is in "
        "unmapped-specimen.csv, and the commonest one by far is that the MIMIC "
        "label names a laboratory test rather than any material.",
    "target_title": "MIMIC Specimen types as SNOMED CT",
    "target_description":
        "The SNOMED CT specimen concepts every mapped MIMIC Specimen.type code "
        "resolves to. Derived from ConceptMap/mimic-specimen-to-standard, whose "
        "targetCanonical this is, so membership here and reachability by "
        "$translate are the same set. Every member is inside "
        "`<<123038009 |Specimen|` and in the SNOMED international core — the "
        "generator gates on both, which is what keeps this value set resolvable "
        "on a server other than the one it was built against. The SNOMED CT "
        "include carries no version: this repo builds no SNOMED release, so "
        "pinning one would name something it cannot reproduce. Note that "
        "several MIMIC codes legitimately share a member: SNOMED files no "
        "neonate-qualified or post-mortem-qualified blood-culture specimen, so "
        "three distinct MIMIC specimen types resolve to "
        "446131002 |Blood specimen obtained for blood culture| and cannot be "
        "told apart after translation.",
    "cli_description": __doc__,
}


if __name__ == "__main__":
    sys.exit(run(FIELD, SOURCES, META, VERSION))
