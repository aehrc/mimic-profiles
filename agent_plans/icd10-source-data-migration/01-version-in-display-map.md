# Step 01: Record the resolved release version in display-map.json

## Goal

`display-map.json` is the single offline artifact the HPC-node migration consumes. Today it
maps `original_code -> {code, display}`; after this step it must also carry the ICD-10-CM
release **version** each code was validated against, so the migration can write
`Coding.version` without any terminology-server access.

## Scope

Modify `scripts/icd-migration/check_icd_codes.py` (in this repo) only:

1. The per-code validation loop in `check_system()` already iterates the versions pinned in
   the ValueSet compose (fetched by `fetch_valueset_versions()`, in compose order
   2016 → 2017 → 2018 → 2019 → 2024) and stops at the first `valid=True`. Capture that
   winning version into the row dict (e.g. key `version`; empty string when validation ran
   without a value set or the code is invalid).
2. Add a `version` column to the CSV field list (appears in `validation-*.csv` and
   `unmapped-*.csv`).
3. Extend the `display_map` entries to `{"code": ..., "display": ..., "version": ...}`.
   For the icd9 path (no value set), `version` will be empty — that is fine, the migration
   only reads the icd10 map.
4. Re-run to regenerate the artifacts:
   `python3 scripts/icd-migration/check_icd_codes.py --system icd10 --insecure --valueset "http://mimic.mit.edu/fhir/mimic/ValueSet/mimic-diagnosis-icd10cm"`

## Out of scope

- Any change to the validation/retry logic itself (it works; unmapped is empty).
- The icd9 path beyond not breaking it.
- Uploading anything to the terminology server.
- The PySpark script (step 02).

## Inputs

- `scripts/icd-migration/check_icd_codes.py` — current version already contains
  `fetch_valueset_versions()` and the per-version retry loop.
- Terminology server `https://velonto.dw.csiro.au/fhir` (self-signed cert → `--insecure`),
  ValueSet `http://mimic.mit.edu/fhir/mimic/ValueSet/mimic-diagnosis-icd10cm` pinning
  icd-10-cm versions 2016, 2017, 2018, 2019, 2024.
- Source codes: `input/resources/CodeSystem-mimic-diagnosis-icd10.json` (18,450 concepts,
  dotless).

## Outputs

- Updated `scripts/icd-migration/check_icd_codes.py`.
- Regenerated `scripts/icd-migration/display-map.json` where every entry under
  `http://hl7.org/fhir/sid/icd-10-cm` has non-empty `code`, `display`, `version`.
- Regenerated `validation-icd10.csv` (with version column) and an **empty**
  `unmapped-icd10.csv` (header only).

## Verification

- `unmapped-icd10.csv` contains only the header row.
- Spot-check `display-map.json`:
  - `"A000"` → code `A00.0`, version `2016` (valid in the first probed release);
  - `"T148"` → code `T14.8`, version `2016` (deleted after 2019 — must NOT be 2024);
  - `"D75A"` → code `D75.A`, version `2024` (FY2023 code, only in the 2024 release);
  - `"I4811"` → code `I48.11`, version `2024`.
- All 18,450 icd10 map entries have a non-empty `version`.

## Implementation notes

- Probe order matters for determinism: it is the ValueSet compose order as returned by
  `fetch_valueset_versions()` — do not sort or hardcode it.
- The display returned by `$validate-code` with `systemVersion=<year>` is that release's
  display; keep using it as `official_display` (no separate lookup needed).
- The run makes up to 5 × 18,450 requests through 16 worker threads against velonto and
  takes a few minutes; `--workers` exists if it needs tuning.
