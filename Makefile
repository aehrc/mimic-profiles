# One target per pipeline stage — see RUNBOOK.md for the full DAG and which
# stages run on the laptop vs the HPC node. Configuration comes from the
# environment (see .env.example); CLI flags on the underlying scripts override.

# .env fills in only what the shell environment hasn't already set, so
# `set -a; source .env` and plain `make` behave the same. Only the variables
# the build scripts read are exported — the rest of .env stays out of the
# recipes' environment.
ONTOSERVER_URL_ENV := $(ONTOSERVER_URL)
SSL_CERT_FILE_ENV := $(SSL_CERT_FILE)
-include .env
ONTOSERVER_URL := $(or $(ONTOSERVER_URL_ENV),$(ONTOSERVER_URL))
SSL_CERT_FILE := $(or $(SSL_CERT_FILE_ENV),$(SSL_CERT_FILE))
export ONTOSERVER_URL
ifneq ($(strip $(SSL_CERT_FILE)),)
export SSL_CERT_FILE
endif

# Per-run override for the upload target: make deploy-terminology FHIR_BASE=…
# Unset ⇒ nothing is passed and the scripts fall back to $ONTOSERVER_URL.
# (It cannot be spelled --fhir-base on the make command line: make claims every
# argument starting with `--` for itself.)
FHIR_BASE ?=
UPLOAD := $(if $(strip $(FHIR_BASE)),--fhir-base $(FHIR_BASE))

# Publish a subset: make upload-mappings ONLY=observation-component
# Comma-separated, no spaces. Unset ⇒ every ConceptMap in output/.
ONLY ?=
ONLY_ARG := $(if $(strip $(ONLY)),--only $(ONLY))

ICD10_YEARS ?= 2016 2017 2018 2019 2024
ICD10PCS_YEARS ?= 2016 2018 2019 2020

TERM := scripts/terminology-mapping
ICD9 := $(TERM)/terminology/icd9/build_icd9cm_codesystem.py
ICD10CM := $(TERM)/terminology/icd10cm/build_icd10cm_codesystem.py
ICD10PCS := $(TERM)/terminology/icd10pcs/build_icd10pcs_codesystem.py
# One builder per bound element. Each writes its ConceptMap, its enumerated
# target ValueSet, its unmapped CSV and its report in a single offline pass.
CONDITION := $(TERM)/conceptmaps/build_condition_cm_vs.py
PROCEDURE := $(TERM)/conceptmaps/build_procedure_cm_vs.py
OBSERVATION := $(TERM)/conceptmaps/build_observation_cm_vs.py
# Observation.component.code is its own bound element with its own binding, so
# its own builder and its own target — not a sub-step of `observation`.
OBSERVATION_COMPONENT := $(TERM)/conceptmaps/build_observation_component_cm_vs.py
VERIFY := $(TERM)/verify/verify_mappings.py
VERIFY_CURATED := $(TERM)/verify/verify_curated_snomed.py
D_ITEMS_TABLE := $(TERM)/conceptmaps/build_d_items_table.py
MICRO_SUSC_TABLE := $(TERM)/conceptmaps/build_micro_susc_table.py
MICRO_TEST_TABLE := $(TERM)/conceptmaps/build_micro_test_table.py
OUTPUTEVENTS_TABLE := $(TERM)/conceptmaps/build_outputevents_table.py
STATISTICS := $(TERM)/build_statistics.py
UPLOAD_MAPPINGS := $(TERM)/upload.py

.PHONY: verify-inputs update-manifest terminology deploy-terminology \
        condition procedure observation observation-component verify-mappings \
        verify-curated d-items-table micro-susc-table micro-test-table \
        outputevents-table mappings statistics \
        upload-mappings ig

verify-inputs: ## check ICD source files against input-manifest.json
	uv run $(TERM)/verify_inputs.py

update-manifest: ## regenerate input-manifest.json after adding/changing a release
	uv run $(TERM)/update_manifest.py \
		--icd10cm-years $(ICD10_YEARS) --icd10pcs-years $(ICD10PCS_YEARS)

# --- stage 1: CodeSystems -------------------------------------------------- #

terminology: ## build ICD CodeSystems into scripts/terminology-mapping/output/ (no upload)
	uv run $(ICD9) --no-upload
	uv run $(ICD10CM) $(ICD10_YEARS) --no-upload
	uv run $(ICD10PCS) $(ICD10PCS_YEARS) --no-upload

deploy-terminology: ## build + upload CodeSystems to $$ONTOSERVER_URL (runs $$lookup smoke tests)
	uv run $(ICD9) $(UPLOAD)
	uv run $(ICD10CM) $(ICD10_YEARS) $(UPLOAD)
	uv run $(ICD10PCS) $(ICD10PCS_YEARS) $(UPLOAD)

# --- stage 2: mappings, built locally and offline --------------------------- #
#
# One target per bound element. Each builder emits its ConceptMap AND the
# enumerated ValueSet that map's targetCanonical names, in the same pass — which
# is why there is no longer a scaffold stage. The scaffold existed only because
# the value set used to be derived from the map in a LATER stage, so at
# map-writing time the targetCanonical pointed at nothing yet. Nothing else ever
# read it.
#
# These touch no network: a builder is a pure function of the committed inputs,
# so `make mappings` is instant and a build from unchanged inputs is
# byte-identical.

condition: ## build the Condition.code ConceptMap + target ValueSet
	uv run $(CONDITION)
	uv run $(STATISTICS) --quiet

