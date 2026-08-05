Profile:        MimicObservationMerged
Parent:         Observation
Id:             mimic-observation-merged
Title:          "MIMIC Observation (merged sub-types)"
Description:    "A facade profile for downstream pipelines that merge every MIMIC Observation sub-type (chartevents, datetimeevents, ED, labevents, microbiology organism/antibiotic/test, outputevents, vital signs) into a single Observation resource, e.g. because a processing engine requires exactly one resource type per table. Binds Observation.code to the union of all sub-type code ValueSets so a single fhirpath-driven code search can find codes across the merged data, and repeats the vital-signs binding on Observation.component.code, which is where the blood-pressure panel keeps its systolic and diastolic codes. This profile is not part of the upstream MIMIC IG and is not used by any example instance in this IG; it exists to give merged data a `meta.profile` that still resolves to exactly one bound ValueSet."

// cardinalities of used elements
// Blood pressure is one Observation coded 85354-9 |Blood pressure panel| whose
// two numbers live in component, so merged data carries components even though
// no other sub-type produces them. Mirrors MimicObservationVitalSigns.
* component 0..2

// binding to MIMIC terminology
* code from MimicObservationMergedCode
// Not folded into MimicObservationMergedCode: that value set is bound to
// Observation.code with REQUIRED strength, so including the component codes
// there would legalise `code = 8480-6 |Systolic blood pressure|` on a merged
// Observation — a code MIMIC only ever emits inside component.
* component.code from MimicObservationComponentVital (required)
