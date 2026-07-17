# One target per pipeline stage — see RUNBOOK.md for the full DAG and which
# stages run on the laptop vs the HPC node. Configuration comes from the
# environment (see .env.example); CLI flags on the underlying scripts override.

ICD10_YEARS ?= 2016 2017 2018 2019
MIGRATED_OUT ?= transformed_data

.PHONY: verify-inputs terminology deploy-terminology ig check-codes migrate verify-migration

verify-inputs: ## check ICD source files against input-manifest.json
	uv run scripts/terminology-build/verify_inputs.py

terminology: ## build ICD CodeSystems + mimic-diagnosis ValueSet into scripts/terminology-build/output/ (no upload)
	uv run scripts/terminology-build/build_icd9cm_codesystem.py --no-upload
	uv run scripts/terminology-build/build_icd10cm_codesystem.py $(ICD10_YEARS) --no-upload

deploy-terminology: ## build + upload CodeSystems/ValueSet to $$ONTOSERVER_URL (runs $$lookup smoke tests)
	uv run scripts/terminology-build/build_icd9cm_codesystem.py
	uv run scripts/terminology-build/build_icd10cm_codesystem.py $(ICD10_YEARS)

ig: ## compile FSH (sushi) and build the IG package (output/package.tgz)
	sushi .
	./_genonce.sh

check-codes: ## validate distinct MIMIC ICD codes against $$ONTOSERVER_URL, regenerating display-map.json
	uv run scripts/icd-migration/check_icd_codes.py --system both \
		--valueset http://mimic.mit.edu/fhir/mimic/ValueSet/mimic-diagnosis

migrate: ## rewrite Condition codings to standard ICD systems (HPC node; needs $$MIMIC_WAREHOUSE)
	uv run scripts/icd-migration/migrate_condition_codes.py --output $(MIGRATED_OUT)

verify-migration: ## independent row-by-row check of the migrated Condition table
	uv run scripts/icd-migration/verify_migration.py --migrated $(MIGRATED_OUT)
