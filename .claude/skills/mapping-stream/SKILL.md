---
name: mapping-stream
description: Drive the per-stream ConceptMap + enumerated ValueSet workflow in scripts/terminology-mapping — adding a code population (stream) to a bound FHIRPath field's builder, or standing up a new bound field. Use whenever work involves build_*_cm_vs.py, build_*_table.py, code-search mapping tables, unmapped-*.csv review, or make targets like condition/procedure/observation/observation-component/upload-mappings.
---

# mapping-stream

You are adding **one stream** (one code population) to the terminology mapping
pipeline, or standing up **one new bound FHIRPath field**. One stream per
invocation — never more, however tempting the next one looks.

## Step 0 — read before doing anything

1. `scripts/terminology-mapping/README.md`, **in full**. It is the authoritative
   description of the architecture and the arguments behind it. This skill does
   not restate it; it tells you the process and the guardrails. Where they seem
   to disagree, the README wins — say so and ask.
2. The field's GitHub issue. These live in **fhnaumann/master_thesis_pipeline,
   not this repo**: `gh issue view -R fhnaumann/master_thesis_pipeline <n>`
   (e.g. issue 20 for Observation.code, issue 18 for the general flow). The
   issue is the spec: which populations exist, their sizes, target systems, and
   the intended order. Every bound field gets an issue in this style.
3. The exemplars you will imitate:
   - Builders (declaration-only): `conceptmaps/build_condition_cm_vs.py`
     (simplest), `conceptmaps/build_observation_cm_vs.py` (multi-stream).
   - Table generators: `conceptmaps/build_micro_susc_table.py` (LOINC),
     `conceptmaps/build_d_items_table.py` (SNOMED).

## Non-negotiables

These are restated here because missing one wrecks a supervised review. The
full arguments are in the README.

1. **Equivalence is decided by resolver, never per row.** `equivalent` only for
   identity mappings and trivial notation rules (the ICD dot). Everything that
   comes from a table is `relatedto`, set by `lib/assemble.py`. Gaps become
   declared `unmatched` elements plus a row in `unmapped-<field>.csv` — never a
   silent omission, never `ConceptMap.group.unmapped` with mode `provided`.
2. **One builder script per FHIRPath field.** A new stream on an existing field
   is a `SOURCES` entry plus a table, not a new `build_*_cm_vs.py`. Builders are
   declarations; everything that computes lives in `conceptmaps/lib/` and
   nothing downstream re-derives a mapping.
3. **Source codes are never hand-written.** They come from the IG through
   `source_concepts`. Determinism comes from the committed table: `make
   mappings` reads CSVs, never a server, and `make mappings && git diff
   --exit-code` must stay a valid test.
4. **code-search is probe-only.** Terminology-server traffic (Ontoserver
   `$lookup`, `$expand`, ECL, `make verify-curated`) is unrestricted — use as
   much as you need. Individual code-search probes to design and validate the
   query setup are also fine. But a **full-population generation run is the
   human's to execute**. Hand over the command; run it yourself only if this
   session's prompt explicitly said so. Permission never carries over from a
   previous conversation, and it does not extend to subagents: a spawned
   prober is bound by the same probe-only rule.
5. **Uploads are always human-run.** Your last act is handing over the exact
   command, always narrowed: `make upload-mappings ONLY=<field>
   UPLOAD_ARGS=--insecure`. If unmapped codes remain, say that `--allow-unmapped`
   will be needed — but choosing it is Felix's call, never yours.

## Step 1 — resume-from-state

A stream spans human gates, so you may be picking up mid-flight. Diagnose
before acting:

| Observed state | Resume at |
|---|---|
| No generator script for the stream | Step 2 (proposal) |
| Generator exists, no committed CSV | Step 3 (hand over the generation command — or the proposal was never approved; check with Felix) |
| CSV committed, no `SOURCES` entry | Step 4 |
| `SOURCES` entry present, outputs stale or unreviewed | Step 5 (build + inspection summary) |
| Built and reviewed, not uploaded | Step 6 (hand over upload command) |
| Uploaded (Felix confirms) | Step 7 (tick the issue checkbox) |

If no stream was named, propose the next unchecked one in the issue's order and
**confirm before starting**.

## Step 2 — propose the query setup, with adversarial evidence

For a code-search stream, four settings carry the accuracy, and you propose all
four for approval before writing the generator:

- **Target system** — LOINC, SNOMED, or mixed (see the issue).
- **Constraint** — a SNOMED ECL expression or a LOINC CLASSTYPE/STATUS filter.
  This is the setting that carries the accuracy, not the threshold: read the
  `Foley Catheter` lesson in the README before choosing.
- **Template sentence** — one fixed wrapper stating what the source table is,
  applied uniformly (never per-item judgement).
- **Confidence threshold** — default 0.8; deviations need evidence.

The proposal must include ~5–10 representative probe results, **including
adversarial ones**: labels where the unconstrained search returns a confident
wrong answer (a physical object, a body structure, a LOINC Part) and the
constraint demonstrably rejects it. Probes are cheap; run enough to know.

