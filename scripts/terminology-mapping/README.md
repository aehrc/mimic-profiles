https://www.cms.gov/medicare/coding-billing/icd-10-codes/icd-9-cm-diagnosis-procedure-codes-abbreviated-and-full-code-titles
https://archive.cdc.gov/www_cdc_gov/nchs/icd/icd9cm.htm
https://github.com/OHDSI/MIMIC/blob/main/custom_mapping_csv/gcpt_proc_itemid.csv

FINDING for ValueSet  mimic-procedureevents-ditems: A true mapping does not stay within Snomed procedure codes, instead branch out to other codes (like Observation area)


# terminology-mapping

Everything that turns raw ICD release files into FHIR terminology resources, and
those resources into the ConceptMaps and ValueSets MIMIC's coded fields resolve
through. Absorbed the former `scripts/terminology-build/` and
`scripts/icd-migration/` — this is the only home now.

## The flow

Three stages. Stages 1–2 are local and offline; stage 3 is the only one that
needs a decision from you.

```
  ┌─ 1 ─ per (system, release) ──────────────────────────────────────┐
  │  sources/  ──build──►  output/CodeSystem-*.json  ──upload──►     │
  │                                                    $lookup       │
  └──────────────────────────┬───────────────────────────────────────┘
  ┌─ 2 ─ one offline pass, `make mappings` ──────────────────────────┐
  │                                                                   │
  │  STREAMS, declared once in conceptmaps/lib/streams.py:            │
  │  one source enumeration -> target system(s) via one resolver      │
  │  (committed table | notation rule | identity). A stream resolves  │
  │  IDENTICALLY wherever it is consumed.                             │
  │                                                                   │
  │  build_<field>_cm_vs.py   one per bound element: projects the     │
  │      streams its facade ValueSet reaches into                     │
  │      ConceptMap-<id>.json + ValueSet-<target id>.json             │
  │      + <field>-report.json (per-map totals and canonicals)        │
  │                                                                   │
  │  build_stream_reports.py  resolves every stream once:             │
  │      output/stream-report.json     THE statistics file            │
  │      unmapped-<stream>.csv         one worklist per stream        │
  │      output/occurrence-buckets.csv per-element data coverage      │
  │                                                                   │
  │  build_statistics.py      renders stream-report.json into         │
  │      mapping-statistics.{csv,html} and the terminal table         │
  └──────────────────────────┬───────────────────────────────────────┘
       ── you read the statistics and the per-stream worklists ──
  ┌─ 3 ─────────────────────▼────────────────────────────────────────┐
  │  upload.py — ValueSets first, then ConceptMaps. Refused while     │
  │  anything is unmapped, unless you pass --allow-unmapped           │
  └──────────────────────────────────────────────────────────────────┘
```

The map and its ValueSet are built together, which is why there is no scaffold
stage any more. Earlier the map was written in one stage and the value set
derived from it in a later one, so at map-writing time the `targetCanonical`
pointed at nothing — a placeholder existed only to fill that gap, and nothing
ever read it.

One ConceptMap and one ValueSet per bound field, so a consumer starting from a
bound element resolves exactly one map:

| Bound element | Bound ValueSet | ConceptMap | Target ValueSet | Builder |
|---|---|---|---|---|
| `Condition.code` | `mimic-diagnosis-icd` | `mimic-diagnosis-icd-to-sid` | `mimic-diagnosis` | `build_condition_cm_vs.py` |
| `Procedure.code` | `mimic-procedure-merged-code` | `mimic-procedure-merged-to-standard` | `mimic-procedure-merged-standard` | `build_procedure_cm_vs.py` |
| `Observation.code` | `mimic-observation-merged-code` | `mimic-observation-merged-to-standard` | `mimic-observation-merged-standard` | `build_observation_cm_vs.py` |
| `Observation.component.code` | `mimic-observation-component-vital` | `mimic-observation-component-to-standard` | `mimic-observation-component-standard` | `build_observation_component_cm_vs.py` |
| `Specimen.type` | `mimic-specimen-type` | `mimic-specimen-to-standard` | `mimic-specimen-standard` | `build_specimen_cm_vs.py` |
| `MedicationRequest.medication[x]` | `mimic-medication-request-code` | `mimic-medication-to-standard` | `mimic-medication-standard` | `build_medication_cm_vs.py` |
| `Medication.code` | `mimic-medication-code` | `mimic-medication-code-to-standard` | `mimic-medication-code-standard` | `build_medication_code_cm_vs.py` |
| `MedicationAdministration.medication[x]` | `mimic-medication-administration-merged-code` | `mimic-medication-administration-to-standard` | `mimic-medication-administration-standard` | `build_medication_administration_cm_vs.py` |

`MedicationRequest.medication[x]` and `Medication.code` are **one pair, not two
populations**: that element is a choice, and at least 87.8% of MIMIC
prescriptions carry `medicationReference` rather than an inline CodeableConcept,
so a consumer must dereference and translate `Medication.code`. A required
binding cannot constrain a Reference — a validator has nothing coded to check —
so for those prescriptions `Medication.code`'s binding is the only one governing
the drug code. Two elements bound to the same union, hence the two facade
ValueSets above; see "One map per element needs one sourceCanonical per element".

Two more elements are inventoried in `occurrences/elements.json` but have **no
map yet**: `MedicationDispense.medication[x]` (9,372 drug-name codes, 12.7M
codings — where nearly the whole name CodeSystem is actually used) and
`MedicationStatement.medication[x]` (the ED medrecon population, bound at the
coding slices).

**One builder script per ConceptMap, and how it maps is that script's own
business.** The condition builder does nothing but insert dots; the procedure
builder combines two notation rules, an identity group and a generated table.
Adding a population means writing one script — nothing central to register it
in. What the scripts share is `conceptmaps/lib/`, which holds everything
executable, and the shape of what they emit (the four files above), so coverage
stays comparable across populations that were mapped by completely different
methods.

### Why `Procedure.code` maps from the *merged* value set

Downstream pipelines merge every Procedure sub-type into one resource type, so
`Procedure.code` is a single column carrying three code populations — MIMIC's
ICD codes, the two SNOMED CT codes of `mimic-procedure-types-ed`, and the local
`mimic-d-items` codes. Such a consumer injects exactly **one** `translate()`
over that column, and a code the map does not contain does not pass through: it
returns nothing and the row's code goes null.

Mapping only the ICD population would therefore make every ED and ICU procedure
silently unsearchable, while every automated check still passed — the map's
`sourceCanonical` and `targetCanonical` would both be correct. So all three
populations live in the one map, and codes that are **already** standard get an
identity group rather than being left out:

| Group source | Target | `targetVersion` | Why |
|---|---|---|---|
| `mimic-procedure-icd9` | `icd-9-cm` | pinned | notation: `3226` → `32.26` |
| `mimic-procedure-icd10` | `ICD10` (PCS) | pinned | notation: 7-char leaves, no dot |
| `snomed.info/sct` | `snomed.info/sct` | **absent** | identity — already standard |
| `mimic-d-items` | `snomed.info/sct` | **absent** | generated table — see below |

"Needs no translation" and "is missing from the map" look identical to a
consumer; the identity group is what makes the first one say so out loud. It is
the same argument as the `unmatched` groups below, and both are why this repo
prefers a declared fact over a silent omission.

Identity groups carry **no `targetVersion`**, and the corresponding
`compose.include` carries no `version`. This repo builds no SNOMED CodeSystem,
and pinning a release it neither publishes nor controls is exactly the
irreproducibility that check 3 exists to catch. Systems allowed to go
unversioned are listed in `UNVERSIONED_SYSTEMS`, so that check can tell a
deliberate omission from a bug rather than skipping it.

