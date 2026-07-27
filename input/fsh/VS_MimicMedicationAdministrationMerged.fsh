ValueSet: MimicMedicationAdministrationMergedCode
Id: mimic-medication-administration-merged-code
Title: "MIMIC MedicationAdministration code (merged sub-types)"
Description: "Union of the per-sub-type MedicationAdministration.medication[x] binding ValueSets (ED, ICU), for use by MimicMedicationAdministrationMerged. Grouping ValueSet — references only, no own codes. Not part of the upstream MIMIC IG."

* include codes from valueset $MimicMedicationWithUnknown
* include codes from valueset $MimicMedicationCodes
