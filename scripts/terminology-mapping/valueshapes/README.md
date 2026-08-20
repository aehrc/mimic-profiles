# Observation value shapes

What SHAPE of value each coded Observation element — `Observation.code` and
`Observation.component.code` — actually carries in the full MIMIC-on-FHIR
warehouse, so a mapping can be checked against the data rather than only against
the terminology.

The chartevents gate asserts that a proposed target is in the constraint, exists,
is active, and has a confirmed display. None of those can see the defect that
dominates the stream: a target whose SCALE contradicts the data. Measured on the
demo warehouse over the 160 highest-occurrence committed LOINC mappings, 19
(12%, 12.8M occurrences) name a code whose `SCALE_TYP` disagrees with what MIMIC
records — including the one case `build_chartevents_table.py` had already found
by hand, and the `GU = Guiding` abbreviation defect its docstring argues no
template can fix:

| item | committed target | LOINC | MIMIC records |
|---|---|---|---|
| `223907 Pupil Size Right` | `8642-1` \|Right pupil Diameter Auto\| | `Qn` | `3mm, 2mm, 4mm, 5mm, Pinpoint` (7 values) |
| `224017 GU Catheter Size` | `78945-3` \|Guiding catheter size\| | `Qn` | `14 French … Coude Catheter` (7 values) |
| `223792 Pain Management` | `34858-1` \|Pain medicine Note\| | `Doc` | `Repositioned, Backrub, IV Push` (15 values) |

A `SCALE_TYP` of `Doc` or `-` is never a legal `Observation.code` target for a
flowsheet value, and none of this needs an LLM, a threshold, or a per-item
judgement — it is decidable from data plus a `$lookup`.

**This is a gate input, not a search input.** Feeding the value domain into the
code-search query text was tried and rejected: it fixes real defects
(`224650 Ectopy Type 1` → `76281-5 |Type of arrhythmia on EKG|` at 0.85, from
no-match in both systems) but disturbs two correct controls and compresses
confidences toward 0.85 — the same failure that rejected the category-injected
templates T1 and T2. The domain is recorded here so a deterministic check can
use it; whether any query ever sends it is a separate decision needing its own
evidence.

Three committed files, produced by one HPC run and then never regenerated until
the warehouse itself changes:

| File | What |
|---|---|
| `observation-value-shapes.csv` | one row per code: the per-value\[x\] counts, `shape`, `scale_hint`, `distinct_values`, `domain_truncated`, `units`, `units_ucum` |
| `observation-value-domains.csv` | one row per (code, value): `rank`, `value`, `occurrences` — long format, so a value containing a comma needs no escaping scheme |
| `value-shape-summary.json` | per-element totals plus the run's identity: Delta version + commit timestamp, host, versions, the caps in force, and the sha256 of both CSVs |

`scale_hint` is the field a consumer compares against LOINC's `SCALE_TYP`:
`Qn`, `NomOrd`, `Nar`, or blank. Blank is deliberately unusable — a mixed-shape
item is one a human should read, not one a gate should decide from. The rule is
stated in the script's docstring and its thresholds are arguments, so it can be
moved with evidence rather than by taste.

Caps are recorded, never silent: `--top-values` (40) bounds the domain rows per
code and `--max-value-chars` (200) bounds the grouping key. Both land in the
summary, and any code whose domain was cut carries `domain_truncated`.

`Observation.component.code` **is** included, since 2026-08-20. Component values
live at `component.value[x]` paired with `component.code` inside the same array
element, so it is planned as a `forEach` over `component` carrying the value
columns with the coding `forEach` nested inside — `VALUE_SCOPES` in the script,
checked against `elements.json` so the scope and the coding path cannot drift
apart silently.

It was originally excluded as 2 codes at 100% coverage, i.e. machinery for
nothing. That is still true of its coverage and was not why it came back: the
BP components carry `mm[Hg]`, already UCUM, which is a **target** of
`mimic-units-to-ucum` and not a source, so `$translate` returns no match and the
units on ~2M of the largest coded Observation population are unreachable by any
arm of that map. Scoping the UCUM identity group that fixes it needs an
enumeration of what the ETL emits, and nothing enumerated component units. The
flat view could not have: it reads `Observation.value[x]`, empty on a BP panel,
so it would have recorded 2 codes with no units at all and called that an
answer.

