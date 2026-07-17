# RUNBOOK — CSIRO MIMIC-on-FHIR pipeline

This repo is a fork of [kindlab/mimic-profiles](https://github.com/kind-lab/mimic-profiles)
(the MIMIC-on-FHIR IG, upstream v1.3.0) carrying all CSIRO modifications, currently at
IG version **1.4.0-csiro**:

1. **Terminology build** (`scripts/terminology-build/`, merged from the former
   `update-mimic-terminology` repo): FHIR R4 CodeSystems for ICD-9-CM 2012 and
   ICD-10-CM 2016–2019 plus the `mimic-diagnosis` ValueSet, generated from CMS/CDC
   source distributions.
2. **Required terminology bindings** on 12+ profile elements, derived from a coverage
   analysis of the **full** MIMIC-on-FHIR dataset (`scripts/binding-analysis/`).
3. **Condition.code migration** of the source data from the custom dotless MIMIC ICD
   CodeSystems to standard `icd-9-cm`/`icd-10-cm` with dotted codes, official displays,
   and pinned `Coding.version` (`scripts/icd-migration/`).

This document is the authoritative narrative and operating manual. It supersedes the
former `NOTES.md` and `MODIFICATION_PLAN.md`.

## 1. Pipeline DAG

Two environments, with a hard boundary:

- **Laptop** — internet, uv-managed Python, Java/SUSHI/Jekyll, reachability to the
  terminology server (`$ONTOSERVER_URL`, e.g. `https://velonto.dw.csiro.au/fhir`).
- **HPC node** — holds the full MIMIC-on-FHIR Pathling Delta warehouse
  (`$MIMIC_WAREHOUSE`); Spark + Pathling available; **no internet, no terminology
  server**. Everything the node needs must be carried in as committed files.

```
[laptop]  verify-inputs ─→ terminology ─→ deploy-terminology ──┐
[laptop]  ig (sushi + _genonce.sh) ─→ package upload ──────────┤
                                                               ▼
[laptop]  check-codes (one-time analysis; needs deployed terminology)
              │  produces scripts/icd-migration/display-map.json (committed)
              ▼  … carried to the node via this repo …
[node]    migrate ─→ verify-migration ─→ migrated Condition data handoff
```

Artifacts crossing the boundary:

| Artifact | Direction | Note |
|---|---|---|
| `scripts/icd-migration/display-map.json` | laptop → node | complete offline map: dotless code → dotted code, official display, pinned version |
| `scripts/binding-analysis/work-items.json` | laptop → node | drove the one-time phase-1 extraction |
| `distinct-codes.ndjson`, `migration-report.json` | node → laptop | evidence, committed |

Repeatable stages: `verify-inputs`, `terminology`, `ig`, `deploy-terminology`,
`migrate`, `verify-migration`. One-time analysis (documented in §5–6, re-runnable
manually but their conclusions are frozen into committed files): binding-analysis
phases 0–2, `check-codes`.

## 2. Configuration

Copy `.env.example` to `.env`, adjust, and load with `set -a; source .env; set +a`.
CLI flags on the underlying scripts override the environment.

| Variable | Used by | Meaning |
|---|---|---|
| `ONTOSERVER_URL` | terminology builds (upload step), `check_icd_codes.py` | FHIR terminology server base URL. Unset ⇒ builds skip upload; check-codes refuses to run |
| `ICD_SOURCE_DIR` | terminology builds, `verify_inputs.py` | directory with the raw ICD distributions (`2012_icd9/`, `2016/`…`2019/`) |
| `MIMIC_WAREHOUSE` | `migrate_condition_codes.py`, `verify_migration.py` | Pathling Delta warehouse path (node) |

Input identity is pinned in `scripts/terminology-build/input-manifest.json`
(SHA-256 + size of every source file that influences output, source URLs, MIMIC data
fingerprint). `make verify-inputs` checks a local copy against it.

Make targets (one per stage):

| Target | Where | What |
|---|---|---|
| `verify-inputs` | laptop | hash-check ICD sources against the manifest |
| `terminology` | laptop | build all CodeSystems + ValueSet into `scripts/terminology-build/output/` (no upload) |
| `deploy-terminology` | laptop | build **and** upload to `$ONTOSERVER_URL`, incl. `$lookup` smoke tests |
| `ig` | laptop | `sushi` + `./_genonce.sh` → `output/package.tgz` |
| `check-codes` | laptop | validate distinct MIMIC ICD codes against the server, regenerate `display-map.json` (one-time; see §6) |
| `migrate` | node | rewrite Condition codings per `display-map.json` (`MIGRATED_OUT`, default `transformed_data`) |
| `verify-migration` | node | independent row-by-row re-derivation check of the migrated table |

## 3. Toolchain

| Tool | Version used | Provenance |
|---|---|---|
| Python | 3.14 (`.python-version`), deps pinned in `uv.lock` (`pathling`, `striprtf`) | `uv sync` |
| SUSHI | 3.20.0 (FSH spec 3.0.0) | npm |
| IG Publisher | 2.2.10 | `_updatePublisher.sh` downloads the **latest** release into `input-cache/publisher.jar` — record the version on rebuilds (`java -jar input-cache/publisher.jar -v`) |
| Java | OpenJDK 21.0.11 (Zulu) | — |
| Jekyll | 4.4.1 | brew/gem (required by the publisher) |
| Ontoserver (server-side) | 6.27.3-SNAPSHOT, FHIR 4.0.1 | velonto.dw.csiro.au |
| Spark/Pathling (node) | Pathling ≥ 7 (uses `view()`, not `extract()`) | node modules |

## 4. Stage details

### verify-inputs
`make verify-inputs`. Inputs: `$ICD_SOURCE_DIR`. Verification is the stage: all 10
files must report `ok`. Sources: CMS ICD-10-CM yearly downloads
(<https://www.cms.gov/medicare/coding-billing/icd-10-codes>), CDC/CMS FY2012 (v29)
ICD-9-CM distribution. Layout in `scripts/terminology-build/README.md`.

### terminology
`make terminology`. Inputs: verified ICD sources. Outputs:
`scripts/terminology-build/output/CodeSystem-icd-9-cm-2012.json`,
`CodeSystem-icd-10-cm-{2016..2019}.json` (gitignored, ~36 MB each),
`ValueSet-mimic-diagnosis.json` (committed).
**Verify:** byte-diff against the release assets (§7); the only legitimate diff is the
ValueSet's `date` field (stamped with the build date). The ICD-9 RTF conversion is
pure-Python (`striprtf`), proven byte-identical to the original macOS `textutil` path.

### ig
`make ig`. Compiles `input/fsh/` with SUSHI, then `./_genonce.sh` runs the IG
Publisher with `-tx https://velonto.dw.csiro.au/fhir` and a custom Java truststore
(§8). Only the publisher merges `input/resources/` (34 VS + 39 CS JSON) with the
FSH-compiled artifacts — all tooling must read `output/package.tgz`, never
`fsh-generated/` alone. Output: `output/package.tgz` (42+ VS, 39 CS, 27 SD at
1.4.0-csiro) and the QA report `output/qa.html`.
**Verify:** publisher QA report sane (no new errors vs. previous build);
`validator_cli` passes on the IG examples.

### deploy-terminology
`make deploy-terminology`. Uploads the 5 CodeSystems + `mimic-diagnosis` ValueSet to
`$ONTOSERVER_URL` and runs built-in `$lookup` smoke tests (the ICD-9 script also
deletes the superseded old ValueSet id).
**Verify:** smoke tests pass (nonzero exit otherwise).

The **IG package upload** (package.tgz → server) was performed by the terminology
server admin / manual FHIR upload, not by a script in this repo.
**Verify:** the checks recorded in `upload-verification-report.md` — resource counts
per type at the new version, `$expand` on `mimic-medication-with-unknown`,
`$validate-code` on `v3-NullFlavor#UNK`, `$lookup` spot-checks on admission-class/type.

### migrate (node)
`make migrate` (or explicit: `uv run scripts/icd-migration/migrate_condition_codes.py
--data $MIMIC_WAREHOUSE --output <dir> [--format delta|ndjson] [--dry-run] [--limit N]`).
Fully offline: consumes only the committed `display-map.json`. Rewrites codings on the
two custom systems to `http://hl7.org/fhir/sid/icd-{9,10}-cm`; everything else passes
through byte-identical. Fails loudly on unmapped codes (drift guard) rather than
passing them through. Defaults to writing a migrated copy; in-place requires
`--overwrite` with `--output` = `--data`.
**Verify:** `migration-report.json` shows `"ok": true`, zero
`residual_source_system_codings`, and before/after coding counts that reconcile
(see §5 for the accepted ±5 false-flag delta). Then run `make verify-migration`.

### verify-migration (node)
`make verify-migration`. Independent of the migration script's own bookkeeping:
re-derives the expected result from `display-map.json` and compares row by row —
id-set equality, zero residual custom-system codings, exact rewrite per map, non-MIMIC
codings byte-identical, coding order preserved, all ICD-9 pins = 2012.

## 5. What was changed and why (provenance)

### Version history
| Version | Meaning |
|---|---|
| 1.3.0 | upstream kindlab release (baseline) |
| 1.3.0-csiro.1 | fork bump so the unmodified rebuild is distinguishable on the terminology server (canonical URLs unchanged) |
| 1.4.0-csiro | bindings applied + Condition.code rebind; uploaded and verified 2026-07-13 (`upload-verification-report.md`) |

### Binding analysis (commit `433aca1`)
Evidence-driven: a field got a `required` binding only if the full MIMIC-on-FHIR data
was covered by the ValueSet ((system, code) membership, offline against
`package.tgz`). Pipeline: 131 candidate elements from package snapshots
(`work-items.json`) → Spark/Pathling distinct-code extraction on the node, partitioned
by `meta.profile` (38,102 distinct codes, `distinct-codes.ndjson`) → offline coverage
cross-check (`binding-report.{json,md}`). Of 131 candidates, 120 had no data; the 11
populated fields resolved as 4 bind / 1 repair→bind / 4 external-terminology /
2 no-binding. Decisions (full detail in `scripts/binding-analysis/FINDINGS.md`):

- **D1**: 8 required bindings applied; micro-test binds `valueCodeableConcept` only
  (not `value[x]`) so free-text results stay valid, using the standard `v3-NullFlavor` VS.
- **D2**: admin-hosp's single gap (`v3-NullFlavor#UNK`, 931 of 27.7M rows — intentional
  upstream ETL null-flavor) fixed via new wrapper VS `mimic-medication-with-unknown`
  (includes `mimic-medication` + `UNK`), bound on that profile only; the shared VS
  stays strict so UNK elsewhere signals an ETL regression.
- **D3**: medication-statement-ed gets **per-slice** bindings (GSN, ETC) with closed
  slicing instead of a merged VS; the NDC slice stays unbound (no server hosts the NDC
  CodeSystem; the slice still pins the system URI). ~68% of medrecon rows are
  text-only — a required CodeableConcept binding would have invalidated them.
- **D4**: vital-signs `component.code` bound to a new two-code VS
  `mimic-observation-component-vital` (BP LOINCs 8480-6/8462-4) rather than polluting
  the shared `mimic-observation-type-vital`.

Consumer note: bindings differ per profile on the same element (e.g.
`Observation.value[x]`), so downstream field→VS resolution must key on
`meta.profile`, never resource type alone; `binding-report.json` is the
machine-readable record including the 120 no-data elements.

### Condition.code migration (commit `e1f48e6`)
Motivation: the data carried custom dotless CodeSystems
(`mimic-diagnosis-icd{9,10}`); validation and mapping need the standard systems.
`Coding.version` is **pinned in the data** to the first ICD release year in which the
code validates (probe order = the ValueSet compose order), because Ontoserver 6.27
`$validate-code` checks a version-less coding against only one arbitrary version of a
multi-version ValueSet. Pinning makes every downstream `$validate-code` a single
direct call. Displays come from the pinned version.

Run on the full dataset (2026-07-16, `scripts/icd-migration/migration-report.json`):
5,655,376 Condition rows; 18,190 + 9,379 distinct source codes. Codings after:
2,445,489 on `icd-10-cm` (2016: 2,392,914, 2017: 37,818, 2018: 11,392, 2019: 2,864,
2024: 501) and 3,209,887 on `icd-9-cm` (all pinned 2012). Zero residual
custom-system codings; zero unmapped.

**False flags**: some codes labeled ICD-9 in MIMIC are actually ICD-10-CM (e.g.
`I50.9`, `J45.901`, `O86.12`, `R27.0`, `S01.312A`, `W01.190A`). `check_icd_codes.py`
detects these and `display-map.json` records them as moves; hence the ±5 asymmetry
between the icd9 before-count (3,209,892) and after-count, matched by +5 on icd10.
`display-map.json` is the committed decision record for every rewrite and relabel.

IG side: `Condition.code` re-bound from the custom `$MimicDiagnosisIcd` VS to the new
merged `mimic-diagnosis` ValueSet (includes both standard ICD systems, versions
pinned).

### Upload verification (2026-07-13)
All 27 SDs, 44 VS, 39 CS present at 1.4.0-csiro on velonto; `$expand`,
`$validate-code`, `$lookup` all functional; versions 1.3.0 / 1.3.0-csiro.1 /
1.4.0-csiro coexist on the server. Details: `upload-verification-report.md`.

## 6. One-time analysis scripts (frozen conclusions, manually re-runnable)

These produced the committed decision files. Re-running is possible but not part of
the reproduction path — the pipeline rebuilds from their committed outputs.

| Script | Runs on | Produces | Re-run |
|---|---|---|---|
| `scripts/binding-analysis/phase0_candidates.py` | laptop | `work-items.json` (131 candidates) | needs a built `output/package.tgz` |
| `scripts/binding-analysis/phase1_extract_distinct.py` | node | `distinct-codes.ndjson`, `extract-summary.json` | `uv run … --data $MIMIC_WAREHOUSE` (see `--help`); PathlingContext must own the SparkSession; Pathling 7+ `view()` not `extract()` |
| `scripts/binding-analysis/phase2_crosscheck.py` | laptop | `binding-report.{json,md}` | offline, stdlib-only over package.tgz + distinct-codes |
| `scripts/icd-migration/check_icd_codes.py` | laptop | `display-map.json`, `validation-*.csv`, `unmapped-*.csv` | `make check-codes` — requires the terminology deployed first (`deploy-terminology` + package upload); `--insecure` available for cert issues. `display-map.json` is already committed; regenerate only after a terminology change, and confirm `unmapped-*.csv` stay empty |

Current findings state: FINDINGS.md — all decisions D1–D4 resolved 2026-07-10 and
applied; binding-report.md — final coverage evidence; `unmapped-icd{9,10}.csv` — empty
(all codes resolve).

## 7. Releases

One git tag per IG version (`v1.4.0-csiro`, …) on the commit that built it. The GitHub
release attaches what git doesn't carry:

- `CodeSystem-icd-9-cm-2012.json`, `CodeSystem-icd-10-cm-{2016,2017,2018,2019}.json`
- `output/package.tgz` (the built IG package)
- `SHA256SUMS` over the assets

Reproduce: checkout the tag → `make verify-inputs` → `make terminology` / `make ig` →
diff outputs against the assets (expected diffs: ValueSet `date`; package.tgz embeds
build timestamps — compare its contents, not the archive bytes).

## 8. Known caveats

- **Truststore for the IG publisher**: velonto's TLS cert chains to the CSIRO internal
  CA, which Java doesn't trust by default. `_genonce.sh` passes
  `-Djavax.net.ssl.trustStore=input-cache/velonto-truststore.jks` (password
  `changeit`). The store is the JDK `cacerts` plus the velonto chain; it is not
  committed (lives in gitignored `input-cache/`). Rebuild it with:
  `cp $JAVA_HOME/lib/security/cacerts input-cache/velonto-truststore.jks &&
  openssl s_client -connect velonto.dw.csiro.au:443 -showcerts </dev/null |
  awk '/BEGIN CERT/,/END CERT/' > /tmp/velonto-chain.pem &&
  keytool -importcert -noprompt -alias velonto -file /tmp/velonto-chain.pem
  -keystore input-cache/velonto-truststore.jks -storepass changeit`
- **Uploads are gated on `ONTOSERVER_URL`**: terminology builds skip upload when it is
  unset; `check_icd_codes.py` refuses to run.
- **The HPC node has no internet**: node stages consume only committed files; don't
  add server calls to node-side scripts.
- **ICD-10-CM 2024** appears in the version pins (501 codings) but is **not built by
  this repo** — the 2024 CodeSystem was already present on velonto. A from-scratch
  server rebuild must load ICD-10-CM 2024 from elsewhere or those codings won't
  validate.
- **`_updatePublisher.sh` pulls the latest publisher** (no version pin) — record the
  version it fetched (currently 2.2.10) when rebuilding the IG.
- **`Requirements-fromNarrative.json`** (repo root, untracked) is referenced nowhere
  and its origin is unclear — left for Felix to keep or delete.
- **IG package upload is not scripted** — it was done server-side by the admin;
  §4 deploy-terminology covers only CodeSystems/ValueSet.
