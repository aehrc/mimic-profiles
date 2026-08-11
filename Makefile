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
# Specimen.type — the fifth bound element, and the cheapest one left: 116 codes
# carrying the third-largest occurrence count of any bound element.
SPECIMEN := $(TERM)/conceptmaps/build_specimen_cm_vs.py
# MedicationRequest.medication[x] — the sixth bound element, the first targeting
# RxNorm, and the first whose primary method is NOT code-search: a deterministic
# term join answers most of it and the service sees only the residual. Also the
# first scoped to the codes the data actually uses; see the builder's docstring.
MEDICATION := $(TERM)/conceptmaps/build_medication_cm_vs.py
# MedicationAdministration.medication[x] — the seventh bound element and the last
# one in issue #18 with nothing built: 6,135 codes carrying 36.7M occurrences,
# twenty times the sibling MedicationRequest field. A separate binding, and
# almost a disjoint population of the same union, so a separate map. Built one
# stream at a time in the order issue #27 records.
MEDICATION_ADMINISTRATION := $(TERM)/conceptmaps/build_medication_administration_cm_vs.py
# Medication.code — the element MedicationRequest.medication[x] REFERENCES. That
# element is a choice, and at least 87.8% of MIMIC prescriptions take its
# Reference branch (1,883,681 inline codings against 15,416,901 rows), so this is
# the map a consumer needs after dereferencing medicationReference. A required
# binding cannot constrain a Reference, so for those prescriptions this element's
# binding is the only one that governs the drug code. Costs no generation run:
# four of its five populations reuse the sibling fields' committed tables.
MEDICATION_CODE := $(TERM)/conceptmaps/build_medication_code_cm_vs.py
# MedicationStatement.medication[x] — the ED medrecon population. It binds at the
# CODING SLICES (gsn and etc separately, ndc deliberately unbound), so it needed a
# facade ValueSet before a map could name one sourceCanonical. Complete against
# both slices since the medication-gsn stream was built. See issue #28.
MEDICATION_STATEMENT := $(TERM)/conceptmaps/build_medication_statement_cm_vs.py
# MedicationDispense.medication[x] — the LARGEST coded medication population in
# MIMIC: 14,240,367 codings, more than the Request and Administration elements
# together, and where 9,372 of the 9,971 drug-name codes are actually used. Two
# sub-types binding at different depths (hosp binds the CodeableConcept to
# mimic-medication, ED binds .coding to mimic-medication-gsn), hence a merged
# facade. Costs ONE generation run — medication-gsn — because its other five
# populations reuse the sibling fields' committed tables. See issue #29.
MEDICATION_DISPENSE := $(TERM)/conceptmaps/build_medication_dispense_cm_vs.py
VERIFY := $(TERM)/verify/verify_mappings.py
VERIFY_CURATED := $(TERM)/verify/verify_curated_snomed.py
D_ITEMS_TABLE := $(TERM)/conceptmaps/build_d_items_table.py
MICRO_SUSC_TABLE := $(TERM)/conceptmaps/build_micro_susc_table.py
MEDICATION_NAME_TABLE := $(TERM)/conceptmaps/build_medication_name_table.py
MEDICATION_POE_IV_TABLE := $(TERM)/conceptmaps/build_medication_poe_iv_table.py
FORMULARY_DRUG_TABLE := $(TERM)/conceptmaps/build_formulary_drug_table.py
MEDICATION_ICU_TABLE := $(TERM)/conceptmaps/build_medication_icu_table.py
MEDICATION_NDC_TABLE := $(TERM)/conceptmaps/build_medication_ndc_table.py
MEDICATION_ETC_TABLE := $(TERM)/conceptmaps/build_medication_etc_table.py
MEDICATION_GSN_TABLE := $(TERM)/conceptmaps/build_medication_gsn_table.py
MICRO_TEST_TABLE := $(TERM)/conceptmaps/build_micro_test_table.py
OUTPUTEVENTS_TABLE := $(TERM)/conceptmaps/build_outputevents_table.py
DATETIMEEVENTS_TABLE := $(TERM)/conceptmaps/build_datetimeevents_table.py
MICRO_ORG_TABLE := $(TERM)/conceptmaps/build_micro_org_table.py
LABEVENTS_TABLE := $(TERM)/conceptmaps/build_labevents_table.py
CHARTEVENTS_TABLE := $(TERM)/conceptmaps/build_chartevents_table.py
LAB_FLUID_TABLE := $(TERM)/conceptmaps/build_lab_fluid_table.py
SPEC_TYPE_TABLE := $(TERM)/conceptmaps/build_spec_type_table.py
STREAM_REPORTS := $(TERM)/build_stream_reports.py
STATISTICS := $(TERM)/build_statistics.py
UPLOAD_MAPPINGS := $(TERM)/upload.py

