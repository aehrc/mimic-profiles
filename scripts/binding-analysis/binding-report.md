# Phase 2 / Step 3 - Binding Coverage Cross-Check

Offline coverage of observed MIMIC codes vs the IG's ValueSets (package.tgz). Stdlib-only, no terminology server.

Total candidate elements: 131 | ok (populated): 11 | no_data: 120 | errors: 0

## Summary

| Element | Profile | Verdict | Best VS | %dist | %rows | #missing |
|---|---|---|---|--:|--:|--:|
| Encounter.priority | mimic-encounter | external_terminology | - | - | - | 0 |
| Location.physicalType | mimic-location | external_terminology | - | - | - | 0 |
| MedicationAdministration.medication[x] | mimic-medication-administration | repair_candidate | mimic-medication | 100.0 | 100.00 | 1 |
| MedicationAdministration.medication[x] | mimic-medication-administration-icu | bind | mimic-medication | 100.0 | 100.00 | 0 |
| MedicationDispense.medication[x] | mimic-medication-dispense | bind | mimic-medication | 100.0 | 100.00 | 0 |
| MedicationRequest.medication[x] | mimic-medication-request | bind | mimic-medication | 100.0 | 100.00 | 0 |
| MedicationStatement.medication[x] | mimic-medication-statement-ed | no_binding | - | - | - | 0 |
| Observation.value[x] | mimic-observation-micro-susc | bind | mimic-micro-interpretation | 100.0 | 100.00 | 0 |
| Observation.value[x] | mimic-observation-micro-test | external_terminology | - | - | - | 0 |
| Observation.component.code | mimic-observation-vital-signs | no_binding | mimic-observation-type-ed | 0.0 | 0.00 | 2 |
| Organization.type | mimic-organization | external_terminology | - | - | - | 0 |

## Encounter.priority  (`mimic-encounter`)

- **Verdict:** `external_terminology`
- **Type:** CodeableConcept | distinct=4, rows=431231
- **Existing binding:** example / http://terminology.hl7.org/ValueSet/v3-ActPriority
- **Observed systems:** http://terminology.hl7.org/CodeSystem/v3-ActPriority
- **External (non-MIMIC) systems:** http://terminology.hl7.org/CodeSystem/v3-ActPriority
  - suggest for `http://terminology.hl7.org/CodeSystem/v3-ActPriority` -> `http://terminology.hl7.org/ValueSet/v3-ActPriority`

_No package ValueSet covers all observed systems._

## Location.physicalType  (`mimic-location`)

- **Verdict:** `external_terminology`
- **Type:** CodeableConcept | distinct=1, rows=39
- **Existing binding:** example / http://hl7.org/fhir/ValueSet/location-physical-type|4.0.1
- **Observed systems:** http://terminology.hl7.org/CodeSystem/location-physical-type
- **External (non-MIMIC) systems:** http://terminology.hl7.org/CodeSystem/location-physical-type
  - suggest for `http://terminology.hl7.org/CodeSystem/location-physical-type` -> `http://hl7.org/fhir/ValueSet/location-physical-type`

_No package ValueSet covers all observed systems._

## MedicationAdministration.medication[x]  (`mimic-medication-administration`)

- **Verdict:** `repair_candidate`
- **Type:** CodeableConcept | distinct=5811, rows=27754178
- **Existing binding:** example / http://hl7.org/fhir/ValueSet/medication-codes|4.0.1
- **Observed systems:** http://mimic.mit.edu/fhir/mimic/CodeSystem/mimic-medication-formulary-drug-cd, http://mimic.mit.edu/fhir/mimic/CodeSystem/mimic-medication-name, http://mimic.mit.edu/fhir/mimic/CodeSystem/mimic-medication-poe-iv, http://terminology.hl7.org/CodeSystem/v3-NullFlavor
- **External (non-MIMIC) systems:** http://terminology.hl7.org/CodeSystem/v3-NullFlavor
  - suggest for `http://terminology.hl7.org/CodeSystem/v3-NullFlavor` -> `http://terminology.hl7.org/ValueSet/v3-NullFlavor`

