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

ICD10_YEARS ?= 2016 2017 2018 2019 2024
ICD10PCS_YEARS ?= 2016 2018 2019 2020

TERM := scripts/terminology-mapping
ICD9 := $(TERM)/terminology/icd9/build_icd9cm_codesystem.py
ICD10CM := $(TERM)/terminology/icd10cm/build_icd10cm_codesystem.py
ICD10PCS := $(TERM)/terminology/icd10pcs/build_icd10pcs_codesystem.py
SCAFFOLD := $(TERM)/valuesets/build_scaffold_valueset.py
CONCEPTMAP := $(TERM)/conceptmaps/build_conceptmap.py
VALUESET := $(TERM)/valuesets/build_final_valueset.py
VERIFY := $(TERM)/verify/verify_mappings.py

.PHONY: verify-inputs update-manifest terminology deploy-terminology scaffolds \
        conceptmaps valuesets verify-mappings mappings upload-mappings ig

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

# --- stages 2-4: mappings, built locally ----------------------------------- #

scaffolds: ## build the placeholder target ValueSets the ConceptMaps point at
	uv run $(SCAFFOLD) --no-upload

conceptmaps: ## build the ConceptMaps from the built CodeSystems (the only place rules live)
	uv run $(CONCEPTMAP) --no-upload

valuesets: ## build the enumerated target ValueSets by translating through the ConceptMaps
	uv run $(VALUESET) --offline --no-upload

verify-mappings: ## check coverage + invariants; non-zero while codes are unmapped
	uv run $(VERIFY)

mappings: scaffolds conceptmaps valuesets verify-mappings ## stages 2-4 then verify

# --- stage 5: publish, gated ----------------------------------------------- #

upload-mappings: ## publish ConceptMaps + ValueSets, only if verify-mappings passes
	uv run $(VERIFY) $(ARGS)
	uv run $(SCAFFOLD) $(UPLOAD)
	uv run $(CONCEPTMAP) $(UPLOAD)
	uv run $(VALUESET) $(UPLOAD)

ig: ## compile FSH (sushi) and build the IG package (output/package.tgz)
	sushi .
	./_genonce.sh