.PHONY: verify-inputs update-manifest terminology deploy-terminology \
        verify-mappings verify-curated \
        d-items-table micro-susc-table micro-test-table \
        outputevents-table datetimeevents-table micro-org-table \
        labevents-table chartevents-table lab-fluid-table spec-type-table \
        medication-name-table medication-poe-iv-table formulary-drug-table \
        medication-icu-table medication-ndc-table medication-etc-table \
        medication-gsn-table \
        generate-all-tables \
        mappings stream-reports statistics upload-mappings ig

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
# ONE COMMAND, `make mappings`, and no per-element build targets any more. A
# ConceptMap consumes several streams and the whole offline pipeline takes
# seconds, so a partial build bought nothing except the mixed-state artefacts
# verify check 7 exists to catch. The per-STREAM commands are the generator
# targets below — generation is the only genuinely per-stream operation.
#
# These touch no network: every step is a pure function of the committed
# inputs, so a build from unchanged inputs is byte-identical and
# `make mappings && git diff --exit-code` is a valid test.
#
# Ordering inside `mappings`:
#   builders            one ConceptMap + target ValueSet per bound element
#   stream-reports      resolve every stream once -> stream-report.json,
#                       unmapped-<stream>.csv worklists, occurrence-buckets.csv
#   statistics          render stream-report.json -> csv + html + terminal
#   verify-mappings     the checks; non-zero while codes are unmapped, which
#                       is the gate working rather than a failure
#
# The observation and medication-code builders read FSH-generated ValueSets, so
# a clean checkout needs `sushi .` first — the builders say so and exit rather
# than emitting a map that silently drops a population.

mappings: ## build every ConceptMap + ValueSet, the stream reports, the statistics, then verify
	uv run $(CONDITION)
	uv run $(PROCEDURE)
	uv run $(OBSERVATION)
	uv run $(OBSERVATION_COMPONENT)
	uv run $(SPECIMEN)
	uv run $(MEDICATION)
	uv run $(MEDICATION_ADMINISTRATION)
	uv run $(MEDICATION_CODE)
	uv run $(MEDICATION_STATEMENT)
	uv run $(MEDICATION_DISPENSE)
	uv run $(STREAM_REPORTS) --quiet
	uv run $(STATISTICS)
	uv run $(VERIFY)

# Resolves every stream once (lib/streams.py) and writes the per-stream
# artefacts. Offline; needs the built CodeSystems in output/ like the builders
# do. The occurrence artifacts are optional — absent, the used-in-data columns
# are omitted rather than zeroed.
stream-reports: ## resolve every stream -> stream-report.json + worklists + buckets
	uv run $(STREAM_REPORTS)

statistics: stream-reports ## per-stream coverage table (csv + html + terminal)
	uv run $(STATISTICS)

verify-mappings: ## check coverage + invariants; non-zero while codes are unmapped
	uv run $(VERIFY)

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