**Candidate ValueSets** (systems superset of observed):

| ValueSet | alias | %dist | %rows | dist cov | row cov | unknown | partial |
|---|---|--:|--:|--:|--:|--:|:-:|
| mimic-medication | $MimicMedicationCodes | 100.0 | 100.00 | 5810/5811 | 27753247/27754178 | 0 | no |

**Missing codes** (top 20 by n; full list in JSON):

| system | code | display | n |
|---|---|---|--:|
| v3-NullFlavor | UNK |  | 931 |

## MedicationAdministration.medication[x]  (`mimic-medication-administration-icu`)

- **Verdict:** `bind`
- **Type:** CodeableConcept | distinct=324, rows=8978893
- **Existing binding:** example / http://hl7.org/fhir/ValueSet/medication-codes|4.0.1
- **Observed systems:** http://mimic.mit.edu/fhir/mimic/CodeSystem/mimic-medication-icu
- **Recommended FSH:**
  ```fsh
  * medication[x] from $MimicMedicationCodes (required)
  ```

**Candidate ValueSets** (systems superset of observed):

| ValueSet | alias | %dist | %rows | dist cov | row cov | unknown | partial |
|---|---|--:|--:|--:|--:|--:|:-:|
| mimic-medication | $MimicMedicationCodes | 100.0 | 100.00 | 324/324 | 8978893/8978893 | 0 | no |

## MedicationDispense.medication[x]  (`mimic-medication-dispense`)

- **Verdict:** `bind`
- **Type:** CodeableConcept | distinct=9372, rows=12689766
- **Existing binding:** example / http://hl7.org/fhir/ValueSet/medication-codes|4.0.1
- **Observed systems:** http://mimic.mit.edu/fhir/mimic/CodeSystem/mimic-medication-name
- **Recommended FSH:**
  ```fsh
  * medication[x] from $MimicMedicationCodes (required)
  ```

**Candidate ValueSets** (systems superset of observed):

| ValueSet | alias | %dist | %rows | dist cov | row cov | unknown | partial |
|---|---|--:|--:|--:|--:|--:|:-:|
| mimic-medication | $MimicMedicationCodes | 100.0 | 100.00 | 9372/9372 | 12689766/12689766 | 0 | no |

## MedicationRequest.medication[x]  (`mimic-medication-request`)

- **Verdict:** `bind`
- **Type:** CodeableConcept | distinct=2890, rows=1883681
- **Existing binding:** example / http://hl7.org/fhir/ValueSet/medication-codes|4.0.1
- **Observed systems:** http://mimic.mit.edu/fhir/mimic/CodeSystem/mimic-medication-name, http://mimic.mit.edu/fhir/mimic/CodeSystem/mimic-medication-poe-iv
- **Recommended FSH:**
  ```fsh
  * medication[x] from $MimicMedicationCodes (required)
  ```

**Candidate ValueSets** (systems superset of observed):

| ValueSet | alias | %dist | %rows | dist cov | row cov | unknown | partial |
|---|---|--:|--:|--:|--:|--:|:-:|
| mimic-medication | $MimicMedicationCodes | 100.0 | 100.00 | 2890/2890 | 1883681/1883681 | 0 | no |

## MedicationStatement.medication[x]  (`mimic-medication-statement-ed`)

- **Verdict:** `no_binding`
- **Type:** CodeableConcept | distinct=19691, rows=8143620
- **Existing binding:** example / http://hl7.org/fhir/ValueSet/medication-codes|4.0.1
- **Observed systems:** http://hl7.org/fhir/sid/ndc, http://mimic.mit.edu/fhir/mimic/CodeSystem/mimic-medication-etc, http://mimic.mit.edu/fhir/mimic/CodeSystem/mimic-medication-gsn
- **External (non-MIMIC) systems:** http://hl7.org/fhir/sid/ndc

