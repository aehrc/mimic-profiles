Profile:        MimicLocation
Parent:         Location
Id:             mimic-location
Title:          "MIMIC Location"
Description:    "A MIMIC location profile based on FHIR R4 Location."

// cardinalities of used elements
* name 1..1

// modifications to elements
* physicalType = $LocationPhysicalType#wa "Ward"
* physicalType from $VSLocationPhysicalType (required)

// referencing must be to MIMIC profiles
* managingOrganization only Reference(MimicOrganization)
