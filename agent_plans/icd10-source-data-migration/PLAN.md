# ICD-10 Source Data Migration (pinned Coding.version)

## Summary

Migrate the ICD-10-coded `Condition.code` codings in the MIMIC-on-FHIR source data (Delta
warehouse on the CSIRO HPC node) from the custom dotless MIMIC code system
(`http://mimic.mit.edu/fhir/mimic/CodeSystem/mimic-diagnosis-icd10`) to proper ICD-10-CM:
system `http://hl7.org/fhir/sid/icd-10-cm`, dotted code, official display, and — the point
of this plan — a **pinned `Coding.version`** (the earliest ICD-10-CM release year in which
the code is valid). Pinning the version in the data makes every downstream
`$validate-code` a single direct call and sidesteps an Ontoserver quirk where a
version-less coding is only checked against one arbitrary version of a multi-version
ValueSet. Two steps: (1) extend the existing checker so `display-map.json` records the
resolved version per code; (2) author the PySpark migration script that applies the map on
the HPC node.

## Key decisions

- **Version pinned in the data, not probed at query time.** Ontoserver (6.27) `$validate-code`
  against `ValueSet/mimic-diagnosis-icd10cm` (which pins icd-10-cm 2016, 2017, 2018, 2019,
  2024 on `https://velonto.dw.csiro.au/fhir`) only checks a version-less coding against one
  arbitrary compose version; `$expand` unions correctly. Rather than every consumer
  re-implementing the retry workaround, the coding itself carries the version it is valid
  against.
- **"First valid release" is the pinning convention.** Probe order 2016 → 2017 → 2018 →
  2019 → 2024 (the compose order of the ValueSet, fetched live — never hardcode the list),
  pin the first year that validates. This is the earliest release containing the code, not
  necessarily the release the coder used; it is deterministic and documented, which is what
  matters.
- **Display comes from the pinned version.** `$validate-code` with `systemVersion` returns
  that version's display, so map-building yields code, version, and display in one call.
- **The probing happens once, at map-build time.** `display-map.json` (built by
  `check_icd_codes.py` against velonto) is the complete offline artifact for the node —
  the HPC node has **no internet**, so the migration script must need no terminology
  server access.
- **All 18,450 MIMIC ICD-10 codes are known to resolve** (unmapped-icd10.csv is empty as
  of 2026-07-16). The migration script must still fail loudly on unmapped codes rather
  than pass them through silently, in case the data and the checked CodeSystem drift.
- **ICD-9 codings are untouched.** They stay on the custom
  `mimic-diagnosis-icd9` system; a real ICD-9-CM treatment is a separate future effort.
- **Node script conventions** follow `scripts/binding-analysis/phase1_extract_distinct.py`:
  every environment assumption behind a CLI flag, a `--dry-run` mode that works without
  importing pyspark, defensive per-partition error handling. Felix runs it on the node.

## Steps

| # | Step | Description |
|---|------|-------------|
| 01 | version-in-display-map | Extend `check_icd_codes.py` so `display-map.json` records the first-valid release version per code; regenerate it |
| 02 | pyspark-migration-script | Author `scripts/icd-migration/migrate_condition_codes.py` (PySpark, node-ready) applying the map to Condition resources |

## Execution

Single agent — the steps are strictly sequential (step 02 consumes step 01's regenerated
`display-map.json`) and the combined scope is small. Work through the steps in order
(01, 02) and complete the full implementation.

## Open questions

- **Write-back target on the node**: overwrite the Condition Delta table in place vs.
  write a migrated copy / NDJSON export. The step-02 script must make this a CLI choice
  and default to writing a copy; Felix decides at run time.
- **Exact Condition table/path layout on the node** is not knowable from this repo —
  step 02 exposes it as flags (same approach as phase1) and must not guess constants.