Consequence for the source side: because `mimic-procedure-types-ed` is
FSH-authored, its enumerated ValueSet only exists under `fsh-generated/`, which
is gitignored. **A clean checkout must run `sushi .` before `make mappings`.** A
missing FSH-authored source is a hard error, not the warning-and-skip a missing
`input/resources/` CodeSystem gets — skipping it is precisely how you would end
up with the map that drops every ED code.

### `Observation.code` is being built one stream at a time

The Observation map is **incomplete on purpose** and currently holds only its
identity groups. Ten populations across nine profiles bind `Observation.code`
(plus `Observation.component.code`), 5,729 codes in total, and — unlike the two
maps above — only 9 of them are already standard. The other 5,720 need a
*semantic* answer, not a notation rule, so the coverage to expect here is the
64% the ICU `procedureevents` table actually scored, **not** the 99.5% the ICD
populations reached by inserting dots. A stream that comes back with a third of
its codes unmapped is the pipeline working, provided every one of them is
declared with a reason.

In the map today:

| Group source | Target | `targetVersion` | Why |
|---|---|---|---|
| `loinc.org` (ED, 4) | `loinc.org` | **absent** | identity — already standard |
| `loinc.org` (vital signs, 5) | `loinc.org` | **absent** | identity — already standard |

Both land in one R4 group, because a group is keyed by (source system, target
system, `targetVersion`) and both populations are LOINC-to-LOINC. LOINC is
therefore now on `UNVERSIONED_SYSTEMS` for the same reason SNOMED CT is: this
repo builds no LOINC CodeSystem, so it has no release to pin.

Each remaining population arrives as its own committed table, its own `make`
target and its own **search constraint** — a SNOMED ECL expression or a LOINC
`CLASSTYPE`/`STATUS` compose filter. The constraint is the setting that carries
the accuracy, not the confidence threshold: unconstrained, `Sodium, Blood`
against all of LOINC answers with the *Part* `LP32156-9 |Sodium|` at 0.9, which
is not a legal `Observation.code` at all. It is the `Foley Catheter` lesson from
the ICU table repeating — see "Why not OHDSI" below — where the worst answer
scored highest.

### `Observation.component.code` is a separate column, so it gets a separate map

MIMIC-ED stores `sbp` and `dbp` as two columns of one row, which FHIR models as
**one** Observation coded `85354-9 |Blood pressure panel|` carrying the two
numbers in `component` — about 2M such rows, the largest coded Observation
population in the warehouse. Those two codes are bound to
`Observation.component.code`, not `Observation.code`.

They are already LOINC, so they get an identity group for the usual reason: a
consumer cannot tell "needs no translation" from "missing from the map". The
question is only *which* map, and the answer is their own —
`build_observation_component_cm_vs.py`, `make observation-component`, own
ConceptMap, own target ValueSet, own report. It is not a sub-step of
`make observation`; it is a separate bound element that happens to sit on the
same resource.

Folding the two codes into `mimic-observation-merged-code` is the easy fix and
the wrong one: that value set is bound with **required** strength, so it would
legalise `code = 8480-6 |Systolic blood pressure|` on a merged Observation — a
code MIMIC only ever emits inside a component. But putting them into the
`Observation.code` *map* while leaving them out of that value set is wrong too,
for two reasons that only show up on the consuming side:

- **There is no correct `sourceCanonical` left to declare.** A consumer
  configures each column with the map it projects through *and* the source value
  set it expects that map to name, then checks the two agree. A map spanning
  both bindings matches neither.
- **It offers a code for a column that can never hold it.** `Observation.code`
  and `Observation.component.code` are different FHIRPath expressions, hence
  different projected columns. One merged map puts `8480-6` in the target value
  set a consumer searches for the `Observation.code` column, so a search for
  "systolic blood pressure" resolves, projects back, and filters
  `Observation.code = 8480-6` — matching nothing, silently, while every check in
  this repo still passes.

Two maps put each code in exactly the one column that can hold it, and both name
a `sourceCanonical` published by `scripts/publish-conformance.sh`.

### One map per element needs one sourceCanonical per element

The rule above assumes each bound element has a binding of its own. `mimic-medication`
breaks that assumption: it is bound `required` on FOUR elements — `MedicationRequest.medication[x]`,
`Medication.code`, `MedicationDispense.medication[x]`, and `MedicationAdministration.medication[x]`
through the merged facade — and each element gets its own map. A shared
`sourceCanonical` then leaves `$translate` unable to tell which element a Coding
came from, and each element-scoped map answering for populations it was never
scoped against. That was not hypothetical: `mimic-medication-to-standard` is
scoped to the 2,888 drug names on `MedicationRequest.medication[x]`, while 9,372
of them appear on `MedicationDispense.medication[x]` — so 6,741 codes came back
"never observed" to a Dispense consumer, 701 of them codes this repo has answers
for.

So two facade ValueSets ARE minted, in `input/fsh/`:
`mimic-medication-request-code` and `mimic-medication-code`. Each is a grouping
ValueSet whose whole compose is `include codes from valueset mimic-medication`,
so **membership is identical and no instance validates differently** — what they
buy is a canonical identity per element. Same shape as
`mimic-medication-administration-merged-code`, different reason: that one unions
sub-types, these disambiguate elements.