`units_ucum` is the column that makes that population readable, and it is read
from `Quantity.system`, not from the spelling. MIMIC writes the raw source
string into **both** `unit` and `code` and declares `mimic-units`, so the
`unit|code` label in `units` never fires there and every entry reads as "code
unknown". Where the ETL has normalised, it declares UCUM — but may still write
one string to both fields, as the components do. Those two cases are
indistinguishable by label and opposite in meaning. On the demo warehouse four
`Observation.code` codes declare UCUM and only three have differing
`unit`/`code`; `2708-6 Oxygen saturation` writes `%` to both and had been
indistinguishable from the MIMIC source string `%`.

## Re-running it on the node

Cluster conventions (account, modules, no internet on compute nodes, no
polling) come from the `csiro-hpc` and `hpc-transfer` skills — defer to those
for anything not stated here. Mirrors `occurrences/` exactly, including reading
that directory's `elements.json` so the two jobs cannot disagree about the
coding path.

```bash
# 1. Dry run locally first: prints the planned view, imports no Spark.
uv run scripts/terminology-mapping/valueshapes/extract_value_shapes.py --dry-run

# 1b. Optional but worth it — smoke test the FHIRPath against the demo
#     warehouse locally. This is what caught Pathling rejecting `|` across
#     value.ofType(Period) and value.ofType(Range).
uv run --with pathling \
  scripts/terminology-mapping/valueshapes/extract_value_shapes.py \
  --data /Users/nau025/warehouses/mimic-iv-demo/delta --out-dir /tmp/vs

# 2. Stage to scratch3 (script + slurm only; outputs come back later).
ssh nau025@petrichor.hpc.csiro.au 'mkdir -p /scratch3/nau025/mimic-on-fhir-delta/valueshapes'
rsync -av --exclude __pycache__ \
  --exclude 'observation-value-shapes.csv' \
  --exclude 'observation-value-domains.csv' \
  --exclude 'value-shape-summary.json' --exclude README.md \
  scripts/terminology-mapping/valueshapes/ \
  nau025@petrichor.hpc.csiro.au:/scratch3/nau025/mimic-on-fhir-delta/valueshapes/

# 3. Smoke test on the LOGIN node — cheap, and catches env drift before a job
#    burns a queue slot. Do not create a PathlingContext here (heavy JVM).
ssh nau025@petrichor.hpc.csiro.au 'bash -lc "
  module load python/3.12.3 amazon-corretto/21.0.0.35.1 &&
  cd /scratch3/nau025/mimic-on-fhir-delta &&
  test -d spark_warehouse && echo warehouse OK &&
  test -f occurrences/elements.json && echo registry OK &&
  uv run python3 -c \"from pathling import PathlingContext; print(0)\" &&
  uv run python3 valueshapes/extract_value_shapes.py --dry-run >/dev/null &&
  echo dry-run OK
"'

# 4. Submit. Status arrives by email (BEGIN/END/FAIL) — do not poll.
ssh nau025@petrichor.hpc.csiro.au \
  'cd /scratch3/nau025/mimic-on-fhir-delta/valueshapes && sbatch extract_value_shapes.slurm'

# 5. Fetch back (no --delete: never remove committed artefacts).
rsync -av \
  nau025@petrichor.hpc.csiro.au:/scratch3/nau025/mimic-on-fhir-delta/valueshapes/observation-value-shapes.csv \
  nau025@petrichor.hpc.csiro.au:/scratch3/nau025/mimic-on-fhir-delta/valueshapes/observation-value-domains.csv \
  nau025@petrichor.hpc.csiro.au:/scratch3/nau025/mimic-on-fhir-delta/valueshapes/value-shape-summary.json \
  scripts/terminology-mapping/valueshapes/
```
