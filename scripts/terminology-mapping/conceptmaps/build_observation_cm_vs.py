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

from conceptmaps.lib.assemble import target                       # noqa: E402
from conceptmaps.lib.canonical import (CANONICAL_BASE, LOINC,     # noqa: E402
                                       MIMIC_BASE, SNOMED, TABLE_DIR)
from conceptmaps.lib.curated import MIXED_TARGET_COLUMNS          # noqa: E402
from conceptmaps.lib.driver import run                            # noqa: E402
from conceptmaps.lib.notation import no_dot                       # noqa: E402

FIELD = "observation"

# This map's own version. See build_condition_cm_vs.py.
VERSION = "1.0.0"

# One table per stream, each committed so the build stays offline and
# deterministic, each regenerated deliberately by its own `make` target.
MICRO_SUSC_TABLE = TABLE_DIR / "micro-susc-loinc.csv"
MICRO_TEST_TABLE = TABLE_DIR / "micro-test-loinc.csv"
OUTPUTEVENTS_TABLE = TABLE_DIR / "outputevents-loinc.csv"
DATETIMEEVENTS_TABLE = TABLE_DIR / "datetimeevents-snomed.csv"
MICRO_ORG_TABLE = TABLE_DIR / "micro-org-snomed.csv"
LABEVENTS_TABLE = TABLE_DIR / "labevents-loinc.csv"
# `-standard`, not `-loinc` or `-snomed`: the only MIXED-TARGET table here, so
# it names its target system per row instead of in its column headings.
CHARTEVENTS_TABLE = TABLE_DIR / "chartevents-standard.csv"

