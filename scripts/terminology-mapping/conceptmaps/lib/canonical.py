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
RXNORM = "http://www.nlm.nih.gov/research/umls/rxnorm"
# HL7 v3 NullFlavor, published by THO. A source system here rather than only a
# target: MedicationAdministration.medication[x] admits `UNK` for the
# administrations whose drug could not be coded, and it maps to itself.
NULL_FLAVOR = "http://terminology.hl7.org/CodeSystem/v3-NullFlavor"
# UCUM. The one target system in this repo that is a GRAMMAR rather than an
# enumeration: there is no concept list to look a code up in, so a target is
# checked by parsing it (ucumate) instead of by $lookup. That is what makes the
# units table the only one here whose every row is verifiable offline.
UCUM = "http://unitsofmeasure.org"

# Systems we map INTO but do not build a CodeSystem for, so no release can be
# pinned and there is nothing for the "only releases we built" check to verify.
# A version-less group or include in any other system is a bug, not a choice.
#
# RxNorm joined when MedicationRequest.medication[x] landed. Note the tension it
# makes explicit: the medication table IS derived from one RxNorm release
# (20231106, the only one velonto holds), and its generator asserts that release
# on every run. But asserting a release while generating and PINNING it into a
# published artefact are different claims — pinning says "this repo can
# reproduce that release", which is exactly what check 3 exists to enforce and
# exactly what this repo cannot do for RxNorm. So the release is recorded in the
# generation log, where it is evidence, and not in the map, where it would be a
# promise.
#
# v3-NullFlavor joined with MedicationAdministration.medication[x]. It is a THO
# resource this repo neither builds nor publishes, and the identity group that
# carries `UNK` through translation would otherwise be the one mapping with a
# version nothing here can reproduce. velonto holds it at 2.1.0; that is the
# server's copy, not ours to pin.
#
# UCUM joined with Observation.valueQuantity.code. It is unversioned for a
# reason the other four do not share: UCUM's identity is its grammar, and a
# conformant expression parses the same under every release, so there is no
# release whose absence could change what `mm[Hg]` denotes. Pinning one would
# name a document rather than constrain a meaning.
UNVERSIONED_SYSTEMS = {SNOMED, LOINC, RXNORM, NULL_FLAVOR, UCUM}

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
