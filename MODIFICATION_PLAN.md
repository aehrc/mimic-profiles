# Fork Modification Plan: ValueSet Bindings for MIMIC-on-FHIR IG

**Goal:** add machine-followable ValueSet bindings (`ElementDefinition.binding`) to coded
fields of the MIMIC profiles (e.g. `MedicationAdministration.medication[x]`), so that a
profile snapshot answers "which ValueSet constrains this field". Local republish first
(internal Ontoserver), upstream PR to kindlab/mimic-profiles later.

**Key decisions (from planning session 2026-07-10):**

- Bindings go on the CodeableConcept element itself (not `.coding` — the existing
  `$GSN_VS` binding on `MedicationAdministrationED.medicationCodeableConcept.coding` is a
  known wart), with explicit strength `(required)`. Strength may be renegotiated to
  `extensible` upstream.
- Evidence-driven: a field gets a binding only if the **full MIMIC-on-FHIR data** is 100%
  covered by the ValueSet. Three-way verdict per field: **bind** / **repair VS or CS**
  (small gap, list missing codes) / **no binding** (structural mismatch — must be
  collected machine-readably, downstream use case handles these explicitly).
- Coverage check is `(system, code)` membership, not bare codes. MIMIC ValueSets have no
  filters/expansions — each just includes whole CodeSystems — so expansion = union of the
  included CodeSystems' concept lists, computable offline from `package.tgz`.
- SUSHI only compiles `input/fsh/` (8 VS, 0 CS). The other 34 VS + 39 CS are JSON in
  `input/resources/`, merged only by the IG Publisher (`_genonce.sh`) into
  `output/package.tgz`. All tooling reads the **built package**, never `fsh-generated/`
  alone.
- Fork version bumped to `1.3.0-csiro.1` (canonical URL unchanged) so the modified
  package is distinguishable from the published 1.3.0 on the terminology server.
- Tooling lives in this repo under `scripts/binding-analysis/`, self-contained (plain
  PySpark + Pathling on the HPC node; no internet on the node; small reference tables
  copied from master_thesis_pipeline with attribution).
- MedicationAdministration (base vs ICU) and Observation (8 profiles) share resource
  types → phase 1 partitions by `meta.profile` (confirmed populated in the Delta data).
- Felix's consumer merges profile-flavored NDJSON back into plain resource types
  (regex-stripping Mimic/ED/ICU/... from file names). Consequence: field→VS resolution
  must be keyed on `meta.profile` (or source-file flavor), not resource type alone —
  e.g. Observation.value[x] binds differently for micro-susc vs micro-test. The two
  MedicationAdministration profiles happen to converge on `mimic-medication`.

## Steps

| # | What | Who | Gate |
|---|------|-----|------|
| 0 | `_updatePublisher.sh`; version bump; `sushi` + `_genonce.sh` on unmodified fork | Claude | `output/package.tgz` exists with 34 VS + 39 CS; QA report sane |
| 1 | Phase-0 script: walk package snapshots → candidate elements (`CodeableConcept`/`Coding`/`code`, no effective binding, excluding R4 `required` base bindings; flag the GSN `.coding` wart) → `work-items.json` | subagent | Felix eyeballs the ~30–60 candidates |
| 2 | Phase-1 Spark script generated from work-items: distinct `(system, code, display, count)` per element per `meta.profile` partition | subagent | Felix runs on HPC node, brings back `distinct-codes` artifact |
| 3 | Phase-2 cross-check: offline set logic over package.tgz → `binding-report.json` (bind / repair / no-binding, with row counts) | subagent | Felix reviews report, decides repair cases |
| 4 | FSH edits: `* <element> from $<VS> (required)` per "bind" verdict; agreed CS repairs | Claude | `sushi` + `_genonce.sh` clean; `validator_cli` passes on the IG's examples |
| 5 | Spot-check 2–3 bindings via terminology server `$expand`; hand `package.tgz` + version note to server admin | Felix | endpoint resolves field → VS end-to-end |
| 6 | Upstream PR: FSH diffs + coverage report as evidence; discuss binding strength | later | — |

## Status

- [x] 0 — baseline build (package.tgz: 42 VS, 39 CS, 54 SD; requires ruby/jekyll via brew)
- [x] 1 — candidate extraction (`scripts/binding-analysis/phase0_candidates.py`): 131 candidates / 160 already-bound across 25 profiles in `work-items.json`; kept inherited example-bound fields, phase 1 filters empirically
- [x] 2 — Spark distinct-values extraction (run on node): 131 items, 0 errors, 11 populated fields (incl. all 5 medication[x]), 120 no-data; 38,102 distinct codes in `distinct-codes.ndjson`. Node fixes: PathlingContext.create() must own the SparkSession; Pathling 7+ uses view() not extract()
- [x] 3 — coverage cross-check + report (`binding-report.{json,md}`): 4 bind, 1 repair (admin-hosp: single NullFlavor UNK gap, 931 rows), 2 no-binding (statement-ed systems disjoint from mimic-medication; vital-signs BP LOINCs missing from VS), 4 external-terminology, 120 no-data
- [ ] 4 — FSH bindings + rebuild + validate — **paused awaiting decisions D1–D4 in
      `scripts/binding-analysis/FINDINGS.md`** (findings + proposed FSH lines +
      Ontoserver validation results all recorded there)
- [ ] 5 — deploy to terminology server
- [ ] 6 — upstream PR
