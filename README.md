# mimic-profiles
FHIR profiles for MIMIC-IV. The MIMIC-IV and MIMIC-IV-ED databases have been modelled as FHIR resources. The process to generate the full implementation guide with resources is:

1. Set up FSH and SUSHI - [SUSHI Setup Guide](https://fshschool.org/docs/sushi/installation/)
- Install Node.js (needed for SUSHI): https://nodejs.org/en/
  - Check node.js is properly set up: `node --version` or `npm --version`
- Install SUSHI: `npm install -g fsh-sushi`

2. Generate FHIR resources from FSH
- In the main directory of the repo run `sushi .`
- This command will generate the FHIR resources from the FSH files


3. Set up the IG Publisher
- [Install Jekyll](https://jekyllrb.com/docs/installation/) (need for the IG html output)
- Run `./_updatePublisher.sh` from the top of the repository to get the latest IG Publisher
  - If _updatePublisher.sh does not work you can manually download the [IG publisher](https://github.com/HL7/fhir-ig-publisher/releases/latest/download/publisher.jar.)


4. Generate the mimic-fhir implementation guide 
- Run `./_genonce.sh`from the top of the repository to generate the mimic-fhir IG

## Publishing conformance resources to the Velonto FHIR server

The `Deploy conformance resources to Velonto` GitHub Actions workflow
(`.github/workflows/deploy-conformance.yml`) builds the IG and publishes every
CodeSystem, ValueSet, and StructureDefinition from the build output to
`http://velonto.dw.csiro.au/fhir`, so the server always reflects the
conformance resources defined in this repository. Terminology (CodeSystems then
ValueSets) is published before StructureDefinitions, so terminology a profile
binds to is present first.

- **Triggers**: manually via workflow dispatch, and automatically on pushes to
  the `velonto` branch.
- **Runner**: the self-hosted `pathling-linux` runner, which has network access
  to `velonto.dw.csiro.au`. The build steps mirror those in `deploy.yml`
  (Java 17, Ruby/Jekyll, Node/SUSHI, then the HL7 IG Publisher).
- **Publish behaviour**: for each conformance resource, any server copy sharing
  the same canonical `url` is deleted, then the build-output copy is uploaded by
  its resource id (`PUT [base]/[type]/[id]`). The run fails fast on the first
  unexpected HTTP response, naming the resource that failed.

The publish step is a standalone script that can be run locally against any
FHIR R4 base URL:

```bash
scripts/publish-conformance.sh <fhir-base-url> <resource-dir>
# e.g. after a local build:
scripts/publish-conformance.sh http://velonto.dw.csiro.au/fhir output
```

It requires `curl` and `jq` on the PATH and reads `CodeSystem-*.json`,
`ValueSet-*.json`, and `StructureDefinition-*.json` from the given directory.

## CSIRO fork changes (2026-07-10): terminology bindings

A full-data binding analysis (see `scripts/binding-analysis/`, decisions and
evidence in `scripts/binding-analysis/FINDINGS.md`) added required terminology
bindings to elements that previously had none. All 131 bindable coded elements
were scanned against the complete MIMIC-on-FHIR dataset; the 11 populated ones
are now bound.

**New required bindings (profiles):**
- `medication[x]` → `mimic-medication` on MedicationAdministrationICU,
  MedicationDispense, MedicationRequest.
- `medication[x]` → new **`mimic-medication-with-unknown`** ValueSet
  (`mimic-medication` + `v3-NullFlavor#UNK`) on MedicationAdministration —
  931 of 27.7M hospital rows carry UNK where the drug could not be coded.
- `value[x]` → `mimic-micro-interpretation` on ObservationMicroSusc.
- `valueCodeableConcept` → `v3-NullFlavor` on ObservationMicroTest (only the
  CodeableConcept choice is bound; free-text string results remain valid).
- `Encounter.priority` → `v3-ActPriority`; `Location.physicalType` →
  `location-physical-type`; `Organization.type` → `organization-type`.
- MedicationStatementED: coding slicing closed (only gsn/ndc/etc systems occur
  in the data), per-slice required bindings `coding[gsnCode]` →
  `mimic-medication-gsn` and `coding[etccodeCode]` → `mimic-medication-etc`.
  The `ndcCode` slice stays unbound: no available terminology server hosts
  `http://hl7.org/fhir/sid/ndc` (an extensional VS of the 9,312 observed NDC
  codes is documented as a future option in FINDINGS.md).
- ObservationVitalSigns: `component.code` → new
  **`mimic-observation-component-vital`** ValueSet (systolic/diastolic BP
  LOINCs `8480-6`/`8462-4`, previously in no ValueSet).

**IG QA fixes:**
- `EX_MimicEncounter`: `priority` example corrected to `v3-ActPriority#EM` —
  real data uses ActPriority (R/EL/EM/UR), not `mimic-admission-type`.
- `EX_MimicMedicationStatementED`: example rebuilt as Acetaminophen 325mg with
  an observed NDC code that also resolves on tx.fhir.org (most MIMIC NDC codes
  are delisted and unknown to tx, which fails IG QA).
- `MimicQuantityUnit`: `degF` corrected to the valid UCUM form `[degF]`.
- Removed the invalid `CodeSystem.valueSet` all-codes claim from
  `mimic-admission-class` and `mimic-admission-type` (their ValueSets also
  include codes from other systems).