# The 188 ICU datetimeevents items, and the first stream since procedureevents to
# target SNOMED — so the first to put a second target system into the
# Observation.code map. Same standing as the three above: network, writes a build
# input, never part of `mappings`.
#
# Its constraint adds `<<364713004 |Temporal observable|` to the procedureevents
# hierarchies, because Observation.value[x] here is a dateTime and the
# administrative dates (date of birth, date of discharge) are observable entities
# that no procedure/finding/event constraint can reach. It also carries a
# device-care reject list, the analogue of the outputevents table's TOTAL_CODES:
# `Arterial catheter care` is true of a dressing, cap, tubing AND wire change
# alike, so mapping it would make four distinct flowsheet columns
# indistinguishable. A second list, WRONG_ACTION, declines a (label, code) PAIR
# for the failure a hierarchy constraint cannot catch — a real, specific concept
# that names the wrong action on the right device. Both are checked before the
# confidence threshold, so an item's recorded status is the reason that actually
# decided it. The generator's docstring carries the evidence, including why the
# threshold stays at 0.8.
#
#   make datetimeevents-table ARGS="--only 224288,224284 --insecure"   probe a few
datetimeevents-table: ## regenerate conceptmaps/datetimeevents-snomed.csv from code-search
	uv run $(DATETIMEEVENTS_TABLE) $(ARGS)

# The 646 microbiology organism names — the largest stream in the Observation
# map so far. Same standing as the four above: network, writes a build input,
# never part of `mappings`.
#
# The first generator here that sends the label with NO context template. Its
# labels are already taxonomic names rather than flowsheet column headings, and
# probing three candidate wrappers found all three answering a NEGATED label
# (`BETA STREP NOT GROUP A OR ANGINOSUS (MILLERI)`) with the very taxon it
# excludes. Its constraint is `<<410607006 |Organism|` alone: unconstrained, the
# `POSITIVE FOR ...` labels come back as findings and substances at 0.90-0.95,
# above several correct answers, and widening to include clinical findings was
# built, probed and dropped because it broke three control rows while rescuing
# none. It also carries WRONG_TAXON, a (itemid, code) pair reject list for the
# one failure the constraint cannot catch — a real organism inside the
# constraint that is wrong about which organism — currently empty, and validated
# both before the run (the concept is real) and after it (the pairing actually
# occurred), because the one entry it shipped with was written from a probe the
# population run did not reproduce. The generator's docstring carries the
# evidence, including why no prefix-stripping rule is applied and why the 0.8
# threshold stays despite 13 of the 15 rows below it looking defensible.
#
#   make micro-org-table ARGS="--only 90707,80249 --insecure"   probe a few
micro-org-table: ## regenerate conceptmaps/micro-org-snomed.csv from code-search
	uv run $(MICRO_ORG_TABLE) $(ARGS)

# The largest stream in the Observation map, 1,622 analytes, and the only one
# whose search text is not the source label: it joins MIMIC's own d_labitems
# dictionary and injects the `fluid` column, because that column is the LOINC
# System axis and only 807 of the 1,622 analytes are blood. Without it every one
# of the 815 non-blood analytes resolves against serum or plasma. `category` is
# deliberately NOT injected — it reaches a better System axis and makes the 52
# `Delete` / `Voided Specimen` rows answer with a blood-gas panel above
# threshold. The generator's docstring carries that evidence, the regression
# that rejected widening the constraint with `CLASS=PULM`, and the one known
# defect (`50823 Required O2`) that no setting catches.
#
# 1,622 items collapse to 1,479 searches on (label, fluid), so this is a long
# run; --only is the way to probe a handful.
#
#   make labevents-table ARGS="--only 50983,51516 --insecure"   probe a few
labevents-table: ## regenerate conceptmaps/labevents-loinc.csv from code-search
	uv run $(LABEVENTS_TABLE) $(ARGS)