procedure: ## build the Procedure.code ConceptMap + target ValueSet
	uv run $(PROCEDURE)
	uv run $(STATISTICS) --quiet

# Reads the FSH-generated Observation ValueSets, so it needs `sushi .` to have
# run — the builder says so and exits rather than emitting a map that silently
# drops a whole population. Same for observation-component below.
observation: ## build the Observation.code ConceptMap + target ValueSet
	uv run $(OBSERVATION)
	uv run $(STATISTICS) --quiet

# Deliberately NOT a dependency of `observation`. Observation.component.code is
# a separate column with a separate binding that happens to sit on the same
# resource; a consumer projects it separately and translates it through its own
# map. Merging the two would leave neither map a correct sourceCanonical.
observation-component: ## build the Observation.component.code ConceptMap + target ValueSet
	uv run $(OBSERVATION_COMPONENT)
	uv run $(STATISTICS) --quiet

verify-mappings: ## check coverage + invariants; non-zero while codes are unmapped
	uv run $(VERIFY)

# Flattens every <field>-report.json into output/mapping-statistics.{csv,html}
# and prints the per-stream table. Recomputes nothing, so a partial build stays
# honest: `make observation` refreshes its own report and this reads the
# committed reports for every other field. The field targets above run it
# --quiet so the files never go stale; this target is the loud version.
statistics: ## per-stream coverage table from the field reports (csv + html + terminal)
	uv run $(STATISTICS)

# `statistics` before `verify-mappings`: the verifier is non-zero by design
# while anything is unmapped, and the coverage table is most useful exactly then.
mappings: condition procedure observation observation-component statistics verify-mappings ## build every population, then verify

# NOT part of `mappings`: it needs the network, while the builders are offline
# and instant. Run it when you touch a mapping table.
verify-curated: ## $$lookup every SNOMED code in the mapping tables
	uv run $(VERIFY_CURATED) $(ARGS)

# Also NOT part of `mappings`, and for a stronger reason than verify-curated:
# this one WRITES a build input. It needs both the network and the code-search
# service, and it is the only stage whose output is not a pure function of this
# repo. Run it deliberately, read the diff, commit the CSV — after which
# `make mappings` is offline and reproducible again.
d-items-table: ## regenerate conceptmaps/d-items-snomed.csv from code-search
	uv run $(D_ITEMS_TABLE) $(ARGS)

# One generator per Observation stream, for the same reason there is one table
# per stream: each needs its own search constraint, context template and
# equivalence rule, and adding a stream must rebuild nothing else. Same standing
# as d-items-table above — network, writes a build input, never part of
# `mappings`.
#
#   make micro-susc-table ARGS="--only 90020,90026 --insecure"   probe a few
micro-susc-table: ## regenerate conceptmaps/micro-susc-loinc.csv from code-search
	uv run $(MICRO_SUSC_TABLE) $(ARGS)

# The 176 microbiology test names. Same standing as the two above. The only
# generator that searches TWO disjoint spaces per item — LOINC's MICRO class and
# its cytogenetics classes — and requires exactly one of them to answer, because
# BIDMC files karyotyping in the same results table and one merged constraint
# answers the cytogenetic cell cultures with bacterial cultures. The generator's
# docstring carries the evidence.
#
#   make micro-test-table ARGS="--only 90039,90075 --insecure"   probe a few
micro-test-table: ## regenerate conceptmaps/micro-test-loinc.csv from code-search
	uv run $(MICRO_TEST_TABLE) $(ARGS)

# The 77 ICU outputevents items. Same standing as the two above. Additionally
# reads MIMIC-IV demo 2.2's ICU dictionary for its pre-filter — the 5 items that
# record no volume are declined without being searched, because the service
# answers them confidently and wrongly.
#
#   make outputevents-table ARGS="--only 226559,226610 --insecure"   probe a few
outputevents-table: ## regenerate conceptmaps/outputevents-loinc.csv from code-search
	uv run $(OUTPUTEVENTS_TABLE) $(ARGS)

# --- stage 3: publish, gated ------------------------------------------------ #

# The builders never upload; this is the only target that writes to a server.
# It publishes every ConceptMap in output/ together with the ValueSet that map's
# own targetCanonical names, value sets first so a map is never briefly pointing
# at something the server does not hold.
#
# Two flag variables because the two steps take different flags: ARGS reaches
# verify (--allow-unmapped, once the unmapped list has been reviewed and
# accepted — verify exits non-zero while any code is unmapped, and that is the
# gate working, not a failure), UPLOAD_ARGS reaches the publisher (--insecure,
# --ca-bundle).
#
#   make upload-mappings ARGS=--allow-unmapped UPLOAD_ARGS=--insecure
#
# ONLY narrows the publish to named populations — the names the builders use,
# which is what `verify-mappings` prints on its `populations:` line and what the
# <field>-report.json files are called. Publishing is a PUT by id, so an
# unnarrowed run replaces the server's copy of every map in output/, including
# ones this branch changed and you did not mean to move:
#
#   make upload-mappings ONLY=observation-component ARGS=--allow-unmapped UPLOAD_ARGS=--insecure
#   make upload-mappings ONLY=observation,observation-component ...
#
# It narrows only the publish. Verify still runs over every population.
upload-mappings: ## publish ConceptMaps + ValueSets, only if verify-mappings passes
	uv run $(VERIFY) $(ARGS)
	uv run $(UPLOAD_MAPPINGS) $(UPLOAD) $(ONLY_ARG) $(UPLOAD_ARGS)

ig: ## compile FSH (sushi) and build the IG package (output/package.tgz)
	sushi .
	./_genonce.sh
