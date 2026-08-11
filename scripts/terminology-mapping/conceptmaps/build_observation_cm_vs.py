#!/usr/bin/env python3
"""Build the Observation.code ConceptMap and its enumerated target ValueSet.

Ten code populations across nine profiles, 5,729 codes, and — unlike Condition
and Procedure — almost none of them are a notation rule. The ICD maps reached
99.5% because dot insertion is spelling; here 5,720 of the 5,729 codes need a
semantic answer, so the honest coverage prior for this field is the one the ICU
`procedureevents` population actually scored, 64%, not 99%.

The populations are therefore added ONE STREAM AT A TIME, each with its own
committed table, its own generator target and its own search constraint (a
SNOMED ECL expression or a LOINC CLASSTYPE/STATUS filter). The constraint is
what carries the accuracy, not the confidence threshold: unconstrained, the
Procedure work had `Foley Catheter` return a *physical object* at confidence
1.0, and probing LOINC unconstrained answers `Sodium, Blood` with a LOINC Part.
The worst answers scored highest.

Present so far:

  identity  the 4 ED and 5 vital-signs codes, which are already LOINC and map to
            themselves. They exist here for the reason the Procedure map's two
            ED SNOMED codes do: a consumer cannot tell "already standard, needs
            no translation" from "missing from the map" — both return nothing
            from $translate — so the map has to say the first one out loud.

  table     the 27 microbiology antibiotics, constrained to LOINC's ABXBACT
            class with no laboratory method — see build_micro_susc_table.py.

  table     the 77 ICU outputevents items, constrained to LOINC's IO_OUT classes
            with PROPERTY = Vol — see build_outputevents_table.py.

  table     the 176 microbiology test names, the first stream searched against
            TWO disjoint constraints — LOINC's MICRO class and its cytogenetics
            classes — because BIDMC files karyotyping in the same results table.
            See build_micro_test_table.py.

  table     the 188 ICU datetimeevents items, the first stream in this map to
            target SNOMED CT rather than LOINC. Their VALUE is a dateTime, so the
            code names the thing whose date was recorded, and the constraint is
            the procedureevents hierarchies plus `<<364713004 |Temporal
            observable|` — SNOMED files date of birth and date of discharge there,
            and no procedure/finding/event constraint can reach them. Its coverage
            is the lowest in this map by some distance, and deliberately so: 45 of
            the 188 items have no SNOMED counterpart at all, because there is no
            concept for changing a catheter cap. See
            build_datetimeevents_table.py.

  table     the 646 microbiology organism names, the largest stream in this map
            so far and the first sent with NO context template. 528 of the 646
            labels are already exact taxonomic names, so the wrapper every
            earlier stream needed is harmful here: all three candidates answered
            a NEGATED label with the taxon it excludes. Constrained to
            `<<410607006 |Organism|` alone; widening it to reach the three
            result labels (`NO GROWTH`, `POSITIVE`, `NEGATIVE`) was built,
            probed and dropped because it broke three control rows and could not
            reach them anyway. Note the targets are organism TAXA, so no
            consumer may assume a target of this map is an observable entity.
            See build_micro_org_table.py.

  table     the 1,622 hospital laboratory analytes, the largest stream in this
            map and the first whose SEARCH TEXT IS NOT THE LABEL. Only 807 of
            them are blood, MIMIC keeps the specimen in a separate `fluid`
            column, and `fluid` is the LOINC System axis — so the generator
            joins MIMIC's own dictionary and injects the specimen into every
            query, without which all 815 non-blood analytes resolve against
            serum or plasma. `category` is deliberately NOT injected: it reaches
            a better System axis and makes the 52 `Delete` / `Voided Specimen`
            rows answer confidently with a blood-gas panel. Constrained to
            LOINC's `CLASSTYPE = 1` (Laboratory), active only, which is NOT
            widened to reach the blood-gas worksheet's respiratory tail — see
            build_labevents_table.py for the regression that rejected it, and
            for the one known defect (`50823 Required O2`) no setting can catch.

  table     the 2,982 ICU chartevents items, the largest stream in this map and
            the first MIXED-TARGET table in the repo: its rows name their own
            terminology, because the population is genuinely two things and
            neither LOINC nor SNOMED covers it alone. The 160 bedside laboratory
            analytes have Laboratory-class LOINC targets that SNOMED cannot
            express, and the ~1,400 nursing-assessment items are refused by
            LOINC and answered by SNOMED observable entities. One source, two
            groups. The issue proposed routing on `param_type`; that was
            dropped, because `param_type` describes the VALUE's datatype and not
            which terminology holds the concept — `GCS - Verbal Response` is
            `Text` and LOINC has it exactly, `Hemoglobin` is `Numeric` and
            SNOMED has nothing for it. Which space answers is the routing rule
            instead. See build_chartevents_table.py.

NOT IN THIS MAP: the blood-pressure component codes. They are bound to
`Observation.component.code`, a different FHIRPath expression over the same
resource and therefore a different column, and they have their own map — see
build_observation_component_cm_vs.py, which carries the full argument. The short
version: they cannot join MimicObservationMergedCode, because it is bound with
REQUIRED strength and admitting them would legalise
`code = 8480-6 |Systolic blood pressure|` on a merged Observation; and putting
them in this map anyway would leave it no correct `sourceCanonical` to declare
and would offer 8480-6 as a searchable value of a column that can never hold it.

So `sourceCanonical` below is exactly the value set bound to Observation.code on
the merged profile — nothing more, nothing less, and nothing this repo has to
mint.

Offline: reads only the IG's own resources; touches no network. Publish with
upload.py.

Usage:
  uv run scripts/terminology-mapping/conceptmaps/build_observation_cm_vs.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from conceptmaps.lib.canonical import CANONICAL_BASE, MIMIC_BASE  # noqa: E402
from conceptmaps.lib.driver import run                            # noqa: E402
from conceptmaps.lib.streams import sources                       # noqa: E402

FIELD = "observation"

# This map's own version. See build_condition_cm_vs.py.
VERSION = "1.0.0"

# One table per stream, each committed so the build stays offline and
# deterministic, each regenerated deliberately by its own `make` target.
# `-standard`, not `-loinc` or `-snomed`: the only MIXED-TARGET table here, so
# it names its target system per row instead of in its column headings.

# No targetVersion on any entry — this repo builds no LOINC release, and pinning
# one it neither publishes nor controls is exactly the irreproducibility
# verify_mappings check 3 exists to catch. LOINC is on UNVERSIONED_SYSTEMS.
# One declaration per stream, in lib/streams.py; this map only names
# which streams its facade ValueSet reaches. Order is group order.
SOURCES = sources(
    "observation-type-ed",
    "observation-type-vital",
    "micro-susc",
    "outputevents",
    "micro-test",
    "datetimeevents",
    "micro-org",
    "labevents",
    "chartevents",
)

META = {
    "id": "mimic-observation-merged-to-standard",
    "name": "MimicObservationMergedToStandard",
    "title": "MIMIC merged Observation codes to LOINC / SNOMED CT",
    "element": "Observation.code",
    # The MERGED bound value set, exactly. Observation.component.code has its
    # own binding and its own map.
    "source_valueset": f"{MIMIC_BASE}/ValueSet/mimic-observation-merged-code",
    "target_valueset": f"{CANONICAL_BASE}/ValueSet/mimic-observation-merged-standard",
    "description":
        "Maps the codes the merged MIMIC Observation profile admits on "
        "Observation.code onto standard terminology, so a consumer can "
        "translate the whole Observation.code column through a single "
        "ConceptMap. Codes that are already LOINC map to themselves, so "
        "translating the column preserves them instead of dropping them. "
        "Observation.component.code is NOT in scope here: it is a separate "
        "column with a separate binding, mapped by "
        "ConceptMap/mimic-observation-component-to-standard. All ten code "
        "populations are now present: the ED and vital-signs identity groups, "
        "the microbiology antibiotics, the microbiology test names, the ICU "
        "outputevents items, the ICU datetimeevents items, the microbiology "
        "organisms, the hospital laboratory analytes and the ICU chartevents "
        "items. Coverage is deliberately partial within them — a code this map "
        "does not resolve is declared as an unmatched element with a reason, "
        "never silently omitted.",
    "purpose":
        "Lets a consumer translate the merged Observation.code column with a "
        "single $translate. Two kinds of group. The ED and vital-signs codes are "
        "already LOINC and map to themselves, stated rather than omitted because "
        "a consumer cannot otherwise tell a code that needs no translation from "
        "one the map is missing — $translate returns nothing in both cases. They "
        "are coded 'equivalent' rather than 'equal', matching the other maps, "
        "because consumers that pin the equivalence they accept filter 'equal' "
        "out. The microbiology antibiotics, the microbiology test names, the ICU "
        "outputevents items, the ICU datetimeevents items, the microbiology "
        "organisms, the hospital laboratory analytes and the ICU chartevents "
        "items come from generated "
        "tables and are 'relatedto': a MIMIC susceptibility code and a LOINC "
        "susceptibility code are related, as are a MIMIC microbiology test name "
        "and a LOINC lab code, an ICU flowsheet output route and a LOINC "
        "fluid-output volume, an ICU flowsheet timestamp column and the "
        "SNOMED CT procedure, finding or temporal observable whose date it "
        "records, a MIMIC organism name and the SNOMED CT taxon it names, a "
        "MIMIC lab analyte and the LOINC laboratory code for that analyte in "
        "that specimen, and an ICU bedside flowsheet column and the LOINC or "
        "SNOMED CT concept naming what it records, "
        "and no direction between them is asserted. Consumers must "
        "accept 'relatedto' as well as 'equivalent' or they will drop those "
        "populations. Note that a target here may be SNOMED CT as well as LOINC: "
        "the datetimeevents and microbiology organism items map to SNOMED, and "
        "the ICU chartevents items map to WHICHEVER of the two carries the "
        "concept, so a consumer cannot assume one target system for this column "
        "and cannot assume one even within a single source population. Nor may "
        "a consumer assume what KIND of "
        "concept a target is: the microbiology organism stream maps to SNOMED CT "
        "organism taxa, which are not observable entities, because MIMIC records "
        "the organism identified in Observation.code itself.",
    "target_title": "MIMIC merged Observation codes as standard terminology",
    "target_description":
        "Every code the merged MIMIC Observation profile admits on "
        "Observation.code, in standard terminology. Derived from "
        "ConceptMap/mimic-observation-merged-to-standard, whose targetCanonical "
        "this is, so membership here and reachability by $translate are the same "
        "set. Neither the LOINC nor the SNOMED CT include carries a version: this "
        "repo builds no LOINC or SNOMED release, so pinning one would name "
        "something it cannot reproduce. Grows as each code-search stream is added "
        "to the map.",
    "cli_description": __doc__,
}


if __name__ == "__main__":
    sys.exit(run(FIELD, SOURCES, META, VERSION))