# The last Observation stream and the only MIXED-TARGET table: its rows name
# their own terminology, because the population is two things and neither
# terminology covers it alone. LOINC (CLASSTYPE 1 and 2, active) is asked first
# and SNOMED CT (<<363787002 |Observable entity|) only where LOINC declined; the
# two are never compared on confidence. The bare label is sent with NO context
# template — injecting the dictionary's `category` was probed and rejected for
# manufacturing an APACHE IV score for a regression coefficient, and re-probed
# against the first full run's abbreviation defects, which it also failed — and
# 216 documentation, attestation and alarm-limit items are declined WITHOUT
# being searched, because they answer above threshold and wrongly and no
# constraint catches it. The generator's docstring carries that evidence and the
# union-vs-split constraint history.
#
# The longest run here: 2,982 items collapse to ~2,200 searches once the `#<n>`
# instance index is stripped, and every one that LOINC declines costs a second
# SNOMED call. --only is the way to probe a handful.
#
#   make chartevents-table ARGS="--only 220045,224093 --insecure"   probe a few
chartevents-table: ## regenerate conceptmaps/chartevents-standard.csv from code-search
	uv run $(CHARTEVENTS_TABLE) $(ARGS)

# The first stream of a new bound element, Specimen.type, and the smallest in the
# repo: 12 codes, no family collapse, no dictionary join. Same standing as every
# generator above — network, writes a build input, never part of `mappings`.
#
# Its constraint is `<<123038009 |Specimen|`, and this population makes the case
# for constraining more sharply than any before it: of 24 labels probed
# unconstrained over all of SNOMED, only 2 answers were legal Specimen.type
# codes, ELEVEN of the wrong ones scored exactly 1.00, and on two labels the
# wrong concept and the right concept carry the SAME display string
# (1382308001 vs 257261003 |Swab|). The bare label is sent with NO context
# template — a `Laboratory specimen submitted for testing: {}` wrapper changed no
# correct answer's code, cost confidence on three rows, and made two rows accept
# a fabricated specimen they had correctly declined bare.
#
# It is also the first SNOMED generator whose gate ASSERTS VALUE-SET MEMBERSHIP
# via ValueSet/$validate-code, ordered ahead of the active / core-module /
# display checks. The three SNOMED generators before it took membership on trust,
# and on `BLOOD CULTURE` that trust was misplaced: code-search matched an
# inactive concept on an exact FSN hit, followed a SAME_AS association out of the
# requested value set, and returned an AU-extension PROCEDURE at 0.95 while
# declaring `inVS: false` in its own response. Fixed service-side since; the
# check stays, because "the service currently complies" is not a property a
# committed table should rest on.
#
#   make lab-fluid-table ARGS="--only Blood,Ascites --insecure"   probe a few
lab-fluid-table: ## regenerate conceptmaps/lab-fluid-snomed.csv from code-search
	uv run $(LAB_FLUID_TABLE) $(ARGS)

# The 104 microbiology specimen descriptions — the second Specimen.type stream,
# and the one that completes the field. Same standing as every generator above:
# network, writes a build input, never part of `mappings`.
#
# It INHERITS its whole query setup from lab-fluid-table (same `<<123038009`,
# same identity template, same 0.8) because the two are the same bound element
# read off two MIMIC columns. What is its own is the CASE-FOLDED family collapse
# — 104 codes to 93 labels, and MIMIC files 7 itemids as `SWAB`/`Swab`, which
# must not receive different targets — and the absence of a pre-filter. That
# absence is a finding, not an omission: the ~20 labels naming a laboratory TEST
# rather than a specimen (`MRSA SCREEN`, `IMMUNOLOGY`, `CRE Screen`) are declined
# by the search itself, 13 of 16 probed returning no candidate at all, so a
# reject list would duplicate what the constraint already does. `XXX` and
# `MICRO PROBLEM PATIENT` likewise decline unaided, which is why the sibling
# stream's NO_CLINICAL_CONTENT rule is not extended here.
#
# The generator's docstring carries the evidence, including the one known defect
# (`70024 VIRAL CULTURE: R/O CYTOMEGALOVIRUS` fabricates a viral isolate
# specimen at exactly 0.80) and why no reject list was added for it — its sibling
# `70041` differs only by a missing space after the colon, declines today, and so
# could not be given an entry without failing the build.
#
#   make spec-type-table ARGS="--only 70012,70091 --insecure"   probe a few
spec-type-table: ## regenerate conceptmaps/spec-type-snomed.csv from code-search
	uv run $(SPEC_TYPE_TABLE) $(ARGS)