_No package ValueSet covers all observed systems._

## Observation.value[x]  (`mimic-observation-micro-susc`)

- **Verdict:** `bind`
- **Type:** CodeableConcept | distinct=4, rows=1107278
- **Observed systems:** http://terminology.hl7.org/CodeSystem/v3-ObservationInterpretation
- **External (non-MIMIC) systems:** http://terminology.hl7.org/CodeSystem/v3-ObservationInterpretation
  - suggest for `http://terminology.hl7.org/CodeSystem/v3-ObservationInterpretation` -> `http://hl7.org/fhir/ValueSet/observation-interpretation`
- **Recommended FSH:**
  ```fsh
  * value[x] from http://mimic.mit.edu/fhir/mimic/ValueSet/mimic-micro-interpretation (required)
  ```

**Candidate ValueSets** (systems superset of observed):

| ValueSet | alias | %dist | %rows | dist cov | row cov | unknown | partial |
|---|---|--:|--:|--:|--:|--:|:-:|
| mimic-micro-interpretation | - | 100.0 | 100.00 | 4/4 | 1107278/1107278 | 0 | no |
| mimic-lab-interpretation | - | 0.0 | 0.00 | 0/4 | 0/1107278 | 0 | no |

## Observation.value[x]  (`mimic-observation-micro-test`)

- **Verdict:** `external_terminology`
- **Type:** CodeableConcept | distinct=2, rows=132802
- **Observed systems:** http://terminology.hl7.org/CodeSystem/v3-NullFlavor
- **External (non-MIMIC) systems:** http://terminology.hl7.org/CodeSystem/v3-NullFlavor
  - suggest for `http://terminology.hl7.org/CodeSystem/v3-NullFlavor` -> `http://terminology.hl7.org/ValueSet/v3-NullFlavor`

_No package ValueSet covers all observed systems._

## Observation.component.code  (`mimic-observation-vital-signs`)

- **Verdict:** `no_binding`
- **Type:** CodeableConcept | distinct=2, rows=3979394
- **Existing binding:** example / http://hl7.org/fhir/ValueSet/observation-codes|4.0.1
- **Observed systems:** http://loinc.org
- **External (non-MIMIC) systems:** http://loinc.org
  - suggest for `http://loinc.org` -> `(LOINC - external; validate against terminology server)`

**Candidate ValueSets** (systems superset of observed):

| ValueSet | alias | %dist | %rows | dist cov | row cov | unknown | partial |
|---|---|--:|--:|--:|--:|--:|:-:|
| mimic-observation-type-ed | - | 0.0 | 0.00 | 0/2 | 0/3979394 | 0 | no |
| mimic-observation-type-vital | - | 0.0 | 0.00 | 0/2 | 0/3979394 | 0 | no |

**Missing codes** (top 20 by n; full list in JSON):

| system | code | display | n |
|---|---|---|--:|
| loinc.org | 8480-6 | Systolic blood pressure | 1989697 |
| loinc.org | 8462-4 | Diastolic blood pressure | 1989697 |

## Organization.type  (`mimic-organization`)

- **Verdict:** `external_terminology`
- **Type:** CodeableConcept | distinct=1, rows=1
- **Existing binding:** example / http://hl7.org/fhir/ValueSet/organization-type|4.0.1
- **Observed systems:** http://terminology.hl7.org/CodeSystem/organization-type
- **External (non-MIMIC) systems:** http://terminology.hl7.org/CodeSystem/organization-type
  - suggest for `http://terminology.hl7.org/CodeSystem/organization-type` -> `http://hl7.org/fhir/ValueSet/organization-type`

_No package ValueSet covers all observed systems._

## no_data elements (120)

These candidate elements had zero rows in MIMIC; carried forward as their own bucket.

