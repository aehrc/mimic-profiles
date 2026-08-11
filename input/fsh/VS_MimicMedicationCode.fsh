ValueSet: MimicMedicationCode
Id: mimic-medication-code
Title: "MIMIC Medication.code"
Description: "The codes bound on Medication.code. Grouping ValueSet — references mimic-medication and adds nothing, so MEMBERSHIP IS IDENTICAL and no instance that validated before validates differently now. It exists to give the element its own canonical identity, so that Medication.code has its own ConceptMap rather than sharing MedicationRequest's — see mimic-medication-request-code for the general argument. This element is the one that argument matters most for: MedicationRequest.medication[x] is a choice, most MIMIC prescriptions take its Reference branch, and a required binding CANNOT constrain a Reference — a validator has nothing coded to check. So for the majority of MIMIC prescriptions the drug code lives here and only this element's binding governs it. A consumer that dereferences medicationReference and translates the Coding it finds is translating Medication.code, and needs a map addressed to Medication.code. Not part of the upstream MIMIC IG."

* include codes from valueset $MimicMedicationCodes