# The medication table has TWO network steps, and only the first is a service
# call. `--refresh-index` re-pulls RxNorm's designations into the committed term
# index, which is a build input; run it deliberately and review the diff, not on
# every generation. Without it the run reads the committed index and contacts
# code-search only for what the index cannot answer.
#
#   make medication-name-table ARGS="--refresh-index --insecure"   re-pull index
#   make medication-name-table ARGS=--insecure                     generate
#   make medication-name-table ARGS="--only Senna,Insulin --insecure"   probe
medication-name-table: ## regenerate conceptmaps/medication-name-standard.csv
	uv run $(MEDICATION_NAME_TABLE) $(ARGS)

# No network and no arguments: it declares two codes unmapped with their reason.
# See its docstring for why it is a script rather than a hand-written CSV.
medication-poe-iv-table: ## regenerate conceptmaps/medication-poe-iv-standard.csv
	uv run $(MEDICATION_POE_IV_TABLE)

# The pharmacy formulary stream, 71.6% of MedicationAdministration.medication[x]
# by data volume. It READS the term index that medication-name-table owns and
# never refreshes it — the two share one constraint, and load_index asserts as
# much — so there is no --refresh-index here.
#
#   make formulary-drug-table ARGS=--insecure                        generate
#   make formulary-drug-table ARGS="--append --insecure"             fill gaps
#   make formulary-drug-table ARGS="--only NACLFLUSH,HEPA5I --insecure"  probe
formulary-drug-table: ## regenerate conceptmaps/formulary-drug-standard.csv
	uv run $(FORMULARY_DRUG_TABLE) $(ARGS)

# The ICU flowsheet stream, 24.4% of MedicationAdministration.medication[x] by
# data volume. Reads the same term index as the two streams above and never
# refreshes it, so there is no --refresh-index here either.
#
# It is the one generator whose SNOMED rung is NOT `<<105590001 |Substance|`:
# asked for the ICU label `Solution` that constraint answers `8537005 |Solution|`
# at confidence 1.00, a physical-state category on 561,934 occurrences. It is
# also the one whose SNOMED gate proves membership of its ECL with
# $validate-code rather than assuming it. Both are argued in its docstring.
#
#   make medication-icu-table ARGS=--insecure                     generate
#   make medication-icu-table ARGS="--append --insecure"          fill gaps
#   make medication-icu-table ARGS="--only 225158,225943 --insecure"  probe
medication-icu-table: ## regenerate conceptmaps/medication-icu-standard.csv
	uv run $(MEDICATION_ICU_TABLE) $(ARGS)

# The NDC stream, 94.2% of Medication.code's reference branch by referring
# prescriptions. The only generator here that contacts NO code-search service:
# both tiers are deterministic lookups, so there is no threshold, no constraint
# and no confidence column. It DOES read medication-name-standard.csv as its
# second tier and records that file's sha256 in the log — regenerate that table
# and this one goes stale with nothing else to notice.
#
# ~5,732 $expand calls at ~0.08s each; a few minutes at the default 8 workers.
#
#   make medication-ndc-table ARGS=--insecure                      generate
#   make medication-ndc-table ARGS="--only 00088222033 --insecure"  probe
medication-ndc-table: ## regenerate conceptmaps/medication-ndc-standard.csv
	uv run $(MEDICATION_NDC_TABLE) $(ARGS)

# The 1,201 FDB therapeutic-class labels of MedicationStatement.medication[x].
# The one medication table with NO RxNorm target — RxNorm has no class concepts
# at any term type, and ATC is on no server this repo can reach — so it is
# single-target SNOMED, and the SUBSTANCE hierarchy rather than the medicinal-
# product one: `<<763158003` contains no diuretic and no dihydropyridine concept,
# which is 4.66% of the element's occurrences. Same standing as every generator
# above: network, writes a build input, never part of `mappings`.
#
# 57 of the 1,201 labels are not medications at all (FDB files devices, supplies
# and bulk chemicals in the same column); the constraint declines them, and the
# generator's docstring carries the adversarial evidence for why no confidence
# threshold could.
#
#   make medication-etc-table ARGS=--insecure                          generate
#   make medication-etc-table ARGS="--only 00000224,00001123 --insecure"  probe
medication-etc-table: ## regenerate conceptmaps/medication-etc-snomed.csv from code-search
	uv run $(MEDICATION_ETC_TABLE) $(ARGS)

