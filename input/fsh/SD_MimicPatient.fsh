Profile:        MimicPatient
Parent:         us-core-patient
Id:             mimic-patient
Title:          "MIMIC Patient"
Description:    "A MIMIC patient based on US Core Patient."

// cardinalities of used elements
* gender 1..1
* name 1..*
* identifier 1..1
* maritalStatus 0..1
* birthDate 1..1
* deceasedDateTime 0..1
* communication 0..*
* managingOrganization 0..1


// binding to MIMIC terminology
* identifier.system = $IdentifierPatient
