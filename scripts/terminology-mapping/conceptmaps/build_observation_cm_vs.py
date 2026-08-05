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

Still to come, in the order the issue sets: MicroOrg (646, SNOMED), Labevents
(1,622) and Chartevents (2,982), all LOINC-or-SNOMED code-search.

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
        "ConceptMap/mimic-observation-component-to-standard. INCOMPLETE: the "
        "code-search populations are being added one stream at a time. Present "
        "so far are the microbiology antibiotics, the microbiology test names, "
        "the ICU outputevents items and the ICU datetimeevents items; "
        "microbiology organisms, ICU chartevents and labevents are not in this "
        "map yet.",
    "purpose":
        "Lets a consumer translate the merged Observation.code column with a "
        "single $translate. Two kinds of group. The ED and vital-signs codes are "
        "already LOINC and map to themselves, stated rather than omitted because "
        "a consumer cannot otherwise tell a code that needs no translation from "
        "one the map is missing — $translate returns nothing in both cases. They "
        "are coded 'equivalent' rather than 'equal', matching the other maps, "
        "because consumers that pin the equivalence they accept filter 'equal' "
        "out. The microbiology antibiotics, the microbiology test names, the ICU "
        "outputevents items and the ICU datetimeevents items come from generated "
        "tables and are 'relatedto': a MIMIC susceptibility code and a LOINC "
        "susceptibility code are related, as are a MIMIC microbiology test name "
        "and a LOINC lab code, an ICU flowsheet output route and a LOINC "
        "fluid-output volume, and an ICU flowsheet timestamp column and the "
        "SNOMED CT procedure, finding or temporal observable whose date it "
        "records, and no direction between them is asserted. Consumers must "
        "accept 'relatedto' as well as 'equivalent' or they will drop those "
        "populations. Note that a target here may be SNOMED CT as well as LOINC: "
        "the datetimeevents items map to SNOMED, so a consumer cannot assume one "
        "target system for this column.",
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
