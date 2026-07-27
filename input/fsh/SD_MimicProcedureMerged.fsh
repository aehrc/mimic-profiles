Profile:        MimicProcedureMerged
Parent:         Procedure
Id:             mimic-procedure-merged
Title:          "MIMIC Procedure (merged sub-types)"
Description:    "A facade profile for downstream pipelines that merge every MIMIC Procedure sub-type (ED, ICD, ICU) into a single Procedure resource, e.g. because a processing engine requires exactly one resource type per table. Binds Procedure.code to the union of all sub-type code ValueSets so a single fhirpath-driven code search can find codes across the merged data. This profile is not part of the upstream MIMIC IG and is not used by any example instance in this IG; it exists to give merged data a `meta.profile` that still resolves to exactly one bound ValueSet."

// binding to MIMIC terminology
* code from MimicProcedureMergedCode
