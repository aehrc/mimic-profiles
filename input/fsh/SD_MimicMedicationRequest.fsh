Profile:        MimicMedicationRequest
Parent:         MedicationRequest
Id:             mimic-medication-request
Title:          "MIMIC Medication Request"
Description:    "A MIMIC medication request profile based on the FHIR R4 medication request resource."

// cardinalities of updated elements
* identifier 1..1
* authoredOn 1..1

// cardinalities of used elements
* status 1..1
* intent 1..1
* subject 1..1
* encounter 0..1
* medication[x] 1..1
* dosageInstruction.route 0..1
* dosageInstruction.doseAndRate 0..1
* dosageInstruction.timing 0..1
* dosageInstruction.maxDosePerPeriod 0..1
* dispenseRequest.validityPeriod 0..1

// identifier slicing
* identifier ^slicing.discriminator.type = #value
* identifier ^slicing.discriminator.path = "system"
* identifier ^slicing.rules = #open
* identifier ^slicing.description = "MedicationRequest identifier.system slicing"

* identifier contains
  PH_ID 0..1 
  and POE_ID 0..1
* identifier[PH_ID].system 1..1
* identifier[PH_ID].system = $IdentifierMedicationRequestPHID
* identifier[PH_ID].value ^short = "Medication request pharmacy_id identifier"
* identifier[PH_ID].value 1..1

* identifier[POE_ID].system 1..1
* identifier[POE_ID].system = $IdentifierMedicationRequestPOE
* identifier[POE_ID].value ^short = "Medication request POE identifier"
* identifier[POE_ID].value 1..1

// binding to MIMIC terminology
// medication[x] is left as CodeableConcept | Reference(MimicMedication) — the
// only medication profile here that does not narrow it — because MIMIC uses BOTH
// branches: the ETL puts prescriptions' drug/gsn/ndc/formulary_drug_cd on a
// shared Medication resource (see input/includes/map-mimic-hosp-meds.md) and the
// full-data extract still found 1,883,681 inline codings. Note that this binding
// governs the CodeableConcept branch ONLY: a required binding cannot constrain a
// Reference, so for the majority of requests the terminology guarantee is
// carried by MimicMedication.code's own binding instead.
// MimicMedicationRequestCode has IDENTICAL membership to $MimicMedicationCodes;
// it exists so this element's ConceptMap has a sourceCanonical no other element
// shares. See VS_MimicMedicationRequestCode.fsh.
* medication[x] from MimicMedicationRequestCode (required)
* dosageInstruction.timing.code from $MimicMedicationFrequency
* dosageInstruction.route from $MimicMedicationRoute

// referencing must be to MIMIC profiles
* subject only Reference(MimicPatient)
* encounter only Reference(MimicEncounter)