# The 9,347 FDB Generic Sequence Numbers shared by MedicationStatement's `gsn`
# coding slice and MedicationDispense's ED pyxis rows — the biggest generated
# table in the repo, and the CHEAPEST per code, because the committed RxNorm term
# index settles 61.4% of it offline (2,137 of the displays are in FDB's
# `generic [Brand]` form and need lib/termindex.bracketed_rungs to get there).
# Only the 3,611-code residual reaches the service. The one SINGLE-TARGET RxNorm
# table here: the SNOMED substance rung its sibling name/formulary streams carry
# was probed and dropped, because GSN has no drug-CLASS gap and that hierarchy
# answered `TAB A VITE` with the nerve agent Tabun.
#
# Budget ~1.5-2.5h at the default 8 workers: the residual is mostly agentic
# calls at ~6-40s each, while a term-join row costs one $lookup.
#
#   make medication-gsn-table ARGS=--insecure                          generate
#   make medication-gsn-table ARGS="--append --insecure"               fill gaps
#   make medication-gsn-table ARGS="--only 004490,006373 --insecure"   probe
medication-gsn-table: ## regenerate conceptmaps/medication-gsn-rxnorm.csv from code-search
	uv run $(MEDICATION_GSN_TABLE) $(ARGS)

# Fill the gaps in every table that CAN have gaps. Only the union-narrowed
# medication tables can: their generation population is "codes the warehouse
# uses on any bound element" (lib/builders.table_population), so a re-extract
# or a new consuming element can widen it past the committed rows. They run in
# --append mode — committed answers, including the declined ones, are kept
# verbatim and only codes with no row are asked. The ten code-search
# generators above are deliberately NOT here: each covers its stream's full
# fixed enumeration, so it never has a gap, and rerunning one is full
# regeneration — nondeterministic, able to CHANGE committed answers, and
# therefore per-stream and deliberate (`make <stream>-table`).
#
# Asks for confirmation first, because even append-only this contacts a paid,
# model-backed service and can run for hours when the gaps are large. FORCE=1
# skips the prompt (an interactive read hangs forever without a TTY):
#
#   make generate-all-tables ARGS=--insecure
#   make generate-all-tables ARGS=--insecure FORCE=1
#
# medication-poe-iv-table is included even though it takes no ARGS (offline,
# two codes); medication-ndc-table is deterministic (no model), so a full run
# is churn-free; medication-name-table is NOT given --refresh-index —
# re-pulling the term index is a build-input change to review on its own.
generate-all-tables: ## fill the gaps in every gap-capable mapping table (network; asks first)
ifndef FORCE
	@printf '\n  WARNING: contacts the code-search service for every mapping table\n'
	@printf '  whose generation population can have grown. Committed answers are\n'
	@printf '  kept (--append); only codes with no row are asked — still\n'
	@printf '  potentially hours and real money when the gaps are large. Full\n'
	@printf '  regeneration stays per-stream: make <stream>-table.\n\n'
	@printf '  Type "yes" to continue: '
	@read answer && [ "$$answer" = yes ] || { echo "  aborted."; exit 1; }
endif
	uv run $(MEDICATION_NAME_TABLE) --append $(ARGS)
	uv run $(MEDICATION_POE_IV_TABLE)
	uv run $(FORMULARY_DRUG_TABLE) --append $(ARGS)
	uv run $(MEDICATION_ICU_TABLE) --append $(ARGS)
	uv run $(MEDICATION_NDC_TABLE) $(ARGS)
	uv run $(MEDICATION_ETC_TABLE) --append $(ARGS)
	uv run $(MEDICATION_GSN_TABLE) --append $(ARGS)

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