**Delegate the probing to subagents — never probe from the main context.**
Raw probe traffic ($expand responses, code-search JSON, ECL trial-and-error)
is bulky and pollutes the context that has to hold the whole stream. Spawn a
subagent (Agent tool) per probing question — e.g. one to tune the constraint
against adversarial labels, one to sample representative labels through the
candidate setup — and have it return only the distilled evidence: for each
probed label, the query sent, the top answer with confidence, and one line on
why it is right or wrong. The subagent inherits the guardrails: terminology
server unrestricted, code-search individual probes only, never a
full-population run. The main agent's job is to assemble the returned
evidence into the proposal, not to hold the transcripts.

**Mixed-target streams** additionally state both constraints and an explicit
routing rule for which codes get probed against which system.

Stop here and wait for approval.

## Step 3 — write the generator, hand over the run

Copy the closest exemplar generator. Conform to the naming table:

| Artifact | Rule | Example |
|---|---|---|
| Generator | `conceptmaps/build_<stream>_table.py` | `build_micro_susc_table.py` |
| Table (single target) | `conceptmaps/<stream>-<system>.csv` | `micro-susc-loinc.csv` |
| Table (mixed target) | `conceptmaps/<stream>-standard.csv` | — |
| Make target | `<stream>-table` | `micro-susc-table` |
| Log | `output/<stream>-generation-log.json` | `micro-susc-generation-log.json` |

The log name matters beyond bookkeeping: `lib/stats.py` derives it from the
table name (drop the table's last `-<system>` token) to pull the generation
settings — constraint, template, threshold — into the per-stream statistics.
The log should carry `constraint_ecl` (or `constraint_vcl`), `template` and
`confidence_threshold` at top level, and the table's `codesearch_confidence` /
`codesearch_status` provenance columns feed the confidence spread and status
breakdown. Copy the exemplars and this works for free.

Single-target tables carry `CURATED_COLUMNS` (`mimic_code, mimic_display,
<system>_code, <system>_display, comment`) plus the `codesearch_*` provenance
columns. Mixed-target tables use per-row **`target_system, target_code,
target_display`** instead of the system-named pair; existing single-target
tables are never migrated to this shape. A blank target code is a decision and
must carry a `comment`. Keep the gate (exists, active, international core
module, server-preferred display) — copy it from the exemplar.

If a stream genuinely cannot conform to the table above, say so and ask.

Then hand Felix the command (`make <stream>-table ARGS=--insecure`) and stop —
unless this session explicitly told you to run it.

## Step 4 — wire the stream into the builder

Add the `SOURCES` entry to the field's existing `build_<field>_cm_vs.py`,
imitating the micro-susc entry: `table`, `table_columns` (or the mixed-target
shape), `targets`. Update the builder's docstring and `META` description if
they enumerate which streams are present.

## Step 5 — build and summarize for inspection

Run `make <field>`, then `make mappings` (verification always runs over every
population). Every field build also regenerates the per-stream statistics:
the `by_stream` array in `<field>-report.json`, plus
`output/mapping-statistics.csv` (committed — the thesis interface) and
`output/mapping-statistics.html` (gitignored view; `make statistics` prints
the terminal table). Do not compute coverage numbers by hand — quote the
stream's `by_stream` entry / CSV row, and confirm the new stream's row appears
there.

Produce a fixed-shape summary:

- The stream's `by_stream` numbers (total, mapped, coverage %, equivalence
  split, `codesearch` status breakdown and confidence spread), plus the
  field-level coverage compared against the state before this stream.
- Unmapped rows **grouped by reason** (below-threshold / gate-failed /
  no-match-in-constraint / no-row-in-curated-table), with counts and a handful
  of spot-check rows from each group.
- Confirmation that `make mappings` passes and a second run leaves
  `git diff --exit-code` clean (the determinism test).

The summary is a map of where to look; Felix inspects the CSV himself. The
working tree should now be one reviewable, commit-sized unit: generator, make
target, committed CSV, `SOURCES` entry, rebuilt outputs.

## Step 6 — hand over the upload

Give the exact command per non-negotiable 5. Do not run it.

## Step 7 — close out

Once Felix confirms the upload happened (never on a green build alone), tick
the stream's checkbox in the field's issue: edit the body via
`gh issue edit -R fhnaumann/master_thesis_pipeline <n> --body ...`, changing
only that checkbox. Name what the next unchecked stream would be — and do not
start it.

## Path (b) — a brand-new bound FHIRPath field

**Hard precondition:** the source ValueSet is already bound in the IG and
resolvable (`input/resources/` or `fsh-generated/` after `sushi .`), and the
field's GitHub issue exists. If either is missing, stop and tell Felix —
never author FSH bindings or invent a population list to unblock yourself, and
never mint a source canonical.

Then:

1. Copy the closest exemplar builder. Declaration only — `SOURCES` and `META`;
   any logic belongs in `lib/`.
2. Author `META` fully, in the house style of the existing four builders:
   canonicals under `CANONICAL_BASE` (never under `mimic.mit.edu`),
   `sourceCanonical` exactly the existing bound ValueSet, and description /
   purpose prose that states the identity groups and the `relatedto` consumer
   caveat out loud. Draft complete prose — Felix edits, you don't skeleton.
3. Wire the Makefile: a `make <field>` target with a `##` help comment, added
   to the `mappings` dependency list.
4. **One name per population, everywhere**: make target, builder `FIELD`,
   `unmapped-<field>.csv`, `<field>-report.json`, `ONLY=` — the same word,
   named for the bound element.
5. Converge to path (a): streams get added one at a time.
