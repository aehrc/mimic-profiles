#!/usr/bin/env python3
"""Build the Quantity.code ConceptMap and its enumerated target ValueSet.

The ninth map, and the first whose target is a GRAMMAR rather than a code list.
UCUM has no concepts to look up: a target is an expression, and whether it is a
legal one is decided by parsing it. Three consequences run through everything
below — the generator needs no network, the gate is decidable rather than
probabilistic, and there is no release to pin.

WHY THIS FIELD AT ALL. `Quantity.unit` is a display string and nothing in FHIR
constrains it, which is the reason this population looks at first like something
a ConceptMap cannot serve. It is not: MIMIC's ETL writes the unit into
`Quantity.code` with `Quantity.system` naming `CodeSystem/mimic-units`, and the
IG's own examples say so —

    EX_MimicObservationLabevents.fsh:  * valueQuantity = 1.3 $MimicUnits#mg/dL "mg/dL"

so the source side is an ordinary coded element with an ordinary local system,
and `mimic-units` is an ordinary MIMIC CodeSystem of 505 concepts. What makes
the field unusual is only that its TARGET system is one this repo cannot
enumerate.

SOURCE AND TARGET ARE THE SAME COLUMN, which no other map here can say. Every
other map translates a code within one element — Condition.code to
Condition.code. This one does too: a consumer $translates `Quantity.code` and
writes the answer back to `Quantity.code`, changing only `Quantity.system` to
`http://unitsofmeasure.org`, and leaves `Quantity.unit` alone as the display it
always was. It is worth stating because a map whose subject is a unit LOOKS like
it ought to be reaching across into a value or a display, and the
Observation.component.code section of the README explains what that would cost.

NO IDENTITY GROUP OVER MIMIC-UNITS, AND NOT BECAUSE NOTHING IS ALREADY STANDARD.
87 of the 505 source strings already parse as valid UCUM, so on the usual test
this map would carry an identity group for them. It carries none, because an
identity mapping in this repo means the source and target SYSTEM are the same
and the code is therefore untouched — and for those 87 the system always
changes, from `mimic-units` to `unitsofmeasure.org`. `mg/dL` -> `mg/dL` is a
real translation that happens to leave the code string alone. Nothing in that
population may be omitted on the grounds that it needs no translation, and every
one of the 505 codes therefore has either a mapping or a declared `unmatched`.

THERE IS AN IDENTITY GROUP, AND IT IS A DIFFERENT POPULATION. The paragraph
above is about codes whose source system is mimic-units. Quantity.code has a
SECOND source system in the data, which nothing in this repo had enumerated
until 2026-08-20: where MIMIC's ETL had already normalised a unit it writes the
UCUM expression into Quantity.code and names `http://unitsofmeasure.org` in
Quantity.system, rather than writing the chart spelling under mimic-units. Those
Codings arrive already standard, their system does not change, and the identity
is therefore the correct answer rather than an omission — the same test the
paragraph above applies, reaching the opposite result because the premise
differs.

They were unreachable before. `mm[Hg]` and `[degF]` are TARGETS of this map and
not sources, so $translate on the BP components and on body temperature returned
no match while every check here stayed green — 5,180,814 occurrences with no
answer. `/min` and `%` did resolve, but only because they happen to be
mimic-units codes spelled identically to their own targets; that is a
coincidence, not a guarantee, and not one a consumer can see. All four are
declared, in the `units-ucum-native` stream.

The enumeration is MEASURED, from the units_ucum column of
valueshapes/observation-value-shapes.csv, which reads the DECLARED
Quantity.system rather than inferring from spelling — a distinction that matters
because the ETL writes the same string into `unit` and `code` in both cases, so
`%` under UCUM and `%` under mimic-units are identical on the page and opposite
in meaning. That measurement covers Observation.code and
Observation.component.code only. The medication dosage columns this map also
serves were not measured, so the UCUM side is complete for Observation and is a
FLOOR elsewhere; closing that means adding Quantity.code to
occurrences/elements.json and re-running the extraction.

EQUIVALENCE IS `equivalent`, WHICH NO OTHER TABLE-BACKED STREAM HERE CLAIMS.
lib/assemble.py sets `relatedto` for a curated table by default, because a
flowsheet label and a SNOMED concept are related in a direction this repo does
not establish. That argument does not reach this table: `mmHg` and `mm[Hg]` are
two spellings of one unit, and the relationship between them is the same KIND of
fact as the ICD dot insertion that has always been `equivalent` — a statement
about notation, checkable without judgement. The stream declares it (see the
`equivalence` key in lib/streams.py) so it stays a property of the resolver
rather than of a row.

The claim is defensible only because the rows that would break it are gated.
Nine mappings change what the source string DENOTES rather than how it is
written, and they are the reason the generator refuses to emit a row that
changes canonical dimension without a comment:

    K/uL  -> 10*3/uL   the source parses as KELVIN per microlitre
    m/uL  -> 10*6/uL   ... as METRES per microlitre
    EA    -> {each}    ... as the EXA-AMPERE
    N/A                ... as NEWTON PER AMPERE, and is therefore declined

Those are still `equivalent` to the unit MIMIC MEANT, which is what the map is
about; they are not equivalent to what the string literally says, and the
comment on each row is where that distinction lives. A consumer reading only the
equivalence will not see it — read the comment.

COVERAGE IS TWO POPULATIONS AND SHOULD NOT BE QUOTED AS ONE. About 92 of these
codes are the units MIMIC records on Observation.valueQuantity, carrying 182M
occurrences, and they map nearly completely because they are ordinary clinical
units with unambiguous UCUM equivalents. The other ~413 are medication dosage
strings, and roughly half of them are not units of measure at all — dose forms,
whole quantities written into the unit column, and ETL artefacts. A headline
percentage over the union describes neither. Take the numbers from the stream's
entry in output/stream-report.json, and read the tier split in
output/units-generation-log.json alongside it.

WHAT IS NOT WIRED UP YET, and it is not this script's to fix: no profile binds
`Quantity.code` to `mimic-units`. The CodeSystem and the ValueSet both exist and
the instances use them, but the only mention in input/fsh/ is the `$MimicUnits`
alias. The map is publishable regardless — its `sourceCanonical` names a
ValueSet the IG really has — but until an element binds it,
lib/streams.undeclared() cannot see the population, and this stream will not
appear in the occurrence buckets or in mapping-statistics.csv's used-in-data
columns. Adding the binding and an occurrences/elements.json entry is what wires
it into the coverage numbers; the stream declares `outside_occurrence_extract`
until then, so its codes are not reported as never-observed on the strength of
an artifact that never looked at them.

Offline: reads the IG's own CodeSystem and the committed table; touches no
network. Publish with upload.py.

Usage:
  uv run scripts/terminology-mapping/conceptmaps/build_units_cm_vs.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from conceptmaps.lib.canonical import CANONICAL_BASE, MIMIC_BASE  # noqa: E402
from conceptmaps.lib.driver import run                            # noqa: E402
from conceptmaps.lib.streams import sources                       # noqa: E402

FIELD = "units"

# This map's own version. See build_condition_cm_vs.py.
VERSION = "1.0.0"

SOURCES = sources("units", "units-ucum-native")

META = {
    "id": "mimic-units-to-ucum",
    "name": "MimicUnitsToUcum",
    "title": "MIMIC unit strings to UCUM",
    # Not Observation.valueQuantity: the same CodeSystem serves the medication
    # dosage columns, and naming one of the two elements would understate the
    # map by about 413 codes. Quantity.code is the FHIRPath both share.
    "element": "Quantity.code",
    # mimic-units NO LONGER SERVES, and this is the one thing the UCUM identity
    # group forces. That ValueSet is a bare compose over CodeSystem/mimic-units
    # and contains none of the four UCUM codes, so a map carrying them while
    # naming it would answer for a population its own sourceCanonical excludes —
    # the failure the README's medication and component sections describe, where
    # a consumer checks the map it projects through against the source value set
    # it expects that map to name, and the two disagree.
    #
    # So mimic-quantity-code is minted, in input/fsh/, as the union of the two
    # populations. Same shape as the mimic-medication-request-code facade and
    # for a related reason, but not the same reason: those disambiguate one
    # population across four elements, this unions two populations on one
    # element. It widens no binding — nothing binds Quantity.code at all (see
    # WHAT IS NOT WIRED UP YET below) — so no instance validates differently
    # than it did.
    "source_valueset": f"{MIMIC_BASE}/ValueSet/mimic-quantity-code",
    "target_valueset": f"{CANONICAL_BASE}/ValueSet/mimic-units-ucum",
    "description":
        "Maps the unit strings MIMIC records in Quantity.code onto UCUM "
        "expressions, so a consumer can translate every Quantity in the "
        "warehouse through a single ConceptMap and get a value it can convert, "
        "compare and plot. MIMIC writes its units under a local CodeSystem "
        "(mimic-units) rather than under UCUM: they are chart spellings — "
        "`mmHg`, `mEq/L`, `cmH2O`, `bpm` — and 418 of the 505 do not parse as "
        "UCUM at all. Source and target are the same element, so a consumer "
        "$translates Quantity.code, writes the answer back to Quantity.code "
        "and sets Quantity.system to http://unitsofmeasure.org, leaving "
        "Quantity.unit as the display it always was. There is no identity "
        "group: the system changes on every row, so even `mg/dL` -> `mg/dL` is "
        "a translation rather than a no-op, and no code is omitted on the "
        "grounds that it needs none. Every target is a parseable UCUM "
        "expression — the generator gates on that offline, so unlike this "
        "repo's other tables no row rests on a confidence score. Counted "
        "units keep their UCUM annotation, so `bpm` becomes `/min{beats}` and "
        "`insp/min` becomes `/min{insp}`; both canonicalise to `s-1` exactly "
        "as plain `/min` does, and the annotation is what keeps the two "
        "distinguishable after translation. A code this map does not resolve "
        "is declared as an unmatched element carrying its reason, never "
        "silently omitted.",
    "purpose":
        "Lets a consumer normalise every MIMIC Quantity to UCUM with one "
        "$translate. Read three things before relying on it. FIRST, a valid "
        "source string is not a correct one: nine mappings change what the "
        "value DENOTES, not merely how it is spelled, because the MIMIC string "
        "parses as UCUM and means something else — `K/uL` on platelet counts "
        "is KELVIN per microlitre, `m/uL` on red cell counts is METRES per "
        "microlitre, `EA` is the EXA-AMPERE, and `N/A` is NEWTON PER AMPERE "
        "and is declined for it. Each carries a comment saying so, and a "
        "consumer that re-derives units from the source strings rather than "
        "through this map will get those wrong. SECOND, equivalence here is "
        "'equivalent' rather than the 'relatedto' this repo's other curated "
        "tables use, because these rows restate a unit's notation rather than "
        "assert an undirected relationship between two concepts — so unlike "
        "the Specimen and Procedure maps, filtering on 'equivalent' keeps this "
        "field's mappings. THIRD, the source CodeSystem holds two populations: "
        "the units on Observation.valueQuantity, which map nearly completely, "
        "and the medication dosage strings, about half of which are not units "
        "of measure at all — dose forms, whole quantities written into the "
        "unit column, and ETL artefacts. Countable dose forms are mapped to "
        "the dimensionless UCUM annotation naming them (`tab` -> `{tablet}`), "
        "which is legal UCUM and dimensionless, so a consumer must not read "
        "one as a measured amount. The rest are declared unmatched with a "
        "reason, and several of those reasons name an ETL defect rather than a "
        "terminology gap: a unit column holding `(1,000 mg)` or "
        "`Units Insulin Glargine` is carrying a value or a product, and no "
        "ConceptMap can split that out.",
    "target_title": "MIMIC units as UCUM",
    "target_description":
        "The UCUM expressions every mapped MIMIC unit string resolves to. "
        "Derived from ConceptMap/mimic-units-to-ucum, whose targetCanonical "
        "this is, so membership here and reachability by $translate are the "
        "same set. Every member parses under ucumate, which the generator "
        "asserts on every row — this value set therefore contains no string "
        "that a UCUM implementation would reject, which is a stronger "
        "guarantee than this repo can make about any of its other target "
        "value sets, because it is decidable rather than gated against a "
        "server. The UCUM include carries no version: UCUM's identity is its "
        "grammar and a conformant expression parses the same under every "
        "release, so there is no release whose absence could change what "
        "`mm[Hg]` denotes. Note that several MIMIC strings legitimately share "
        "a member — `mmHg`, `mm Hg` and `mmHg.` all resolve to `mm[Hg]`, and "
        "the whole `tab`/`Tab`/`TAB`/`tablet`/`tablets`/`tabs` family to "
        "`{tablet}` — so the members here are far fewer than the mapped "
        "source codes, which is the normalisation the map exists to perform.",
    "cli_description": __doc__,
}


if __name__ == "__main__":
    sys.exit(run(FIELD, SOURCES, META, VERSION))
