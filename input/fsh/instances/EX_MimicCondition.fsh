Instance: ExampleMimicCondition
InstanceOf: MimicCondition
Title: "Example Condition resource MIMIC-IV"
Description: "An example of how a MIMIC-IV Condition resource would look like."
Usage: #example

* code = $Icd10CM|2016#Z85.46 "Personal history of malignant neoplasm of prostate"
* subject = Reference(ExampleMimicPatient)
* encounter = Reference(ExampleMimicEncounter)