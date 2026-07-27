Profile:        MimicObservationMerged
Parent:         Observation
Id:             mimic-observation-merged
Title:          "MIMIC Observation (merged sub-types)"
Description:    "A facade profile for downstream pipelines that merge every MIMIC Observation sub-type (chartevents, datetimeevents, ED, labevents, microbiology organism/antibiotic/test, outputevents, vital signs) into a single Observation resource, e.g. because a processing engine requires exactly one resource type per table. Binds Observation.code to the union of all sub-type code ValueSets so a single fhirpath-driven code search can find codes across the merged data. This profile is not part of the upstream MIMIC IG and is not used by any example instance in this IG; it exists to give merged data a `meta.profile` that still resolves to exactly one bound ValueSet."

// binding to MIMIC terminology
* code from MimicObservationMergedCode
