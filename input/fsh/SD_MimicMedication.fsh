Profile:        MimicMedication
Parent:         Medication
Id:             mimic-medication
Title:          "MIMIC Medication"
Description:    "A MIMIC medication profile based on the FHIR R4 medication resource."

// cardinalities of updated elements
* identifier 1..*

// cardinalities of used elements
* code 0..1

// bindings to MIMIC terminology
// For every MedicationRequest that uses medicationReference — the majority of
// MIMIC prescriptions — this is the ONLY binding that governs the drug code, as
// a required binding on a choice element cannot constrain its Reference branch.
// MimicMedicationCode has IDENTICAL membership to $MimicMedicationCodes; it
// exists so this element's ConceptMap has a sourceCanonical no other element
// shares. See VS_MimicMedicationCode.fsh.
* code from MimicMedicationCode
