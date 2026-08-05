"""Canonical URLs and the systems this repo may leave unversioned."""

from pathlib import Path

from common import paths

REPO = paths.ROOT.parent.parent
RESOURCES = REPO / "input" / "resources"
# FSH-authored IG resources land here. Gitignored, so a clean checkout must run
# `sushi .` before the mapping stages — see igsource.source_concepts.
FSH_GENERATED = REPO / "fsh-generated" / "resources"

# Mapping tables live next to the builders that declare them.
TABLE_DIR = Path(__file__).resolve().parent.parent

ICD9_CM = "http://hl7.org/fhir/sid/icd-9-cm"
ICD10_CM = "http://hl7.org/fhir/sid/icd-10-cm"
ICD10_PCS = "http://www.cms.gov/Medicare/Coding/ICD10"
SNOMED = "http://snomed.info/sct"
LOINC = "http://loinc.org"

# Systems we map INTO but do not build a CodeSystem for, so no release can be
# pinned and there is nothing for the "only releases we built" check to verify.
# A version-less group or include in any other system is a bug, not a choice.
# RxNorm belongs here as soon as a population maps into it.
UNVERSIONED_SYSTEMS = {SNOMED, LOINC}

MIMIC_BASE = "http://mimic.mit.edu/fhir/mimic"

# Our own canonical base. NOT mimic.mit.edu/fhir/mimic — that namespace belongs
# to the upstream IG's publisher (KinD Lab), and minting resources there risks a
# canonical collision on a shared terminology server. Referencing their
# canonicals is fine; creating new ones under their base is not. Consequence:
# resources under this base must NOT live in input/resources/, because the IG
# publisher requires every contained resource's url to start with the IG
# canonical.
CANONICAL_BASE = "http://fhnaumann.github.io/mimic-profiles/fhir"

PUBLISHER = "CSIRO"
