# Occurrence counts

How often every coded value actually occurs in the full MIMIC-on-FHIR
warehouse, so the mapping coverage tables can be weighted by data volume.
Coverage over *codes* answers "how much of the dictionary did we map"; coverage
over *occurrences* answers "how likely is a data point I meet to carry an
unmapped code", and the gap between the two is the interesting part — 80% of
codes mapped but 50% of rows means the frequent codes are the unmapped ones.

Two committed files, produced by one HPC run and then never regenerated until
the warehouse itself changes:

| File | What |
|---|---|
| `code-occurrences.csv` | `element,system,code,display,occurrences` — every distinct coded value, with its row count |
| `occurrence-summary.json` | per-element totals plus the run's identity: Delta version + commit timestamp per table, host, versions, and the sha256 of the CSV |
| `elements.json` | the registry both sides read: resource type + FHIRPath for the node, bound ValueSets for the local classification |

`build_statistics.py` verifies the CSV against `csv_sha256` before using it, so
a half-copied or hand-edited file cannot quietly enter a thesis table. Without
these files present, `make statistics` behaves exactly as it did before them.

## Re-running it on the node

Cluster conventions (account, modules, no internet on compute nodes, no
polling) come from the `csiro-hpc` and `hpc-transfer` skills — defer to those
for anything not stated here.

```bash
# 1. Dry run locally first: prints the planned views, imports no Spark.
uv run scripts/terminology-mapping/occurrences/count_occurrences.py --dry-run

# 2. Stage to scratch3 (script + registry + slurm only; outputs come back later).
ssh nau025@petrichor.hpc.csiro.au 'mkdir -p /scratch3/nau025/mimic-on-fhir-delta/occurrences'
rsync -av --exclude __pycache__ --exclude 'code-occurrences.csv' \
  --exclude 'occurrence-summary.json' --exclude README.md \
  scripts/terminology-mapping/occurrences/ \
  nau025@petrichor.hpc.csiro.au:/scratch3/nau025/mimic-on-fhir-delta/occurrences/

# 3. Smoke test on the LOGIN node — cheap, and catches env drift before a job
#    burns a queue slot. Do not create a PathlingContext here (heavy JVM).
ssh nau025@petrichor.hpc.csiro.au 'bash -lc "
  module load python/3.12.3 amazon-corretto/21.0.0.35.1 &&
  cd /scratch3/nau025/mimic-on-fhir-delta &&
  test -d spark_warehouse && echo warehouse OK &&
  uv run python3 -c \"from pathling import PathlingContext; print(0)\" &&
  uv run python3 occurrences/count_occurrences.py --dry-run >/dev/null &&
  echo dry-run OK
"'

# 4. Submit. Status arrives by email (BEGIN/END/FAIL) — do not poll.
ssh nau025@petrichor.hpc.csiro.au \
  'cd /scratch3/nau025/mimic-on-fhir-delta/occurrences && sbatch count_occurrences.slurm'

# 5. Fetch back (no --delete: never remove committed artefacts).
rsync -av \
  nau025@petrichor.hpc.csiro.au:/scratch3/nau025/mimic-on-fhir-delta/occurrences/code-occurrences.csv \
  nau025@petrichor.hpc.csiro.au:/scratch3/nau025/mimic-on-fhir-delta/occurrences/occurrence-summary.json \
  scripts/terminology-mapping/occurrences/

# 6. Then, locally:
make statistics
```

The job is **read-only** — it never writes to the warehouse. That is the
difference from `merged_profile_provisioning`, which does.

## Why not the artefacts that already exist

`scripts/binding-analysis/distinct-codes.ndjson` already has counts in its `n`
column, and this script's query shape is lifted from
`phase1_extract_distinct.py`. But phase 0 filtered its work items to elements
that were *not* already bound, which excludes the three elements this repo maps
most: `Observation.code`, `Procedure.code` and `Specimen.type`. Topping that
file up would leave the statistics citing two extraction runs against warehouse
states separated by a provisioning step, so all seven elements are recounted
here in one job with one provenance record. `distinct-codes.ndjson` stays what
it is: evidence for the July binding analysis.

`pathling_mcp_tool`'s `get_cardinality_and_top_values_impl` was the other
candidate. It caps results at 20 values, which is useless for a field whose
whole story is its long tail, and it explodes several array columns
independently — cross-joining the codings of a multi-coding CodeableConcept
rather than keeping them aligned. The SQL-on-FHIR `forEach` used here gets that
right by construction.

## What is deliberately not in the artifact

**No `meta.profile` column.** A resource may carry more than one profile, so
grouping on an exploded `meta.profile` would count its codings once per
profile. Population identity survives without it: each unbuilt population has
its own CodeSystem (`mimic-chartevents-d-items`, `mimic-d-labitems`,
`mimic-microbiology-organism`), so a code's system already says which
population it came from.

**No patient or encounter counts.** Considered and rejected: the metric is "how
likely is a data point to carry an unmapped code", which is rows by definition,
and a patient count never enters it.
