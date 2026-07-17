// Instance
Instance:       ExampleMimicMedicationStatementED
InstanceOf:     MimicMedicationStatementED
Title:          "Example MedicationStatement resource MIMIC-ED"
Description:    "An example of how a MIMIC-ED MedicationStatement resource would look like."
Usage:          #example

// codes are real MIMIC-ED medrecon values; NDC chosen from the observed set so it
// also resolves on tx.fhir.org (most MIMIC NDCs are delisted and unknown to tx)
* medicationCodeableConcept.text = "Acetaminophen 325mg Tablet"
* medicationCodeableConcept.coding[gsnCode] = $GSN_CS#063395
* medicationCodeableConcept.coding[ndcCode] = $NDC#10135012301
* medicationCodeableConcept.coding[etccodeCode] = $ETC#00000577 "Analgesic or Antipyretic Non-Opioid"
* dateAsserted = 2177-02-13T03:31:00.000Z 
* subject = Reference(ExampleMimicPatientED)
* context = Reference(ExampleMimicEncounterED)