Two consequences worth knowing. They are FSH-authored, so they reach a server
through the IG build and `scripts/publish-conformance.sh`, not through
`upload.py` (which publishes each map's *target* value set only). And
`verify_mappings.py` check 5 reads them from `fsh-generated/`, so it needs
`sushi .` to have run — it says so rather than passing silently when they are
missing.

### The one rule about rules

**Nothing downstream of a builder re-derives a mapping.** The builder writes a
ConceptMap; the ValueSet projection, the verifier and every consumer read that
map. This is not stylistic: the dot-insertion rules were previously reimplemented
in three scripts that drifted apart, and the coverage checker and the published
map disagreed as a result.

With one builder per population, the corollary is where the shared code sits:
`conceptmaps/lib/notation.py` holds the dot rules and nothing else may. ICD-9-CM
is a target of *both* the diagnosis and the procedure map — differing only by the
`kind` filter — so this is exactly the duplication that caused the original bug.
If you find yourself writing `code[:3] + "." + code[3:]` anywhere else in this
repo, that is the bug.

What each builder owns is its **declaration**: `SOURCES` (which streams it
consumes, by name — the streams themselves live once in `lib/streams.py`) and
`META` (ids, canonicals, titles, descriptions, purpose, copyright). What `lib/`
owns is everything that computes, assembles or writes:

| Module | Holds |
|---|---|
| `lib/streams.py` | every stream, declared once; `check_disjoint`, `undeclared` |
| `lib/notation.py` | dot insertion, `is_pcs_leaf`, `concept_properties` |
| `lib/canonical.py` | system URLs, `UNVERSIONED_SYSTEMS`, canonical bases |
| `lib/igsource.py` | `source_concepts` — reading codes from the IG |
| `lib/builders.py` | which builders exist; a table generator's population |
| `lib/curated.py` | loading and validating a mapping table |
| `lib/built.py` | the built CodeSystems, release resolution, dating |
| `lib/assemble.py` | `resolve_source` — ONE resolution per stream — then stream outcomes → ConceptMap groups, `unmatched` groups |
| `lib/project.py` | ConceptMap → enumerated target ValueSet |
| `lib/report.py` | the per-stream worklists and the per-map report |
| `lib/stats.py` | the codesearch block, from committed tables and logs |
| `lib/driver.py` | the shared build: streams in, three files out |

Its other corollary: **source codes are never written out in a builder.**
`source_concepts` reads them from the IG's own CodeSystems and ValueSets, and
both the builders and the verifier go through it, so neither can hold a private
copy of what the source side is. A literal list of codes in this repo would
drift from the profiles the map serves and nothing would notice.

Future mapping rules more complex than dot insertion go in that same file, and
everything downstream gets them for free.

## The ICU population, where no rule is possible

`mimic-procedureevents-d-items` is the third population in the merged
`Procedure.code` column, and it is the first one no rule can derive. The
displays are ICU flowsheet labels rather than clinical terms, and they fail a
string matcher in three distinct ways:

- **The label omits the procedure.** `225460 Cervical Spine`, `225461 Pelvis`
  and `225463 TLS Spine` sit alongside `225459 Chest X-Ray`; they are X-ray
  series named only by body region. Match `Pelvis` lexically and you get
  `12921003 |Pelvic structure|` — a body structure, confidently returned, and
  it validates. The six gauge items (`224566 14 Gauge` …) are the same shape:
  a cannula size standing for the cannulation.
- **Local acronyms.** `229526 MAC` is a multi-access catheter, not
  *Mycobacterium avium* complex and not monitored anaesthesia care.
  `227719 AVA`, `225205 RIC`, `229514 EKOS`, `229533 Camino`, `228130 NEOB`,
  and `227715 TLS Clearance` (thoracolumbosacral, not tumour lysis) are alike.
- **Items that are not procedures.** `225474 Fall`, `225466 Cardiac Arrest`,
  `225465 Chest Pain` and `225472 Pneumothorax` are events, disorders and
  findings; the four `(Inhaled)` agents are medication administrations.

Every one of those failures produces a mapping that looks right and means
something else — the same reason this repo refuses `unmapped: provided` and
refuses the PCS fallback. So the ICU mapping is **data**, in
`conceptmaps/d-items-snomed.csv`.

That table used to be written by hand. It no longer is: a hand-built table
rests every row on one person's clinical judgement, which a reader cannot check
and a second person cannot reproduce. `conceptmaps/build_d_items_table.py`
generates it from two sources that can both be cited, and `make d-items-table`
runs it.

A blank `snomed_code` is a **decision, not an omission**, and the row must then
carry a `comment` saying why; those rows become `unmatched` elements exactly
like the ICD ones. The generator writes that comment itself, naming what the
service said and on what ground it was declined:

```csv
mimic_code,mimic_display,snomed_code,snomed_display,comment,...
229468,24 Gauge,,,code-search returned no match within (<<71388002 OR <<404684003 OR <<272379006).,...
221216,X-ray,168537006,Plain X-ray,,...
```

Those five columns are `CURATED_COLUMNS` in `lib/curated.py`, the only ones a
builder reads. The file carries five more — `codesearch_target`,
`codesearch_display`, `codesearch_confidence`, `codesearch_status` and
`codesearch_reasoning` — which the build reads and discards. The proposal is
recorded on every row including the rows where it was then rejected, so any
single mapping, and any single non-mapping, can be audited from the CSV alone.

There is **no `equivalence` column**: every mapping a table supplies is
`relatedto`, set by `lib/assemble.py`. See [Equivalence](#equivalence-relatedto-for-every-table-mapping).

### A table is keyed by its source CodeSystem, not by the field that reads it

Two bound elements can share a source CodeSystem. `mimic-medication-name` is one:
`MedicationRequest.medication[x]` observes 2,888 of its codes and
`MedicationAdministration.medication[x]` observes 3,620, overlapping in 2,600.

A table per field over those sets is a way for this repo to publish **two
different RxNorm concepts for one MIMIC drug name**, in two ConceptMaps, with
nothing to notice. The deterministic term-join tier would agree by construction,
but code-search re-asked on the shared residual can answer differently, and no
check compares two tables. Detecting that afterwards is worse than preventing
it: detection fires only once both generation runs have been paid for, and
resolving the conflict is then a per-row human judgement — the thing the
generated-table contract exists to remove.

So the table is shared — it belongs to the STREAM, one entry in
`lib/streams.py`, and every map that consumes the stream reads the same rows
and publishes the same answers. Two things follow:

- `load_table` validates rows against the stream's whole **enumeration**.
  Staleness detection survives — a row naming a code the IG no longer has is
  still fatal, as is display drift — and since every consuming map resolves
  the full enumeration, there are no sibling-only rows left to mistake for
  stale ones.
- The generation population is the codes observed on **any** bound element
  (`lib/builders.table_population` — the stream's enumeration narrowed by the
  committed occurrence counts), not one element's usage. A code observed
  somewhere without a table row lands in the worklist as
  `no-row-in-curated-table` while the build stays green — the signal to run
  `make generate-all-tables`, which fills exactly those gaps.

**`--append` is what makes sharing cheap.** Without it, adding a second field's
codes means re-asking the service for the whole union and rewriting rows already
generated, reviewed and committed. With it the committed rows are kept verbatim
— including the declined ones, which are answers and are the most expensive
calls in a run — and only codes with no row are asked. It refuses when the
committed log's settings differ from the generator's constants: the log states
one constraint, template and threshold for the whole table, so appending across
a settings change would attribute today's settings to yesterday's rows. Moving a
setting means regenerating in full.

**Determinism comes from the table being committed**, not from the strings.
`make mappings` reads the CSV and never a server, so it stays offline and
`make mappings && git diff --exit-code` stays a valid test. The generator is
deliberately *not* wired into it: it needs the network and a model-backed
service, and it is the only stage whose output is not a pure function of this
repo. Run it, read the diff, commit the CSV.

### How the table is generated

```
 generate (network, explicit, occasional)          build (offline, unchanged)

  code-search (all 169) ──► gate ──► d-items-snomed.csv ──► build_procedure_
                                       committed, with           cm_vs.py
                                       provenance columns      reads the
                                                               committed CSV
```

**The gate** is the same check `verify-curated` enforces, used as a filter
rather than an assertion: a target is discarded unless it exists, is **active**,
and is in the SNOMED **international core module** rather than a national
extension. A target that fails is treated exactly like an absent one. This is
not hypothetical — it drops 7 AU-extension concepts that code-search proposes,
which resolve on the server they were authored against and nowhere else, and
are invisible by reading a CSV. Target displays are then replaced with the
server's preferred term, so `verify-curated`'s display check passes by
construction.

### Why not OHDSI

An earlier version of this table took OHDSI's MIMIC-IV → OMOP CDM crosswalk
([OHDSI/MIMIC](https://github.com/OHDSI/MIMIC), Apache-2.0) as the primary
source, with code-search as a gated second opinion, on the ground that a
published artefact is reproducible where a model-backed service is not. That
is a real property, and it was the wrong trade: the two disagreed on 45 of the
93 rows where both answered, and reading the disagreements, the second opinion
kept winning on clinical grounds. OHDSI put `Presep Catheter` — a central
venous oximetry catheter — on Swan-Ganz pulmonary catheterisation, and
`Midline`, which is by definition not a central line, on peripherally inserted
**central** catheterisation. It also repeatedly chose a target carrying a
qualifier the flowsheet label never asserted: `Hemodialysis` onto
**intermittent** haemodialysis, `Tunneled (Hickman) Line` onto **fluoroscopy
guided** tunnelled catheterisation, `Cardiac Cath` onto angiocardiography.
Precedence by source was shipping targets that were wrong about the patient.

The cost of dropping it is **32 items that now have no target at all**, chiefly
the vascular-line family (`14`/`16`/`18`/`20`/`22 Gauge`, `Multi Lumen`,
`Cordis/Introducer`, `Triple Introducer`), the temporary-LVAD lines
(`Impella`, both `Tandem Heart` lines) and the spine imaging and clearance
items. Mapped rows fall from 140 to 108. Those 32 are declared unmapped with a
reason rather than guessed, and 20 of them failed at the confidence threshold
or the extension gate rather than for want of an answer — so they are
recoverable by moving a stated setting, not by re-adding a source.

Two settings carry the accuracy. Both are stated rules applied identically to
all 169 items, and neither involves a per-item decision:

- **The search is constrained to procedure ∪ clinical finding ∪ event**
  (`<<71388002 OR <<404684003 OR <<272379006`). Not the full implicit SNOMED
  ValueSet: asked for `Foley Catheter` against all of SNOMED the service
  answers `73368009 |Foley catheter (physical object)|` at confidence **1.0** —
  a correct reading of the text and an unusable `Procedure.code`. `Midline`
  returns a qualifier value, `MAC` a substance, `Pelvis` a body structure, all
  above 0.9. **Confidence does not separate these from good answers; the worst
  of them score highest**, because the service is confidently coding what the
  label literally says. Only the hierarchy constraint separates them. Narrowing
  to procedures alone would be wrong in the other direction — `Fall`,
  `Chest Pain` and `Pneumothorax` genuinely are not procedures — hence the union.
- **Each label is wrapped in one fixed sentence**, `ICU procedure event
  recorded on placement or performance of: {label}`. These labels are column
  headings from a `procedureevents` table, and that table is the only place the
  word "procedure" appears: `Foley Catheter` names the device and leaves the
  catheterisation implicit. The template supplies that context uniformly, so it
  states a fact about the source table rather than a judgement about any item.
  Without it the constrained search correctly declines most of the
  line/catheter population.

**Answers below 0.8 confidence are discarded** and the item is left unmapped.
Every run prints the full confidence distribution so the threshold can be moved
with evidence rather than by taste.

`output/d-items-generation-log.json` records what the last run saw for every
row, so any single mapping can be audited without re-running the generator.

### It names source codes, and is checked instead of trusted

A mapping table has to write source codes down — a per-code answer is its
entire content — which is the one thing the corollary above forbids. What
replaces the guarantee is validation. `load_curated` reads the IG enumeration
through `source_concepts` as every other stage does, and then:

| Situation | Result |
|---|---|
| row names a code the IG does not have | **fatal** — stale row, delete it |
| row's `mimic_display` differs from the IG's | **fatal** — the item was relabelled upstream; re-check the mapping |
| IG code has no row | ordinary unmapped CSV row, `no-row-in-curated-table` |
| blank `snomed_code`, no `comment` | **fatal** — a decision must state its reason |

The display check is the load-bearing one: an item whose label changed upstream
is precisely the item whose mapping a human should look at again.

### What the last run found

Where the 169 rows end up:

| | rows |
|---|---|
| code-search, ≥ 0.8 and passed the gate | 108 |
| proposed below the 0.8 threshold | 35 |
| proposed but outside the international core | 7 |
| no match within the ECL constraint | 19 |

So **61 items are declared unmapped**, and 42 of those had an answer that was
rejected by a stated setting rather than never offered. The `codesearch_target`
and `codesearch_confidence` columns keep the rejected proposal, so moving the
threshold is an evidenced decision rather than a guess.

> **Known defect: `227719 AVA`.** Mapped to `287364001 |Arteriovenous
> anastomosis|`, a surgical AV fistula. In the MIMIC line population `AVA` is
> Advanced Venous Access, a large-bore introducer, so this makes the data say
> something false rather than merely vague. Left in place and flagged here
> because the generator does not hand-write targets; the fixes available are to
> change `TEMPLATE` or to drop the row, both of which are decisions about the
> method rather than about this itemid. A consumer should drop it.

`make verify-curated` re-checks every target against a live server: that it
exists, is **active**, belongs to the **international core module** rather than
a national extension, and that `snomed_display` really is a designation of that
concept. It is not part of `make mappings`, which stays offline and instant.

**Accuracy against the table this replaced.** `eval/d-items-snomed-manual.csv`
is the hand-built 169-row table the generator superseded, kept as an answer key
over exactly the items the generator maps. Against it the generated table picks
the identical concept on **69 rows and agrees on 3 more by declaring both
unmapped (42.6%)**; 39 rows map to a different concept, and **58 the generator
leaves unmapped where a human had committed to an answer**. There is no row
where the human declined and the generator answered.

That agreement rate was 66.9% when OHDSI was the primary source, and the drop
is almost entirely the 58-row coverage gap rather than new wrong codes — the
intended failure direction, but a real cost, and the honest headline for this
change. Note the key is itself fallible and is not a gold standard: it is the
judgement the generator was built to stop relying on, and several of the rows
it "loses" are ones where the human answer was the clinically wrong one.

### Equivalence: `relatedto` for every table mapping

Two equivalences are emitted, and which one a mapping gets is decided by its
**resolver**, not per row. `lib/assemble.py` sets it:

| resolver | equivalence | populations |
|---|---|---|
| notation | `equivalent` | all ICD: 27,913 diagnosis, 10,031 PCS, 2,542 ICD-9 Vol 3 |
| identity | `equivalent` | 2 ED SNOMED, 9 LOINC observation, 2 LOINC component |
| table | `relatedto` | 108 ICU d_items, 27 microbiology antibiotics |

A notation mapping changes how a code is written and never which concept it
means, so `equivalent` there is a fact about spelling. An identity mapping is
the same code twice. Both are checkable without judgement.

A table mapping is not. `224276 16 Gauge` → `233520008 Peripheral venous cannula
insertion` loses the gauge; `229526 MAC` names one kind of central line;
`90008 TRIMETHOPRIM/SULFA` → `18998-5` crosses from a MIMIC drug name to a LOINC
susceptibility test. These are relationships, and **the direction is not
something this repo establishes**, so it is not asserted. Subsumption is only
decidable between two codes in one system, and the source is a MIMIC itemid or
antibiotic code rather than a SNOMED or LOINC concept, so there is no
`$subsumes` to run; code-search returns a code, a confidence and free text,
never a direction.

Earlier versions derived a direction per row — `equivalent` on a lexical match
against the target's designations, `wider` otherwise, with `narrower` where a
reviewer caught the fallback pointing the wrong way. Two problems, both fatal to
the idea. The claims were confident where the evidence was not: `wider` rested
on `TEMPLATE` having asked for a covering concept, which constrains the query
and not the answer, and the service answering with something *more* specific
(`Paracentesis` → `Abdominal paracentesis`) made the row simply wrong with no
signal in the data. And the exceptions needed hand-written overrides —
per-row judgement re-entering through the mechanism built to keep it out.
Dropping the derivation removed a lexical rule, a review heuristic, an override
table per generator, and the CSV column that carried the result.

What survives is **`comment`**: prose on the rows where the code pair alone
would mislead, carried into `ConceptMap.element.target.comment`. Three rows have
one — the lumbar epidural, and the two abbreviated antibiotic labels. They live
in `COMMENT_OVERRIDES` in each generator, keyed on `(mimic_code, target_code)`
so a note cannot survive its target moving, and an entry matching no row is
**fatal** rather than skipped. Like the equivalence overrides before them they
deliberately cannot pin a target code — the moment they could, they would be a
way to hand-write mappings around the confidence threshold and the gate, and the
table would stop being "what the service returned, gated".

The consequence is load-bearing and consumers must act on it: **filtering on
`equivalence: equivalent` drops all 135 table rows** — the whole ICU procedure
and microbiology populations. See the consumer notes.

## Running it

```sh
make verify-inputs        # do my ICD sources match input-manifest.json?
make update-manifest      # re-pin them after adding or changing a release

make terminology          # stage 1, build only
make deploy-terminology   # stage 1, build + upload + $lookup smoke tests

make mappings             # stage 2, everything offline: all ConceptMaps and
                          # ValueSets, the stream reports, the statistics,
                          # then verify — the everyday command
make stream-reports       # just the per-stream artefacts
make statistics           # stream reports + the coverage table (csv + html + terminal)
make verify-mappings      # the checks on their own
make verify-curated       # $lookup every SNOMED code in the mapping tables

make <stream>-table ARGS=--insecure   # regenerate ONE stream's mapping table;
                                      # network + code-search, never part of
                                      # `make mappings`. One target per
                                      # table-backed stream: d-items-table,
                                      # labevents-table, medication-name-table, …
make generate-all-tables ARGS=--insecure   # fill the gaps in every
                                      # gap-capable table (--append); asks for
                                      # confirmation first, FORCE=1 skips it

make upload-mappings UPLOAD_ARGS=--insecure  # stage 3, refuses while codes are unmapped
make upload-mappings ARGS=--allow-unmapped UPLOAD_ARGS=--insecure   # ... once reviewed
make upload-mappings ONLY=observation-component ARGS=--allow-unmapped UPLOAD_ARGS=--insecure
                                     # ... publishing just one map
```

`make mappings` is what you run while iterating: no network, seconds. There
are deliberately NO per-element build targets any more — a ConceptMap consumes
several streams and the whole offline pipeline is one pass, so a partial build
bought nothing except the mixed-state artefacts verify check 7 exists to
catch. The builders take no `--fhir-base` at all — they are pure functions of
the committed inputs, which is what makes a build from unchanged inputs
byte-identical and `make mappings && git diff --exit-code` a valid test.

TWO NAMING VOCABULARIES, on purpose. Build and generation are per STREAM
(`make labevents-table`, `unmapped-labevents.csv`, the rows of
`mapping-statistics.csv`); publishing is per MAP, so `ONLY=` takes the
builders' field names (`condition`, `observation-component`,
`medication-code`, …) — uploads move ConceptMaps and generation moves tables,
and the two are different sets of things.

`upload-mappings` takes two flag variables because its two steps take different
flags: `ARGS` reaches the verifier, `UPLOAD_ARGS` reaches the publisher.

Uploads go to `$ONTOSERVER_URL`. velonto needs `--insecure` (or `--ca-bundle`).
`upload.py` publishes every ConceptMap in `output/` together with the ValueSet
that map's own `targetCanonical` names — **value sets first**, so a map is never
briefly pointing at something the server does not hold.

`ONLY` narrows *that* — and only that. Publishing is a `PUT` by id, so an
unnarrowed run replaces the server's copy of every map in `output/`, including
populations your branch changed and you did not mean to move. `ONLY` takes a
comma-separated list of population names, resolved through the
`<field>-report.json` each builder writes, so a population names itself by being
built and there is no list to keep in step. A wrong name is a hard error listing
the real ones.

**One name per thing, everywhere.** A map is named for the element it maps
(`condition`, `observation-component`, `medication-code`), and that one word is
the builder's `FIELD`, `<field>-report.json` and `ONLY=`. A stream is named
for its table (`d-items`, `labevents`, `medication-name`), and that one word is
its registry key in `lib/streams.py`, its `make <stream>-table` target, its
`unmapped-<stream>.csv` worklist, its generation log and its row in the
statistics. `Condition.code` used to answer to `diagnosis`; its **canonicals
keep their names** (`ConceptMap/mimic-diagnosis-icd-to-sid`,
`ValueSet/mimic-diagnosis`) because a canonical is an identity rather than a
label.

What it does **not** narrow is the checking: `verify-mappings` still runs over
every population, because a broken map is broken whether or not this run would
have touched it.

Publication is a plain `PUT` by resource id, which fully replaces the previous
copy. Nothing is deleted first — CodeSystem releases deliberately share one
canonical URL and differ only by `version`, so a delete-by-url would take the
siblings with it.

### Per-stream statistics

A STREAM is the unit every statistic is keyed by: one source enumeration
resolved into one or more target systems by one resolver, declared exactly once
in `conceptmaps/lib/streams.py` and consumed by however many ConceptMaps bind
it. The stream key is the ENUMERATING RESOURCE, not the source CodeSystem —
`mimic-d-items` is one CodeSystem partitioned across three subset ValueSets
(procedureevents, datetimeevents, outputevents), each its own stream with its
own table and target. Streams sharing a system must be pairwise disjoint;
verify check 8 enforces it.

The registry is hand-kept, which makes it exactly as complete as someone
remembered to make it — so the table is built over the **bindings**, not over
the registry. `lib/streams.undeclared()` expands every `bound_valuesets` entry
in `occurrences/elements.json`, subtracts what the streams enumerate, and
`build_stream_reports.py` synthesises a `declared: false` row for whatever is
left: method `unstreamed`, 0% coverage, its own `unmapped-<name>.csv`, and the
elements that bind it in the `consumed by` column. Verify check 9 counts those
codes as unmapped.

The point is the **denominator**. Left out, the 10,548 GSN and ETC codes
carrying 7.1M occurrences were absent from `all streams (used-in-data)`
altogether, so declaring a stream for them could only ever move the headline
figure *down* — a coverage metric that punishes discovering work is pointed the
wrong way. Disjointness stops the registry double-counting; this is the half
that stops it under-counting, and the two are not symmetric: an overlap shows up
as a contradiction, while an omission shows up as nothing at all.

`build_stream_reports.py` resolves every stream once and writes
`output/stream-report.json`, one block per stream:

    enumerated_total   every code the stream declares
    used_in_data       codes observed on ANY bound element (union — the same
                       code is never counted once per consuming field)
    mapped             codes with an answer, over the whole enumeration
    mapped_used        the intersection, and the numerator of
    coverage_pct       THE headline: of the codes the warehouse actually
                       uses, how many resolve
    occurrences_*      the same coverage weighted by data volume
    codesearch         for table-backed streams: threshold, confidence
                       spread, status split, near-misses — read offline from
                       the committed table's provenance columns and its
                       generation log

Occurrence weights mix two artifacts on purpose: event elements weigh by
`code-occurrences.csv`, dictionary elements (Medication, deduplicated) by
`reference-occurrences.csv`, which counts each code once per REFERRING
resource — so the reference branch counts each prescription exactly once and
dictionary size is never summed with data volume.

Without the occurrence artifacts every used-in-data figure is OMITTED, never
zeroed and never re-based onto the enumeration: an empty percentage column
says "nobody counted", a number would quietly change what the column means.

`build_statistics.py` renders that report into `output/mapping-statistics.csv`
— one row per stream, the citable table — plus `mapping-statistics.html` (a
stacked-bar view, gitignored: a derived view, never a deliverable) and a
terminal table via `make statistics`. It recomputes nothing.

### Weighting coverage by how much data a code carries

Coverage over codes says how much of the dictionary was mapped. It cannot say
how likely a data point is to carry a code `$translate` cannot resolve, and
those diverge whenever the unmapped codes are the frequently used ones — which
is the case worth catching, because missing a code recorded on every admission
is not the same failure as missing one recorded twice in 2012.

So `occurrences/count_occurrences.py` runs once on the HPC node against the full
Delta warehouse and counts every distinct coded value for the ten bound
elements in `occurrences/elements.json`. Its outputs are committed
(`code-occurrences.csv`, `occurrence-summary.json` — the latter carries each
Delta table's version and each CSV's sha256, which `build_statistics.py`
verifies), so everything downstream stays offline.

Two of those outputs exist because a coding count is not a resource count.
`MedicationRequest.medication[x]` is a choice, and only its CodeableConcept
branch carries a Coding, so the count sees 1,883,681 codings against 15,416,901
rows — at least 87.8% of prescriptions keep their drug code on `Medication.code`
behind a `medicationReference`. `element-shapes.csv` counts which branch each
resource took; `reference-occurrences.csv` follows the reference and counts the
target's codes once per *referring* resource, which is the volume figure
comparable with the other elements. Note also that `Medication` is
**deduplicated** — one resource per distinct drug tuple — so its own occurrence
counts are dictionary size, not data volume; `occurrence_kind` marks that and
`build_statistics.py` reports the two in separate tables. See
`occurrences/README.md` for the re-run procedure and for why neither
`binding-analysis/distinct-codes.ndjson` nor the Pathling MCP tool's
`get_cardinality_and_top_values` could serve.

With the artifact present, `build_statistics.py` adds `occurrences_total`,
`occurrences_mapped` and `occurrence_coverage_pct` to each stream row, writes
`output/occurrence-buckets.csv`, and gives the HTML a per-element section with
the head of the distribution and each code's status. The buckets partition every
occurrence seven ways, and everything after `declined` is deliberately not one
number:

| bucket | meaning | the fix |
|---|---|---|
| `mapped` | resolvable via `$translate` | — |
| `declined` | a built stream considered the code and said no; its reason is in `unmapped-<stream>.csv` | nothing — this is the judgement |
| `blocked-upstream` | a built stream that maps nothing because the obstacle is outside terminology | the ETL |
| `unresolved-in-stream` | a stream owns the code and has no answer for it yet | `make generate-all-tables` |
| `no-map-for-element` | a stream resolved it; this element has no ConceptMap to serve the answer | a `build_*_cm_vs.py` |
| `no-stream-yet` | **no stream declares this population at all** | a declaration in `lib/streams.py` |
| `not-in-enumeration` | a code the data carries that no bound ValueSet admits; under a `required` binding that is an ETL or binding defect, so it should be empty | the binding, or the ETL |

Only `declined` is a judgement this repo would defend. Reporting it together
with an unbuilt population would misrepresent both, which is why the
element-level view exists alongside the per-stream one rather than instead of it.

The three backlogs are three buckets because they are three different jobs, and
one used to hide inside another: before the split,
`MedicationDispense.medication[x]` reported 14,240,367 occurrences as
`no-stream-yet` when only 1,550,601 of them had no stream — the other 12.7M were
streams that resolve perfectly, waiting on a builder for that element. The test
order in `element_sections` is what keeps them apart, and it runs
outermost-obstacle-first: no bound ValueSet, then no stream, then blocked, then
no map, then whatever the stream itself found. With the ConceptMap test first —
where it used to be — an element with no builder had *every* admitted occurrence
called backlog, which is how the 1.5M disappeared.

Attribution of a count to a stream is by code membership, not by source system:
`mimic-d-items` serves three populations, so only the enumerations can say which
stream a given d-item belongs to. Each stream therefore records the IG resource
its codes came from as `source_file` — the `stream` name alone is not enough,
because `mimic-microbiology-antibiotic` exists as both a CodeSystem and a
ValueSet and only the CodeSystem enumerates anything.

### How unmapped codes are recorded

A code a stream cannot resolve is recorded in **two** places, and
`verify_mappings.py` fails if they disagree:

- `unmapped-<stream>.csv` — the worklist, one per stream (its audience is
  whoever fixes a mapping table, and tables are per stream). The `reason`
  column says which kind of gap each row is:

      no-suitable-concept        the stream considered the code and declined,
                                 with the table row's comment as the reason —
                                 the only judgement this repo would defend
      no-row-in-curated-table    observed in the warehouse, but the table's
                                 generation population predates it — a backlog;
                                 `make generate-all-tables` is what fills it
      not-observed-in-data       used on NO bound element anywhere (a
                                 union-level fact from the occurrence counts)
      absent-from-all-built-releases   a notation stream's code missing from
                                 every built release — build the release
      no-stream-yet              a bound population NO stream declares. The
                                 whole file carries this reason: it is the
                                 synthesised worklist for a gap found by
                                 `lib/streams.undeclared()`, not a row inside a
                                 real stream's worklist

- every ConceptMap consuming the stream, as an element whose target has
  `equivalence: "unmatched"` and **no code**, carrying the same reason. This
  makes "considered, and there is deliberately no target" a machine-readable
  fact rather than a silent omission.

Note this is *not* `ConceptMap.group.unmapped`. That element is a fallback
**rule**, not a list — `provided` would make `$translate` return `0095` as
though it were a valid ICD-9-CM code, i.e. answer confidently with something
fabricated. A reported gap beats a silent wrong answer.

### The refine loop

A builder always writes `unmapped-<field>.csv`, empty or not. The goal is empty.
When it isn't, the fix is almost always a **missing input**, not a missing
judgement — build the release that has the code:

```sh
ls scripts/terminology-mapping/sources/icd10pcs/      # which years do I have?
make terminology ICD10PCS_YEARS="2016 2017 2018"      # build the missing one
make mappings                                          # re-check
```

## Layout

```
sources/            external release files, gitignored; per code system, per year
  icd9/{2012,2014}/  icd10cm/{2016..2019,2024}/  icd10pcs/{2016,2018,2019,2020}/
common/             shared helpers (TLS, HTTP, upload + $lookup smoke test, CLI)
terminology/        stage 1 — source files -> CodeSystem, one folder per system
  icd9/  icd10cm/  icd10pcs/
conceptmaps/        stage 2 — builders, the stream registry, shared machinery
  build_condition_cm_vs.py      Condition.code: names its streams, ~90 lines
  build_procedure_cm_vs.py      Procedure.code
  build_observation_cm_vs.py    Observation.code
  build_observation_component_cm_vs.py   Observation.component.code: its own binding
  lib/                          everything executable — see "the one rule about rules"
    streams.py                  EVERY STREAM, DECLARED ONCE: enumeration,
                                resolver, targets; builders reference names
  d-items-snomed.csv            one committed table per table-backed stream,
  labevents-loinc.csv  ...      read only through the registry
  build_d_items_table.py        one generator per table; network + code-search,
  build_labevents_table.py ...  run by hand via make <stream>-table
eval/               the manual table the generator replaced, kept as an answer key
  d-items-snomed-manual.csv     never read by the build
verify/             the checks, and stage 3's gate
  verify_mappings.py            verify_curated_snomed.py (needs the network)
upload.py           stage 3 — the only script that writes to a server
build_stream_reports.py resolves every stream once -> the statistics artefacts
build_statistics.py renders stream-report.json into the csv/html/terminal views
occurrences/        how often each coded value occurs; extracted once on the node
  count_occurrences.py          the node script (+ --dry-run, needs no warehouse)
  count_occurrences.slurm       the Petrichor job; read-only, never writes data
  elements.json                 the ten bound elements, read by BOTH sides
  code-occurrences.csv          the counts, committed — optional input to
                                build_statistics.py
  element-shapes.csv            which branch of a choice element each resource
                                took (only for elements declaring count_shapes)
  reference-occurrences.csv     codes reached through a Reference, weighted by
                                referring resources
  occurrence-summary.json       what was counted, and each CSV's sha256
output/             every generated resource, flat, ResourceType-id.json
  stream-report.json            one block per stream — THE statistics file
  unmapped-<stream>.csv         one worklist per stream, with reasons
  <field>-report.json           per-map totals and canonicals (ONLY= reads it)
  mapping-statistics.csv        one row per stream — the citable table; see
                                "Per-stream statistics"
  occurrence-buckets.csv        where every occurrence of a bound element goes
  <stream>-generation-log.json  what the last generator run saw, per row
input-manifest.json sha256 of every input that influences a generated resource
```

A code system's folder is keyed by its **canonical URL**, not by its source files.
That is why ICD-9-CM diagnoses and procedures share one folder and produce one
CodeSystem: THO assigns both to `http://hl7.org/fhir/sid/icd-9-cm`, so a `Coding`
cannot distinguish them and the server can only resolve that URI to one resource.
They are separated by a `kind` property instead.

## Code systems

| Script | Canonical URL | Output |
|---|---|---|
| `terminology/icd9/build_icd9cm_codesystem.py` | `http://hl7.org/fhir/sid/icd-9-cm` | `CodeSystem-icd-9-cm-2012.json` |
| `terminology/icd10cm/build_icd10cm_codesystem.py` | `http://hl7.org/fhir/sid/icd-10-cm` | `CodeSystem-icd-10-cm-<year>.json` |
| `terminology/icd10pcs/build_icd10pcs_codesystem.py` | `http://www.cms.gov/Medicare/Coding/ICD10` | `CodeSystem-icd-10-pcs-<year>.json` |

Every builder takes release years as positional arguments and shares the same
flags (`--base-dir`, `--out-dir`, `--fhir-base`, `--no-upload`, `--ca-bundle`,
`--insecure`). Which years get built comes from `ICD10_YEARS` /
`ICD10PCS_YEARS` in the `Makefile`.

Note that ICD-10-PCS is **not** under `hl7.org/fhir/sid/` the way the other two
are, and THO's own `icd10PCS` entry is a `content: not-present` stub with no
properties or filters — there is no upstream resource to copy from.

### ICD-9-CM carries both volumes in one resource

`CodeSystem-icd-9-cm-2012.json` holds Volumes 1-2 (diagnosis, `Dtab12.rtf`) and
Volume 3 (procedure, `Ptab12.RTF`) side by side, because THO lists ICD-9-CM
twice under the one canonical URL and they differ only in OID — `...6.103` for
diagnoses, `...6.104` for procedures. Both are carried as `identifier`, and a
`kind` property (`diagnosis` | `procedure`) is the only thing separating the two
trees. Two resources is not an option: `url` + `version` is the CodeSystem's
identity, so the second upload would be rejected as a conflict.

The merge is safe because the **dotted** forms are disjoint — diagnosis codes
have three characters before the dot (or a V/E prefix), procedure codes two —
and the builder asserts that rather than trusting it. The **dot-less** forms are
not: `4019` is both `401.9` (essential hypertension, one of the most common
codes in MIMIC) and `40.19`. Nothing in the string recovers the dot; only the
originating MIMIC table does. That is why the CMS long-description files are
applied per volume and never to a merged code list, and why any dot-less lookup
keyed on this URL must also carry `kind`.

Procedure expansion mirrors the diagnosis side — the tabular lists neither the
fourth digits of sections 38 and 77-80 (a `[0-9]` bracket under each covered
subcategory) nor those of sections 90-91 (no brackets; every subcategory takes
every digit the block defines). A subcategory with no bracket under a
bracket-using block takes no fourth digit at all and is a leaf in its own right,
which is what keeps `80.6` from being wrongly split into `80.60`-`80.69`. The
build verifies the expanded leaf set against `CMS29_DESC_LONG_SG.txt`, which is
authoritative for which procedure codes exist; it currently matches exactly
(3,877), and 3,738 of the generated displays are byte-identical to CMS before
the long descriptions are even applied.

### ICD-10-PCS is not shaped like ICD-10-CM

PCS codes are exactly seven characters, all of them billable, with no dots and no
category codes — so there is no `billable` property and no dot insertion. What it
has instead is a positional hierarchy, which the builder materialises as five
tiers:

| Tier | Chars | Count (FY2018) | Source |
|---|---|---|---|
| Section | 1 | 17 | tables XML, axis 1 |
| Body system | 2 | 109 | tables XML, axis 2 |
| Table | 3 | 873 | **CMS**, the flag-0 rows of the order file |
| Body part | 4 | 11,630 | tables XML, axis 4 |
| Code | 7 | 78,705 | order file, flag 1 |

Only the 7-character leaves are valid codes. Every shorter concept carries the
standard `notSelectable` property. **ValueSets built over this CodeSystem must
contain leaves only** — consumers are not obliged to honour `notSelectable`, and
at least one (the `code-search` service) ignores it entirely, so a grouper left in
a ValueSet will eventually be returned as an answer.

Two cross-checks the builder relies on: the order file's 78,705 flag-1 codes equal
the cross-product of every `pcsRow`'s axes in the tables XML, and its 873 flag-0
headers equal the number of `pcsTable` elements.

Designations come from the alphabetic index — the clinical vernacular
("Abdominohysterectomy", "Aqueduct of Sylvius") that appears nowhere in the
generated displays. The index targets the 4-character tier, so by default those
terms are also propagated down to the leaves, since consumers typically expand a
leaf-only ValueSet and would never see them otherwise. That propagation is what
takes the resource from 39 MB to 85 MB; `--no-propagate` turns it off.

Root-operation definitions (817 of the 873 tables have one; the rest are imaging
and other sections where character 3 is not an Operation) land on the 3-character
tier as `concept.definition`.

## Two ways a dot-less code lies to you

MIMIC stores every ICD code without dots, and that form is genuinely ambiguous.
Both mechanisms below are load-bearing, and the verifier checks them.

**1. `kind` — which volume is this?** Covered above: `4019` is both diagnosis
`401.9` and procedure `40.19`, so each bound field matches only its own volume.

**2. No cross-target fallback for procedures.** Diagnosis sources fall back from
ICD-9-CM to ICD-10-CM when a code misses, which is how the six codes MIMIC filed
under `icd_version` 9 that are really ICD-10-CM (`I509`, `J45901`, `O8612`,
`R270`, `S01312A`, `W01190A`) are found. Applying the same fallback to procedures
is actively harmful: **64 of MIMIC's 2,544 ICD-9 procedure codes are verbatim
valid 4-character ICD-10-PCS body-part groupers.** MIMIC procedure `0095` means
ICD-9 `00.95`, but as a raw string it matches PCS `0095` *"Subarachnoid Space,
Intracranial"* — an anatomical structure, not a procedure. Worse, it would map
silently and the unmapped report would then read zero. Procedure sources
therefore have exactly one target each, and PCS matches only 7-character leaves.

## What the verifier checks

`verify/verify_mappings.py` re-derives nothing. It reads the generated
artefacts and checks properties of them:

1. **Stream coverage** — every code in each stream's enumeration is mapped by
   every consuming ConceptMap or listed in `unmapped-<stream>.csv`, and the
   map's `unmatched` entries and the CSV agree. Nothing may be silently absent
   from both. (When the occurrence artifacts are absent, rows claiming
   `not-observed-in-data` are warned about rather than re-verified — the
   fact they claim lives in those artifacts.)
2. **ValueSet == ConceptMap target side** — the VS is the map's
   `targetCanonical`, so "member of the value set" and "reachable by
   `$translate`" must be the same set.
3. **Only releases built here** — a pinned release this repo has no source for
   produces an artefact that cannot be reproduced or redistributed.
4. **Only declared systems go unversioned** — see `UNVERSIONED_SYSTEMS`.
5. **No PCS grouper mappings** — the dot-less collision, checked explicitly.
6. **Completeness against the binding** — every code the element's bound
   ValueSet admits has an entry in its ConceptMap, mapped or `unmatched`;
   needs `sushi .` for the FSH-authored facades and says so otherwise.
7. **Stream ↔ map agreement** — every ConceptMap consuming a stream carries
   the IDENTICAL answers for that stream's codes. A stream resolves once
   (lib/assemble.py); two maps disagreeing means an artefact is stale, which
   is what a partial rebuild produces and why there are no partial builds.
8. **Partition disjointness** — streams sharing a source system must not
   overlap, or a code belongs to two streams and every statistic counts it
   twice.
9. **Partition coverage** — the other half of 8: every code any binding admits
   must belong to *some* stream. Disjointness stops the registry
   double-counting; nothing stopped it under-counting by simply not mentioning
   a population, and that failure is silent where an overlap is not — a stream
   that does not exist writes no row, no worklist and no warning. Check 6
   catches this per *map*, so it is blind to an element with no builder at all,
   which is where both undeclared populations were sitting.

Checks 2–8 are correctness bugs, and `--allow-unmapped` does not relax them.
Check 9 is a data gap of the same kind the worklists record, so its codes are
added to the unmapped count and gated the same way.

`verify_curated_snomed.py` is separate because it needs a server. It checks the
four things about a mapping target that no human can see by reading the CSV:
the concept **exists**, is **active**, is in the **international core module**
rather than a national extension, and its `snomed_display` really is one of its
designations. The third matters most for reproducibility — an AU- or US-only
concept resolves on the server it was picked from and nowhere else.

`build_d_items_table.py` applies these same four checks as it generates, so a
green `verify-curated` on a freshly generated table confirms the generator's
gate rather than discovering something new. It stays worth running: it is what
catches a table going stale as SNOMED retires concepts under a committed CSV.

## Source data layout (not committed)

The raw distributions are gitignored — download them and lay them out under
`sources/` as above, or point `$ICD_SOURCE_DIR` elsewhere. Order files are matched
by glob (`*order*<year>*.txt`) and XML by `rglob`, so CMS zips can be extracted
into the year folder as-is regardless of the folder names inside.

Verify what you have matches what the committed resources were built from:

```sh
uv run scripts/terminology-mapping/verify_inputs.py
```

Sources:

- ICD-10-CM and ICD-10-PCS: <https://www.cms.gov/medicare/coding-billing/icd-10-codes>
- ICD-9-CM 2012: CDC/CMS FY2012 (v29) distribution. Two zips: the CDC tabular
  RTFs (`Dtab12.rtf`, `Ptab12.RTF`) and the CMS long descriptions, which ship
  `CMS29_DESC_LONG_DX` and `CMS29_DESC_LONG_SG` together (DX = Volumes 1-2,
  SG = Volume 3). Both description files are optional — without them the
  contextless tabular titles are used, so `003.29` stays `"Other"` instead of
  `"Other localized salmonella infections"`.

ICD-9-CM RTF parsing uses the pure-Python `striprtf` package (pinned in the repo's
`pyproject.toml`), so all builds are cross-platform; the output was verified
byte-identical to the previous macOS `textutil`-based conversion.

## Output and reproducibility

Committed: `ConceptMap-*.json` and the two enumerated `ValueSet-*.json`. These
are the deliverables, and will eventually be released elsewhere.

Also committed: `unmapped-<field>.csv` and `<field>-report.json` — the record of
what could not be mapped and why, which is as much a result as the maps are.

Not committed: `CodeSystem-*.json` (36–85 MB each — attached as assets to the
GitHub release for the IG version they belong to; download from there to use them
without rebuilding).

**Rebuilds from unchanged inputs are byte-identical.** `date` is derived from the
newest input mtime rather than from `now`, so a re-run never churns the diff and
`git diff` on a committed artefact always means a real change. `make mappings &&
git diff --exit-code` is a valid test.

That test used to have a wrinkle, now fixed: the ConceptMap stage and the
ValueSet stage both wrote `unmapped-<field>.csv` with different columns, and
because `make mappings` ran them in order the ValueSet stage's five-column
version always won. `expected_code`, `expected_system` and `comment` were
therefore lost on every full build — including the per-code reasons a generated
table records for declining to map something, which was the most useful column in
the file. One builder now writes it once, in the full schema.

## Canonical base — why these are not in the IG

The ConceptMaps and the ValueSets they target live under **our own** base:

```
http://fhnaumann.github.io/mimic-profiles/fhir/ConceptMap/mimic-diagnosis-icd-to-sid
http://fhnaumann.github.io/mimic-profiles/fhir/ValueSet/mimic-diagnosis
http://fhnaumann.github.io/mimic-profiles/fhir/ConceptMap/mimic-procedure-merged-to-standard
http://fhnaumann.github.io/mimic-profiles/fhir/ValueSet/mimic-procedure-merged-standard
```

not under `http://mimic.mit.edu/fhir/mimic`, which belongs to the upstream IG's
publisher (KinD Lab). Minting new canonicals in someone else's namespace risks a
collision on a shared terminology server if upstream ever publishes at the same
URL. Referencing their canonicals is fine, and `sourceCanonical` deliberately
still points at their bound value sets.

The consequence is that these resources cannot live in `input/resources/`: the IG
publisher requires every resource it carries to have a url under the IG canonical.
They are uploaded straight to the terminology server instead, and nothing in
`input/fsh/` references them, so the IG build is unaffected.

## Consumer notes

A consumer starting from a bound element finds the right map without hardcoding
the pairing:

```
GET [base]/ConceptMap?source-uri=http://mimic.mit.edu/fhir/mimic/ValueSet/mimic-diagnosis-icd&_summary=true
```

- **Use `source-uri`, not `source`.** R4 defines both, but Ontoserver 6.x
  implements only `source-uri` — and matches it against `sourceCanonical`. Plain
  `source` returns `HTTP 400 not-supported`.
- **`_summary=true` is worth it.** The scope fields are summary elements and
  survive; `group` does not. That is ~1 KB instead of 8 MB. Fetch by id or pass
  `_summary=false` when you actually need `group.targetVersion`.
- **`$translate` does not return the release.** Ontoserver 6.27.3 does not echo
  `group.targetVersion` into the returned `Coding`. Codes present in only one
  release (the icd-10-cm 2024 tail, 43 codes) then fail `$validate-code` against
  the multi-version value set unless the version is restored from the map's group.
- **Drop `Coding.version` before reverse-translating.** A code is mapped into the
  *earliest* release containing it, so a coding stamped `version=2024` will not
  match a code filed in the 2016 group.
- **Omit `targetsystem` and OR every returned Coding into the filter.** The six
  relabeled codes mean an ICD-10-CM code can legitimately reverse-map to both
  `mimic-diagnosis-icd10|X` and `mimic-diagnosis-icd9|X`.
- **Filter out `unmatched`, not "everything except `equivalent`".** The
  declared-`unmatched` elements make `$translate` answer `result: true` with a
  Coding that names a system but carries **no code** — that is the point, it
  reports "considered, no target" rather than staying silent. A consumer that
  reads `match.concept` without checking gets a codeless Coding, so those must
  be dropped. Dropping everything that is not `equivalent` is a different and
  wrong thing: it discards every `relatedto` row, which is the whole ICU
  procedure population and the whole microbiology population — exactly the
  silent loss this merged map exists to prevent. Test for a **present target
  code**, and accept `relatedto` alongside `equivalent`. Note this means
  FHIRPath's `translate(url, false, 'equivalent')` is **not** the right call
  here, whatever an older version of this file said.
- **The SNOMED CT codes map to themselves.** Translating `Procedure.code` returns
  them unchanged rather than dropping them, so one `translate()` covers the whole
  merged column. They carry no `Coding.version`, and neither does the target
  value set's SNOMED include.
- **A SNOMED target is not necessarily a procedure.** The ICU items include
  events, findings and disorders that MIMIC files in `procedureevents` anyway
  (`225474 Fall`, `225465 Chest Pain`, `225472 Pneumothorax`,
  `225466 Cardiac Arrest`), and they map to the concept that actually means
  that, not to a procedure standing in for it. A consumer that assumes every
  target is `<< 71388002 |Procedure|` will be wrong for those rows. Check the
  target's own hierarchy rather than trusting the field it was mapped from.

## Context: the reverted migration

In July 2026 `Condition.code` was rewritten onto the standard `icd-9-cm` /
`icd-10-cm` systems and the IG re-bound to a matching ValueSet. **That migration
was reverted.** `Condition.code` is bound to `mimic-diagnosis-icd` again (the
union of the custom `mimic-diagnosis-icd9` / `mimic-diagnosis-icd10` CodeSystems)
and the data carries MIMIC's dot-less codes; translation to the standard systems
is a **read-time** concern, done through the ConceptMaps built here (e.g. the
`translate()` calls in `scripts/mimic-pipeline/probe-view-dwd.json`), not by
rewriting stored resources. Only the profile re-binding and the data rewrite were
reverted, and neither lived here.
