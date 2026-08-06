# RUNBOOK — CSIRO MIMIC-on-FHIR pipeline

This repo is a fork of [kindlab/mimic-profiles](https://github.com/kind-lab/mimic-profiles)
(the MIMIC-on-FHIR IG, upstream v1.3.0) carrying all CSIRO modifications, currently at
IG version **1.4.0-csiro**:

1. **Terminology build** (`scripts/terminology-mapping/`, merged from the former
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
[laptop]  mappings  =  condition ─→ procedure ─→ verify-mappings
              │            (offline; needs the built CodeSystems in output/)
              │            each builder writes its ConceptMap AND its ValueSet
              ▼  … you read <field>-report.json and unmapped-<field>.csv …
[laptop]  upload-mappings   (gated: refuses while any code is unmapped)
              │  ConceptMaps + ValueSets → $ONTOSERVER_URL
              ▼
[node]    read-time translation via ConceptMap/$translate
```

Condition/Procedure codes are **not** rewritten in the warehouse. Translation to
the standard ICD systems is a read-time concern (see §5); the node consumes the
published ConceptMaps rather than a migrated copy of the data.

Artifacts crossing the boundary:

| Artifact | Direction | Note |
|---|---|---|
| `scripts/terminology-mapping/output/ConceptMap-*.json` | laptop → server | the mapping rules, committed; the only place they live |
| `scripts/terminology-mapping/output/ValueSet-mimic-{diagnosis,procedure}.json` | laptop → server | enumerated target value sets, committed |
| `scripts/binding-analysis/work-items.json` | laptop → node | drove the one-time phase-1 extraction |
| `scripts/terminology-mapping/occurrences/{count_occurrences.py,elements.json,count_occurrences.slurm}` | laptop → node | the occurrence count job |
| `scripts/terminology-mapping/occurrences/{code-occurrences.csv,occurrence-summary.json}` | node → laptop | per-code counts, committed; optional input to `make statistics` |

Repeatable stages: `verify-inputs`, `terminology`, `ig`, `deploy-terminology`,
`mappings`, `upload-mappings`. One-time analysis (documented in §5–6, re-runnable
manually but their conclusions are frozen into committed files): binding-analysis
phases 0–2.

## 2. Configuration

Copy `.env.example` to `.env`, adjust, and load with `set -a; source .env; set +a`.
CLI flags on the underlying scripts override the environment.

| Variable | Used by | Meaning |
|---|---|---|
| `ONTOSERVER_URL` | terminology builds, `upload-mappings` | FHIR terminology server base URL. Unset ⇒ builds skip upload |
| `ICD_SOURCE_DIR` | terminology builds, `verify_inputs.py` | directory with the raw ICD distributions, one folder per code system per fiscal year |
| `MIMIC_WAREHOUSE` | `scripts/mimic-pipeline/` | Pathling Delta warehouse path (node) |

Input identity is pinned in `scripts/terminology-mapping/input-manifest.json`
(SHA-256 + size of every source file that influences output, source URLs, MIMIC data
fingerprint). `make verify-inputs` checks a local copy against it.

Make targets (one per stage):

| Target | Where | What |
|---|---|---|
| `verify-inputs` | laptop | hash-check ICD sources against the manifest |
| `terminology` | laptop | build all CodeSystems + ValueSet into `scripts/terminology-mapping/output/` (no upload) |
| `deploy-terminology` | laptop | build **and** upload to `$ONTOSERVER_URL`, incl. `$lookup` smoke tests |
| `ig` | laptop | `sushi` + `./_genonce.sh` → `output/package.tgz` |
| `condition` | laptop | `Condition.code`: ConceptMap + enumerated target ValueSet, one offline pass |
| `procedure` | laptop | `Procedure.code`: same, for the three merged populations |
| `verify-mappings` | laptop | coverage + invariant checks; non-zero while any code is unmapped |
| `mappings` | laptop | every builder, then verify — the everyday command |
| `verify-curated` | laptop | `$lookup` every SNOMED code in the mapping tables (needs the network) |
| `d-items-table` | laptop | regenerate the ICU table from code-search (needs the network; never part of `mappings`) |
| `upload-mappings` | laptop | publish ConceptMaps + ValueSets; gated on `verify-mappings`, override with `ARGS=--allow-unmapped`, TLS flags via `UPLOAD_ARGS` |

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
ICD-9-CM distribution. Layout in `scripts/terminology-mapping/README.md`.

### terminology
`make terminology`. Inputs: verified ICD sources. Outputs:
`scripts/terminology-mapping/output/CodeSystem-icd-9-cm-2012.json`,
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

### mappings
`make mappings`. Runs one builder per bound element, then verifies. Fully offline
and takes seconds — the builders take no `--fhir-base` at all. Inputs: the built
CodeSystems in `output/`, `input/resources/CodeSystem-mimic-*.json`, the
FSH-generated ValueSets, and the committed `conceptmaps/d-items-snomed.csv`.

Each builder writes four files in one pass:
`ConceptMap-<id>.json`, the enumerated `ValueSet-<target id>.json` that map's
`targetCanonical` names, `unmapped-<field>.csv`, and `<field>-report.json`
(coverage in a shape that is comparable across populations). All committed.

Nothing downstream re-derives a mapping — the shared machinery is in
`conceptmaps/lib/`, and the dot rules live only in `lib/notation.py`. See
`scripts/terminology-mapping/README.md`.

**Verify:** all four checks pass — coverage, ValueSet == ConceptMap target side,
only releases built here, and no ICD-9 procedure code mapped to an ICD-10-PCS
grouper. Rebuilds from unchanged inputs are byte-identical, so
`make mappings && git diff --exit-code` is a valid test.

`make statistics` (run by every field target, and last in `mappings`) flattens the
reports into `output/mapping-statistics.{csv,html}`. If
`occurrences/code-occurrences.csv` is present it also weights every coverage
figure by how often each code occurs in the warehouse and writes
`output/occurrence-buckets.csv` — the counts come from the node job in §6, are
committed, and are verified against their summary's sha256, so this stage stays
offline and byte-identical either way. Absent, nothing changes.

### upload-mappings
`make upload-mappings`. Runs `verify-mappings` first and **refuses to publish
while any code is unmapped** — read `unmapped-<field>.csv`, fix the input that is
missing (almost always an unbuilt ICD release), and re-run. Once reviewed,
`make upload-mappings ARGS=--allow-unmapped` publishes anyway; that flag does not
relax the three correctness checks.

Publication is a plain `PUT` by resource id. Nothing is deleted first: CodeSystem
releases deliberately share one canonical URL and differ only by `version`, so a
delete-by-url would take the sibling releases with it.

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
| `scripts/terminology-mapping/occurrences/count_occurrences.py` | node | `code-occurrences.csv`, `occurrence-summary.json` | `sbatch count_occurrences.slurm` on Petrichor — read-only, never writes to the warehouse. Self-contained (stdlib + pathling only) because the node's uv env is Python 3.12, not this repo's 3.14. Full procedure incl. login-node smoke test: `occurrences/README.md`. Re-run only after the warehouse itself changes |
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
