ValueSet: MimicQuantityCode
Id: mimic-quantity-code
Title: "MIMIC Quantity.code"
Description: "Every code MIMIC records in Quantity.code, across BOTH systems it writes there. The sourceCanonical of ConceptMap/mimic-units-to-ucum, and the enumeration its UCUM identity group is built from. Not part of the upstream MIMIC IG.

TWO POPULATIONS, because the ETL writes Quantity.system two ways and this is the only resource that says so. Usually it writes the raw chart spelling into Quantity.code and names CodeSystem/mimic-units — `mmHg`, `mEq/L`, `bpm` — which is the 505-code population mimic-units enumerates and the map's table group translates. But where the ETL had already normalised a unit it writes the UCUM expression into Quantity.code and names http://unitsofmeasure.org instead, and those codes are members of no MIMIC CodeSystem at all. They are not reachable through mimic-units, they are not spelling variants of anything in it, and before this ValueSet existed nothing in the IG enumerated them.

MEASURED, NOT ASSUMED. The four UCUM codes below are the complete set the 2026-08-20 full-warehouse run found on Observation.code and Observation.component.code, from the units_ucum column of valueshapes/observation-value-shapes.csv, which reads the DECLARED Quantity.system rather than guessing from the spelling. They carry 10,796,927 occurrences between them. Two of the four are unreachable without this: `mm[Hg]` (3,779,500 occurrences, both blood pressure components) and `[degF]` (1,401,314, body temperature) are targets of the map and not sources, so translating them returned no match. The other two resolve today only by coincidence — `/min` and `%` happen to be mimic-units codes spelled identically to their own targets — and they are enumerated here anyway, because a coincidence is not a guarantee and a consumer cannot see which of the four it is relying on.

SCOPE OF THE MEASUREMENT. Those two elements are the only ones the extraction covers. The same map also serves the medication dosage columns, where whether the ETL ever writes UCUM directly has not been measured — so this ValueSet is complete for Observation and is a floor, not a ceiling, everywhere else. Extending occurrences/elements.json and re-running the extraction is what would close that."

// The 505 MIMIC chart spellings, unchanged — a bare compose over
// CodeSystem/mimic-units, exactly as the upstream IG publishes it.
* include codes from valueset $MimicUnitsVS

// The UCUM codes the ETL writes into Quantity.code itself. Enumerated rather
// than composed as "all of UCUM": UCUM is a grammar with no concept list, so
// there is no set to include, and an unbounded include would assert this map
// answers for every legal UCUM expression when it answers for four.
* $UCUM#"mm[Hg]" "mm[Hg]"
* $UCUM#"[degF]" "[degF]"
* $UCUM#"/min" "/min"
* $UCUM#"%" "%"
