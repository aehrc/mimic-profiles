ValueSet: MimicObservationMergedCode
Id: mimic-observation-merged-code
Title: "MIMIC Observation code (merged sub-types)"
Description: "Union of the per-sub-type Observation.code binding ValueSets (chartevents, datetimeevents, ED, labevents, microbiology organism/antibiotic/test, outputevents, vital signs), for use by MimicObservationMerged. Grouping ValueSet — references only, no own codes. Not part of the upstream MIMIC IG."

* include codes from valueset MimicCharteventsDItems
* include codes from valueset MimicDatetimeeventsDItems
* include codes from valueset MimicObservationTypeED
* include codes from valueset MimicDLabitems
* include codes from valueset MimicMicrobiologyOrganism
* include codes from valueset MimicMicrobiologyAntibiotic
* include codes from valueset MimicMicrobiologyTest
* include codes from valueset MimicOutputeventsDItems
* include codes from valueset MimicObservationTypeVital
