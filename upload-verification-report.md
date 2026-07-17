# Upload Verification Report

**Package:** `kindlab.fhir.mimic` v`1.4.0-csiro`
**Server:** `https://velonto.dw.csiro.au/fhir/`
**Date:** 2026-07-13

## Server Status

Server is up and responding (HTTP 200 on `/metadata`). Ontoserver `6.27.3-SNAPSHOT`, FHIR `4.0.1`.

## Resource Counts at v1.4.0-csiro

| Resource Type | Count |
|---|---|
| StructureDefinition | 27 |
| ValueSet | 44 |
| CodeSystem | 39 |

Multiple versions now coexist on the server (v1.3.0, v1.3.0-csiro.1, v1.4.0-csiro), resulting in 81 StructureDefinition, 130 ValueSet, and 117 CodeSystem entries total across all versions.

## StructureDefinitions

All 27 expected profiles are present at v1.4.0-csiro (resource dates: 2026-07-13):

- DilutionDetails
- LabPriority
- MimicCondition
- MimicEncounter
- MimicLocation
- MimicMedication
- MimicMedicationAdministration
- MimicMedicationAdministrationICU
- MimicMedicationDispense
- MimicMedicationDispenseED
- MimicMedicationRequest
- MimicMedicationStatementED
- MimicObservationChartevents
- MimicObservationDatetimeevents
- MimicObservationED
- MimicObservationLabevents
- MimicObservationMicroOrg
- MimicObservationMicroSusc
- MimicObservationMicroTest
- MimicObservationOutputevents
- MimicObservationVitalSigns
- MimicOrganization
- MimicPatient
- MimicProcedure
- MimicProcedureED
- MimicProcedureICU
- MimicSpecimen

## ValueSets

All 44 ValueSets present. Key verification:

- **`mimic-medication-with-unknown`** (v1.4.0-csiro, status: draft) — correctly structured with two includes:
  - A `valueSet` reference to `http://mimic.mit.edu/fhir/mimic/ValueSet/mimic-medication`
  - One enumerated concept: `UNK` from `http://terminology.hl7.org/CodeSystem/v3-NullFlavor`
  - `$expand` returns 20,000+ concepts (full medication list)
  - `$validate-code` confirms `UNK` is valid (`result: true`)

## CodeSystems

All 39 CodeSystems present. Concepts are stored internally by the terminology server; the raw GET response returns an empty `concept` array, which is normal server behaviour. All concepts are fully functional via `$lookup`:

- `mimic-admission-class` (9 concepts): `$lookup` confirms EU OBSERVATION, URGENT, ELECTIVE, EW EMER. all accessible
- `mimic-admission-type` (9 concepts): `$lookup` confirms EU OBSERVATION, URGENT, ELECTIVE, SURGICAL SAME DAY ADMISSION, DIRECT OBSERVATION, EW EMER. all accessible

Associated ValueSets expand correctly against both CodeSystems.

## Summary

The upload completed successfully. All StructureDefinitions, ValueSets (including `mimic-medication-with-unknown`), and CodeSystems are present at version `1.4.0-csiro`. No missing or broken resources were found. All `$lookup`, `$expand`, and `$validate-code` operations function correctly.
