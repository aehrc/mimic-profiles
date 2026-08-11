# Occurrence counts

How often every coded value actually occurs in the full MIMIC-on-FHIR
warehouse, so the mapping coverage tables can be weighted by data volume.
Coverage over *codes* answers "how much of the dictionary did we map"; coverage
over *occurrences* answers "how likely is a data point I meet to carry an
unmapped code", and the gap between the two is the interesting part — 80% of
codes mapped but 50% of rows means the frequent codes are the unmapped ones.

Committed artefacts, produced by one HPC run and then never regenerated until
the warehouse itself changes:

| File | What |
|---|---|
| `code-occurrences.csv` | `element,system,code,display,occurrences` — every distinct coded value, with its row count |
| `element-shapes.csv` | `element,shape,resources` — for a CHOICE element, how many resources took each branch. Only for elements declaring `count_shapes` |
| `reference-occurrences.csv` | `element,via,system,code,display,resources` — codes reached by following a Reference, counted once per *referring* resource. Only for elements declaring `reference_join` |
| `occurrence-summary.json` | per-element totals plus the run's identity: Delta version + commit timestamp per table, host, versions, and the sha256 of each CSV |
| `elements.json` | the registry both sides read: resource type + FHIRPath for the node, bound ValueSets for the local classification |

`build_statistics.py` verifies the CSV against `csv_sha256` before using it, so
a half-copied or hand-edited file cannot quietly enter a thesis table. Without
these files present, `make statistics` behaves exactly as it did before them.

## A coding count is not a resource count

`code-occurrences.csv` counts **codings**, and on a choice element that is not
the same population as the resources. `MedicationRequest.medication[x]` is
`CodeableConcept | Reference(Medication)`, and only the CodeableConcept branch
carries a Coding — so the 2026-08-06 run recorded 1,883,681 codings against
15,416,901 MedicationRequest rows. At least 87.8% of prescriptions carry their
drug identity on `Medication.code`, reached through the reference, and a
coverage percentage over the codings alone reads as a statement about
prescriptions when it is a statement about one branch of one element.

That is what the two side files exist for, and why `Medication.code` is in the
registry at all. `element-shapes.csv` says how the choice was actually taken;
`reference-occurrences.csv` follows the reference so resource-level reachability
can be computed. Note also that a `required` binding on a choice element **cannot
constrain the Reference branch** — a validator has nothing coded to check — so
for most MIMIC prescriptions the terminology guarantee is carried entirely by
`Medication.code`'s own binding.

A useful by-product: `with_codeable_concept` true together with `with_coding`
false is a CodeableConcept carrying `text` and no `Coding`. Under a required
binding on the whole CodeableConcept that is non-conformant, and the summary
reports it as `codeable_concept_without_coding`. On
`MedicationStatement.medication[x]` it is expected and legal, because that
profile binds the coding *slices* rather than the CodeableConcept.

## Not every element's count is data volume

`Medication.code` is in the registry and is counted, but its counts are the
**size of the drug dictionary**, not data volume. MIMIC mints one `Medication`
per distinct `(drug, gsn, ndc, formulary_drug_cd)` tuple — `drug_code` converted
to UUID5, see `input/includes/map-medicationrequest.md` — so a code used on ten
thousand prescriptions still occurs about once there. It is counted anyway
because `observed_only` needs to know which codes appear *at all*, and because
dictionary reachability is worth reporting.

`occurrence_kind` marks the distinction and `build_statistics.py` reports the two
in separate tables. The volume question for a dictionary element is answered by
`reference-occurrences.csv`, which counts its codes once per *referring*
resource — that figure is comparable with the event elements, and the dictionary
count is not.

Related: do not sum `occurrences` across elements. The same drug-name code is
counted on `MedicationRequest.medication[x]`, `MedicationDispense.medication[x]`,
`MedicationAdministration.medication[x]` and `Medication.code`, because each is a
separate binding with its own map. Per-element is the only level at which the
numbers mean anything.

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
  --exclude 'occurrence-summary.json' --exclude 'element-shapes.csv' \
  --exclude 'reference-occurrences.csv' --exclude README.md \
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
  nau025@petrichor.hpc.csiro.au:/scratch3/nau025/mimic-on-fhir-delta/occurrences/element-shapes.csv \
  nau025@petrichor.hpc.csiro.au:/scratch3/nau025/mimic-on-fhir-delta/occurrences/reference-occurrences.csv \
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
states separated by a provisioning step, so all ten elements are recounted
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
