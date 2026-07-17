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
