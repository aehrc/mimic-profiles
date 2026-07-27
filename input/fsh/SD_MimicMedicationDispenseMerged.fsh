Profile:        MimicMedicationDispenseMerged
Parent:         MedicationDispense
Id:             mimic-medication-dispense-merged
Title:          "MIMIC MedicationDispense (merged sub-types)"
Description:    "A facade profile for downstream pipelines that merge every MIMIC MedicationDispense sub-type (ED, ICU) into a single MedicationDispense resource, e.g. because a processing engine requires exactly one resource type per table. The sub-type profiles disagree on binding depth — mimic-medication-dispense binds the whole medication[x] CodeableConcept, mimic-medication-dispense-ed binds only medication[x].coding — so this facade narrows medication[x] to CodeableConcept and binds at the deeper .coding path, which is compatible with both. Binds to the union of all sub-type code ValueSets so a single fhirpath-driven code search can find codes across the merged data. This profile is not part of the upstream MIMIC IG and is not used by any example instance in this IG; it exists to give merged data a `meta.profile` that still resolves to exactly one bound ValueSet."

// binding to MIMIC terminology
* medication[x] only CodeableConcept
* medicationCodeableConcept.coding from MimicMedicationDispenseMergedCode
