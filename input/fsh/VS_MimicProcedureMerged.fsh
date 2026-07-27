ValueSet: MimicProcedureMergedCode
Id: mimic-procedure-merged-code
Title: "MIMIC Procedure code (merged sub-types)"
Description: "Union of the per-sub-type Procedure.code binding ValueSets (ED, ICD, ICU), for use by MimicProcedureMerged. Grouping ValueSet — references only, no own codes. Not part of the upstream MIMIC IG."

* include codes from valueset $MimicProcedureIcd
* include codes from valueset MimicProcedureTypesED
* include codes from valueset $MimicProcedureeventsDItems
