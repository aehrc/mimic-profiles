ValueSet: MimicMedicationDispenseMergedCode
Id: mimic-medication-dispense-merged-code
Title: "MIMIC MedicationDispense code (merged sub-types)"
Description: "Union of the per-sub-type MedicationDispense medication[x] / medication[x].coding binding ValueSets (ED, ICU), for use by MimicMedicationDispenseMerged. Grouping ValueSet — references only, no own codes. Not part of the upstream MIMIC IG."

* include codes from valueset $MimicMedicationCodes
* include codes from valueset $GSN_VS