- `Condition.bodySite` (mimic-condition)
- `Condition.stage.summary` (mimic-condition)
- `Condition.stage.type` (mimic-condition)
- `Condition.evidence.code` (mimic-condition)
- `Encounter.hospitalization.reAdmission` (mimic-encounter)
- `Encounter.hospitalization.dietPreference` (mimic-encounter)
- `Encounter.location.physicalType` (mimic-encounter)
- `Medication.form` (mimic-medication)
- `Medication.ingredient.item[x]` (mimic-medication)
- `MedicationAdministration.statusReason` (mimic-medication-administration)
- `MedicationAdministration.performer.function` (mimic-medication-administration)
- `MedicationAdministration.reasonCode` (mimic-medication-administration)
- `MedicationAdministration.statusReason` (mimic-medication-administration-icu)
- `MedicationAdministration.performer.function` (mimic-medication-administration-icu)
- `MedicationAdministration.reasonCode` (mimic-medication-administration-icu)
- `MedicationAdministration.dosage.site` (mimic-medication-administration-icu)
- `MedicationAdministration.dosage.route` (mimic-medication-administration-icu)
- `MedicationDispense.statusReason[x]` (mimic-medication-dispense)
- `MedicationDispense.performer.function` (mimic-medication-dispense)
- `MedicationDispense.type` (mimic-medication-dispense)
- `MedicationDispense.dosageInstruction.additionalInstruction` (mimic-medication-dispense)
- `MedicationDispense.dosageInstruction.asNeeded[x]` (mimic-medication-dispense)
- `MedicationDispense.dosageInstruction.site` (mimic-medication-dispense)
- `MedicationDispense.dosageInstruction.method` (mimic-medication-dispense)
- `MedicationDispense.dosageInstruction.doseAndRate.type` (mimic-medication-dispense)
- `MedicationDispense.substitution.type` (mimic-medication-dispense)
- `MedicationDispense.substitution.reason` (mimic-medication-dispense)
- `MedicationDispense.statusReason[x]` (mimic-medication-dispense-ed)
- `MedicationDispense.performer.function` (mimic-medication-dispense-ed)
- `MedicationDispense.type` (mimic-medication-dispense-ed)
- `MedicationDispense.substitution.type` (mimic-medication-dispense-ed)
- `MedicationDispense.substitution.reason` (mimic-medication-dispense-ed)
- `MedicationRequest.statusReason` (mimic-medication-request)
- `MedicationRequest.category` (mimic-medication-request)
- `MedicationRequest.performerType` (mimic-medication-request)
- `MedicationRequest.reasonCode` (mimic-medication-request)
- `MedicationRequest.courseOfTherapyType` (mimic-medication-request)
- `MedicationRequest.dosageInstruction.additionalInstruction` (mimic-medication-request)
- `MedicationRequest.dosageInstruction.asNeeded[x]` (mimic-medication-request)
- `MedicationRequest.dosageInstruction.site` (mimic-medication-request)
- `MedicationRequest.dosageInstruction.method` (mimic-medication-request)
- `MedicationRequest.dosageInstruction.doseAndRate.type` (mimic-medication-request)
- `MedicationRequest.substitution.allowed[x]` (mimic-medication-request)
- `MedicationRequest.substitution.reason` (mimic-medication-request)
- `MedicationStatement.statusReason` (mimic-medication-statement-ed)
- `MedicationStatement.reasonCode` (mimic-medication-statement-ed)
- `Observation.bodySite` (mimic-observation-chartevents)
- `Observation.method` (mimic-observation-chartevents)
- `Observation.referenceRange.appliesTo` (mimic-observation-chartevents)
- `Observation.component.code` (mimic-observation-chartevents)
- `Observation.component.value[x]` (mimic-observation-chartevents)
- `Observation.bodySite` (mimic-observation-datetimeevents)
- `Observation.method` (mimic-observation-datetimeevents)
- `Observation.referenceRange.appliesTo` (mimic-observation-datetimeevents)
- `Observation.component.code` (mimic-observation-datetimeevents)
- `Observation.component.value[x]` (mimic-observation-datetimeevents)
- `Observation.bodySite` (mimic-observation-ed)
- `Observation.method` (mimic-observation-ed)
- `Observation.referenceRange.appliesTo` (mimic-observation-ed)
- `Observation.component.code` (mimic-observation-ed)
- `Observation.component.value[x]` (mimic-observation-ed)
- `Observation.bodySite` (mimic-observation-labevents)
- `Observation.method` (mimic-observation-labevents)
- `Observation.referenceRange.appliesTo` (mimic-observation-labevents)
- `Observation.component.code` (mimic-observation-labevents)
- `Observation.component.value[x]` (mimic-observation-labevents)
- `Observation.bodySite` (mimic-observation-micro-org)
- `Observation.method` (mimic-observation-micro-org)
- `Observation.referenceRange.appliesTo` (mimic-observation-micro-org)
- `Observation.component.code` (mimic-observation-micro-org)
- `Observation.component.value[x]` (mimic-observation-micro-org)
- `Observation.bodySite` (mimic-observation-micro-susc)
- `Observation.method` (mimic-observation-micro-susc)
- `Observation.referenceRange.appliesTo` (mimic-observation-micro-susc)
- `Observation.component.code` (mimic-observation-micro-susc)
- `Observation.component.value[x]` (mimic-observation-micro-susc)
- `Observation.bodySite` (mimic-observation-micro-test)
- `Observation.method` (mimic-observation-micro-test)
- `Observation.referenceRange.appliesTo` (mimic-observation-micro-test)
- `Observation.component.code` (mimic-observation-micro-test)
- `Observation.component.value[x]` (mimic-observation-micro-test)
- `Observation.bodySite` (mimic-observation-outputevents)
- `Observation.method` (mimic-observation-outputevents)
- `Observation.referenceRange.appliesTo` (mimic-observation-outputevents)
- `Observation.component.code` (mimic-observation-outputevents)
- `Observation.component.value[x]` (mimic-observation-outputevents)
- `Observation.bodySite` (mimic-observation-vital-signs)
- `Observation.method` (mimic-observation-vital-signs)
- `Observation.referenceRange.appliesTo` (mimic-observation-vital-signs)
- `Observation.component.value[x]` (mimic-observation-vital-signs)
- `Procedure.statusReason` (mimic-procedure)
- `Procedure.category` (mimic-procedure)
- `Procedure.performer.function` (mimic-procedure)
- `Procedure.reasonCode` (mimic-procedure)
- `Procedure.bodySite` (mimic-procedure)
- `Procedure.outcome` (mimic-procedure)
- `Procedure.complication` (mimic-procedure)
- `Procedure.followUp` (mimic-procedure)
- `Procedure.usedCode` (mimic-procedure)
- `Procedure.statusReason` (mimic-procedure-ed)
- `Procedure.category` (mimic-procedure-ed)
- `Procedure.performer.function` (mimic-procedure-ed)
- `Procedure.reasonCode` (mimic-procedure-ed)
- `Procedure.bodySite` (mimic-procedure-ed)
- `Procedure.outcome` (mimic-procedure-ed)
- `Procedure.complication` (mimic-procedure-ed)
- `Procedure.followUp` (mimic-procedure-ed)
- `Procedure.usedCode` (mimic-procedure-ed)
- `Procedure.statusReason` (mimic-procedure-icu)
- `Procedure.performer.function` (mimic-procedure-icu)
- `Procedure.reasonCode` (mimic-procedure-icu)
- `Procedure.outcome` (mimic-procedure-icu)
- `Procedure.complication` (mimic-procedure-icu)
- `Procedure.followUp` (mimic-procedure-icu)
- `Procedure.usedCode` (mimic-procedure-icu)
- `Specimen.collection.method` (mimic-specimen)
- `Specimen.collection.bodySite` (mimic-specimen)
- `Specimen.processing.procedure` (mimic-specimen)
- `Specimen.container.type` (mimic-specimen)
- `Specimen.container.additive[x]` (mimic-specimen)