# No targetVersion on any entry — this repo builds no LOINC release, and pinning
# one it neither publishes nor controls is exactly the irreproducibility
# verify_mappings check 3 exists to catch. LOINC is on UNVERSIONED_SYSTEMS.
SOURCES = [
    {
        # mimic-observation-ed: triage acuity, chief complaint, pain, rhythm.
        "system": LOINC,
        "valueset_file": "ValueSet-mimic-observation-type-ed.json",
        "identity": True,
        "targets": [target(LOINC, no_dot)],
    },
    {
        # mimic-observation-vital-signs: the five panel-level vital codes.
        "system": LOINC,
        "valueset_file": "ValueSet-mimic-observation-type-vital.json",
        "identity": True,
        "targets": [target(LOINC, no_dot)],
    },
    {
        # mimic-observation-micro-susc: 27 antibiotics, where the code means
        # 'susceptibility to this drug' rather than the drug. No rule can
        # derive these — the displays are bare drug names, two of them
        # abbreviated — so the mapping is data; see build_micro_susc_table.py.
        #
        # `file`, not `valueset_file`: ValueSet-mimic-microbiology-antibiotic
        # is a bare compose with no enumerated concepts, so the CodeSystem is
        # the only enumeration there is.
        "system": f"{MIMIC_BASE}/CodeSystem/mimic-microbiology-antibiotic",
        "file": "CodeSystem-mimic-microbiology-antibiotic.json",
        "table": MICRO_SUSC_TABLE,
        # This table targets LOINC and says so in its own header.
        "table_columns": ("loinc_code", "loinc_display"),
        "targets": [target(LOINC, no_dot)],
    },
    {
        # mimic-outputevents-d-items: 77 ICU flowsheet items, every one of them
        # a volume of fluid out via one route. The label names the route's
        # device or site and leaves the measurement implicit — `Foley`,
        # `Jackson Pratt #1`, `T Tube`, `Lumbar` — so no rule can derive these
        # and the mapping is data; see build_outputevents_table.py.
        #
        # Same source CodeSystem as the procedureevents items in the Procedure
        # map, a different bound ValueSet: mimic-d-items partitions cleanly into
        # 188 datetimeevents + 77 outputevents + 169 procedureevents = 434, and
        # each population's table carries only its own rows.
        "system": f"{MIMIC_BASE}/CodeSystem/mimic-d-items",
        "valueset_file": "ValueSet-mimic-outputevents-d-items.json",
        "table": OUTPUTEVENTS_TABLE,
        # This table targets LOINC alone. The issue proposed a SNOMED fallback;
        # probing showed it rescues nothing this constraint declines, so the
        # table stays single-target — see the generator's docstring.
        "table_columns": ("loinc_code", "loinc_display"),
        "targets": [target(LOINC, no_dot)],
    },
    {
        # mimic-microbiology-test: 176 test names from
        # `microbiologyevents.test_name`. Note the code carries the TEST only —
        # the specimen is a separate MIMIC column and reaches FHIR as
        # Observation.specimen — so labels split between those that name their
        # specimen (`URINE CULTURE`) and those that deliberately do not
        # (`GRAM STAIN`), and LOINC's `… in Specimen` variants are the right
        # target for the second kind.
        #
        # Not a homogeneous population: BIDMC's cytogenetics lab shares the
        # microbiology results table, so ~28 of the 176 are karyotyping, FISH
        # and cell-culture items that LOINC files in MOLPATH and
        # PANEL.HL7.CYTOGEN rather than MICRO. build_micro_test_table.py
        # therefore searches two disjoint spaces per item and requires exactly
        # one to answer; one merged constraint answered the cytogenetic cell
        # cultures with bacterial cultures, which is a wrong answer no
        # downstream check can catch. Its docstring carries the evidence.
        #
        # `file`, not `valueset_file`: ValueSet-mimic-microbiology-test is a
        # bare compose with no enumerated concepts, so the CodeSystem is the
        # only enumeration there is — same as the antibiotics above.
        "system": f"{MIMIC_BASE}/CodeSystem/mimic-microbiology-test",
        "file": "CodeSystem-mimic-microbiology-test.json",
        "table": MICRO_TEST_TABLE,
        # Both passes target LOINC, so the table stays single-target and the
        # two-pass rule is entirely the generator's business.
        "table_columns": ("loinc_code", "loinc_display"),
        "targets": [target(LOINC, no_dot)],
    },
    {
        # mimic-datetimeevents-d-items: 188 ICU flowsheet items whose VALUE is a
        # dateTime, so the code has to name the thing whose date was recorded —
        # `224288 Arterial line Insertion Date` is an arterial catheterisation
        # that got written down, not a concept called "insertion date".
        #
        # The first stream in this map to target SNOMED CT rather than LOINC, and
        # the reason is that shape: SNOMED models the administrative dates (date
        # of birth, date of discharge) as observable entities, and the ICU line
        # and skin events as procedures, findings and events. So the constraint is
        # the procedureevents hierarchies plus `<<364713004 |Temporal
        # observable|`. See build_datetimeevents_table.py, which also records why
        # 45 of the 188 are unrepresentable in SNOMED at all — there is no
        # concept for changing a catheter cap — and why the expected coverage is
        # therefore nearer 40% than the 64% the procedureevents items scored.
        #
        # Third population off the same source CodeSystem as the procedureevents
        # and outputevents items: mimic-d-items partitions cleanly into 188
        # datetimeevents + 77 outputevents + 169 procedureevents = 434, and each
        # population's table carries only its own rows. This entry and the
        # outputevents one above therefore share a source system and differ in
        # target, which is two groups rather than one — a group is keyed by
        # (source system, target system, targetVersion).
        "system": f"{MIMIC_BASE}/CodeSystem/mimic-d-items",
        "valueset_file": "ValueSet-mimic-datetimeevents-d-items.json",
        "table": DATETIMEEVENTS_TABLE,
        # The only table in this map that targets SNOMED, so it keeps the default
        # column names rather than declaring LOINC ones.
        "table_columns": ("snomed_code", "snomed_display"),
        # No targetVersion: this repo builds no SNOMED release either, and SNOMED
        # has been on UNVERSIONED_SYSTEMS since the Procedure map.
        "targets": [target(SNOMED, no_dot)],
    },
    {
        # mimic-microbiology-organism: 646 organism names from
        # `microbiologyevents.org_name`. `Observation.value[x]` on
        # MimicObservationMicroOrg is a plain string, so it is the CODE that
        # names the organism identified, and the target is a SNOMED organism
        # TAXON rather than an observable or a laboratory test.
        #
        # Consumers must take that literally: `<<363787002 |Observable entity|`
        # is not a safe assumption about a target of this map. It is the caveat
        # the README already records for the ICU procedure population — a SNOMED
        # target is not necessarily a procedure — arriving from the other
        # direction, and it follows from the IG's modelling rather than from
        # anything the mapping chose.
        #
        # The first stream here sent with NO context template: 528 of the 646
        # labels are already exact taxonomic names, so the wrapper every previous
        # stream needed is not only unnecessary but harmful — all three
        # candidates answered a NEGATED label with the taxon it excludes. See
        # build_micro_org_table.py, which carries that evidence along with why
        # the constraint is `<<410607006 |Organism|` alone and why widening it to
        # include clinical findings was built, probed and dropped.
        #
        # `file`, not `valueset_file`: ValueSet-mimic-microbiology-organism is a
        # bare compose with no enumerated concepts, so the CodeSystem is the only
        # enumeration there is — same as the antibiotics and the test names.
        "system": f"{MIMIC_BASE}/CodeSystem/mimic-microbiology-organism",
        "file": "CodeSystem-mimic-microbiology-organism.json",
        "table": MICRO_ORG_TABLE,
        # The second table in this map to target SNOMED, so it keeps the default
        # column names rather than declaring LOINC ones. It shares a group with
        # the datetimeevents stream only if it shares a source system, which it
        # does not — different source CodeSystem, so a group of its own.
        "table_columns": ("snomed_code", "snomed_display"),
        "targets": [target(SNOMED, no_dot)],
    },
    {
        # mimic-d-labitems: 1,622 hospital laboratory analytes, the largest
        # population in this map and the fourth to target LOINC.
        #
        # The one structurally new thing about this stream is that the SEARCH
        # TEXT IS NOT THE LABEL. MIMIC keeps the specimen in its own `fluid`
        # column, and only 807 of the 1,622 analytes are blood — the rest are
        # urine, CSF, pleural, ascitic, synovial, stool and marrow. `fluid` is
        # the LOINC System axis, so a search on the bare label asks a question
        # with no specimen in it and gets serum or plasma back by default:
        # `Potassium` filed under Other Body Fluid answers with a BLOOD code,
        # and `(Albumin)` under Pleural with a serum one. The generator
        # therefore joins MIMIC's own openly-downloadable dictionary and injects
        # the specimen into every query. See build_labevents_table.py, which
        # carries the measurement (specimen-correct System on the non-blood rows
        # goes 7/12 -> 11/12) and, more importantly, why `category` is NOT also
        # injected despite reaching 12/12: it makes the 52 `Delete` and `Voided
        # Specimen` rows answer with `24338-6 |Gas panel - Blood|` above
        # threshold and inside the constraint.
        #
        # Its docstring also records why the constraint stays
        # `CLASSTYPE=1,STATUS=ACTIVE` and is NOT widened with `CLASS=PULM` to
        # reach the blood-gas worksheet's respiratory tail: the widening rescues
        # one defensible mapping out of eleven and was measured changing the
        # answer for an ordinary chemistry analyte whose correct target involved
        # no PULM code at all. Membership is not answer stability.
        #
        # `file`, not `valueset_file`: ValueSet-mimic-d-labitems is a bare
        # compose with no enumerated concepts, so the CodeSystem is the only
        # enumeration there is — same as the antibiotics, the test names and the
        # organisms.
        "system": f"{MIMIC_BASE}/CodeSystem/mimic-d-labitems",
        "file": "CodeSystem-mimic-d-labitems.json",
        "table": LABEVENTS_TABLE,
        # Targets LOINC, so it declares the LOINC column names. It shares a
        # group with the other LOINC-targeting streams only if it shares a
        # source system, which it does not — its own CodeSystem, so its own
        # group.
        "table_columns": ("loinc_code", "loinc_display"),
        "targets": [target(LOINC, no_dot)],
    },
    {
        # mimic-chartevents-d-items: 2,982 ICU bedside flowsheet columns, the
        # largest population in this map and by some distance the largest coded
        # Observation population in the warehouse — 313.6M occurrences, 68% of
        # every occurrence of Observation.code.
        #
        # The one structurally new thing about this stream is that it is the
        # first MIXED-TARGET table: its rows name their own terminology, because
        # which one answers is a result of the search rather than a property of
        # the stream. The population is genuinely two things. The 160 `Labs`
        # items are bedside laboratory analytes whose LOINC targets are
        # Laboratory-class and which SNOMED cannot express at MIMIC's
        # granularity at all; the ~1,400 nursing-assessment items — skin and
        # wound detail, line sites, positioning, limb colour — are refused by
        # LOINC above threshold and answered correctly by SNOMED observable
        # entities. Neither terminology covers the population alone, which is
        # what makes the per-row `target_system` worth its machinery here where
        # the outputevents and labevents streams both probed a SNOMED second
        # opinion and rightly rejected it.
        #
        # So this ONE source contributes TWO groups, one per system it named — a
        # group is keyed by (source system, target system, targetVersion), and
        # lib/curated.py checks every row's system against the `targets` below
        # so a table cannot open a group into a terminology never declared here.
        #
        # See build_chartevents_table.py for the resolution rule (LOINC first,
        # SNOMED only where LOINC declined, never compared on confidence), for
        # why the SNOMED constraint is `<<363787002 |Observable entity|` alone
        # rather than the procedure/finding/event union the two ICU procedure
        # streams use, and for the 216 documentation, attestation and
        # alarm-limit items declined without being searched because no
        # constraint or threshold catches them.
        #
        # `file`, not `valueset_file`: ValueSet-mimic-chartevents-d-items is a
        # bare compose with no enumerated concepts, so the CodeSystem is the
        # only enumeration there is — same as the antibiotics, the test names,
        # the organisms and the lab analytes. Note this is its OWN CodeSystem
        # and not the `mimic-d-items` the three other ICU streams share.
        "system": f"{MIMIC_BASE}/CodeSystem/mimic-chartevents-d-items",
        "file": "CodeSystem-mimic-chartevents-d-items.json",
        "table": CHARTEVENTS_TABLE,
        # The mixed-target shape: `target_system` per row rather than a
        # system-named column pair. See lib/curated.py MIXED_TARGET_COLUMNS.
        "table_columns": MIXED_TARGET_COLUMNS,
        # Both systems declared, and load_table rejects a row naming anything
        # else. `targets[0]` is additionally the system an unmapped row is
        # reported against — LOINC, the space asked first.
        "targets": [target(LOINC, no_dot), target(SNOMED, no_dot)],
    },
]

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
