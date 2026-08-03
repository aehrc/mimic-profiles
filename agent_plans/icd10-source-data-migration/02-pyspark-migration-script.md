# Step 02: PySpark migration script for Condition codings

## Goal

Author the script that actually changes the source data: rewrite every ICD-10 coding in
MIMIC-on-FHIR `Condition.code` from the custom dotless MIMIC system to proper ICD-10-CM
with dotted code, official display, and pinned `Coding.version`. It runs on the CSIRO HPC
node (Spark + Delta-format MIMIC-on-FHIR, **no internet**), so it must be fully driven by
the offline `display-map.json` from step 01. The author cannot run it against real data;
Felix executes it on the node.

## Scope

Create `scripts/icd-migration/migrate_condition_codes.py`:

- **Transformation** (per `Condition.code.coding` array element):
  - If `system == "http://mimic.mit.edu/fhir/mimic/CodeSystem/mimic-diagnosis-icd10"`
    and the (dotless) `code` is in the map: replace with
    `system = "http://hl7.org/fhir/sid/icd-10-cm"`, `code = <dotted>`,
    `display = <official display>`, `version = <pinned release year>`.
  - If the system matches but the code is NOT in the map: do not rewrite; count it and
    write the distinct offenders to an output file; nonzero offenders → exit nonzero
    (expected to be zero — unmapped-icd10.csv was empty on 2026-07-16).
  - Any other coding (ICD-9 custom system, or anything else): pass through byte-identical.
- **Map loading**: read `display-map.json` (path via CLI flag, default the file next to
  the script), take the `http://hl7.org/fhir/sid/icd-10-cm` sub-map, broadcast it.
  Refuse to start if any entry lacks a non-empty `version` (guards against running with a
  stale pre-step-01 map).
- **CLI / environment** (mirror `scripts/binding-analysis/phase1_extract_distinct.py`):
  - flags for the warehouse/Condition-table location — do NOT hardcode node paths;
  - `--output` for the write-back target, defaulting to writing a **migrated copy**
    (never overwrite in place unless an explicit `--in-place`-style flag is passed —
    write-back mode is an open decision Felix makes at run time);
  - `--dry-run` prints the planned read/transform/write without importing pyspark;
  - a `--limit`/sample flag so Felix can trial-run on a few rows first.
- **Reporting**: end-of-run counts — Condition rows scanned, codings rewritten, codings
  passed through by system, unmapped offenders — printed and written to a small JSON
  summary next to the output.

## Out of scope

- Modifying `check_icd_codes.py` or `display-map.json` (step 01 owns those).
- ICD-9 codings — pass through untouched.
- Other resource types or elements (only `Condition.code.coding`).
- IG profile/binding changes (`Condition` profile still binds the old VS; that is a
  separate task).
- Running against real data — cannot be done off the node.

## Inputs

- `scripts/icd-migration/display-map.json` — step 01 output:
  `{ "http://hl7.org/fhir/sid/icd-10-cm": { "<dotless>": {"code","display","version"}, ... }, ... }`.
- `scripts/binding-analysis/phase1_extract_distinct.py` — the established conventions for
  node scripts (flag-driven env, dry-run without pyspark, defensive error handling).
- `MODIFICATION_PLAN.md` — background on the node setup (PathlingContext must own the
  SparkSession if pathling is used; plain Spark/Delta is fine for this job and preferred —
  no FHIRPath needed for a structural rewrite).

## Outputs

- `scripts/icd-migration/migrate_condition_codes.py` — the node-ready script.
- A short usage section either as module docstring or appended README note in
  `scripts/icd-migration/`, including the exact command Felix should run first
  (`--dry-run`, then `--limit` trial, then full run).

## Verification

The script cannot touch real data here, so verification is local:

- `python3 scripts/icd-migration/migrate_condition_codes.py --dry-run ...` runs on a
  machine **without pyspark installed** and prints the plan.
- Unit-style self-test (e.g. `--self-test` flag or a small `if __name__` test path) that
  feeds a handful of synthetic Condition JSON rows through the transformation function
  (pure-Python, no Spark) and asserts:
  - dotless ICD-10 coding → rewritten with dotted code + version (e.g. `T148` →
    `T14.8`/`2016`, `D75A` → `D75.A`/`2024`, using the real display-map);
  - ICD-9 coding and non-MIMIC systems pass through unchanged;
  - unknown ICD-10 code is counted as an offender, not rewritten.
- Stale-map guard: running with a version-less map entry aborts with a clear message.

## Implementation notes

- Keep the dot-insertion rule out of this script entirely — the map's dotted `code` field
  is authoritative (single source of truth already lives in `check_icd_codes.py`'s
  `convert_icd10`; do not duplicate the logic, just consume the map).
- The transformation should be expressible as a pure function
  `migrate_coding(coding: dict, icd10_map: dict) -> (dict, status)` used by both the Spark
  UDF/`transform` path and the self-test — that is what makes it testable off-node.
- Delta/Spark specifics on the node (Spark version, table vs. path access) are unknown
  from this repo; expose them as flags with sensible defaults and document assumptions in
  the docstring rather than guessing silently.
- `Coding.version` for `http://hl7.org/fhir/sid/icd-10-cm` is the release year string
  (`"2016"` … `"2024"`), exactly as stored in the map — no reformatting.
