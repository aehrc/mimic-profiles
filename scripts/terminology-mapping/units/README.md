# Observation.valueQuantity units

Every unit string MIMIC records on `Observation.valueQuantity`, and whether it
is valid UCUM. The inventory a `mimic-units` → `http://unitsofmeasure.org`
mapping would be built from, and the count of how much data rides on each
string.

```sh
make validate-units          # offline, seconds
```

**No cluster run.** This is the third directory of its kind and the first that
does not touch the warehouse: `valueshapes/extract_value_shapes.py` already
extracted the unit population on the full 461M-row Delta warehouse and committed
it as the `units` column of `observation-value-shapes.csv`. `validate_units.py`
reads that column, so it is a pure function of a committed input in the same way
`make mappings` is — which is why it gets a `make` target where `occurrences/`
and `valueshapes/` deliberately do not.

| File | What |
|---|---|
| `mimic-units-validation.csv` | one row per distinct unit: the verdict, canonical form, how many Observation codes use it, occurrences, and three example Observation displays |
| `unit-validation-summary.json` | totals by verdict over both distinct strings and occurrences, the ucumate version, the sha256 of input and output |

## What the run found

**95 distinct strings, 182,241,362 occurrences. 43 valid, 52 invalid — and the
invalid ones carry 84.7M occurrences, 46% of the data.**

The invalid head is not exotic. It is ordinary clinical units spelled the way a
chart spells them, and nearly every one has an unambiguous UCUM equivalent:

| string | occurrences | codes | UCUM |
|---|---|---|---|
| `mmHg` | 25,401,973 | 87 | `mm[Hg]` |
| `mEq/L` | 19,977,995 | 49 | `meq/L` |
| `insp/min` | 9,642,142 | 9 | `/min` |
| `bpm` | 7,827,348 | 13 | `/min` |
| `IU/L` | 5,409,097 | 24 | `[IU]/L` |
| `sec` | 4,162,356 | 15 | `s` |
| `cmH2O` | 3,351,546 | 19 | `cm[H2O]` |
| `°F`, `°C` | 2,474,874 | 12 | `[degF]`, `Cel` |
| `mm Hg`, `mmHg.` | 1,054,660 | 10 | `mm[Hg]` — two more spellings of the row above |

That shape — a bracket convention, a case rule, a stray space — is what makes
this population worth a ConceptMap rather than a judgement call per row. It is
much closer to the ICD dot-insertion streams than to the ICU `d_items` table.

### `valid` is not a clean bill of health

Four strings parse as valid UCUM and mean something other than what MIMIC
intends. They are the reason `canonical_term` is a committed column: the verdict
alone hides them, and the dimension makes them obvious.

| string | codes it is on | parses as | intended |
|---|---|---|---|
| `K/uL` | Platelet Count, WBC | **Kelvin** per microlitre | `10*3/uL` |
| `m/uL` | Red Blood Cells | **metres** per microlitre | `10*6/uL` |
| `uU/ML` | TSH | microUnit per **megalitre** | `u[IU]/mL` |
| `N/A` | dRVVT Screen, SCT Screen | **Newton per Ampere** | not a unit at all |

Together 13,060,056 occurrences, all currently counted in the 43 "valid". This is the
same failure mode the ICU procedure table documents — the confidently wrong
answer scoring at least as well as the right one — and it is why nothing here
auto-promotes a `valid` verdict into a mapping.

The script does **not** try to detect these. Deciding that `K` is Kelvin here but
plausible elsewhere is a per-row clinical judgement, and this repo puts those in
a reviewed table rather than a heuristic.

### Duplicate spellings

Five pairs of distinct strings are the same unit at the same magnitude, so they
would collapse to one target:

    mL / ml            g/dL / g/dl        mL/min / ml/min
    mg/L / ug/mL       g/kg / mg/g

Reported by grouping on `canonical_term` **and** `canonical_magnitude`. The term
alone is a *dimension*, not a unit: nine MIMIC units canonicalise to `g.m-3`,
from `pg/mL` to `g/dL`, and calling those a collision would be wrong by six
orders of magnitude.

## What this cannot see

Two gaps, both needing a re-run of `valueshapes/extract_value_shapes.py` rather
than a change here. Neither blocks the mapping — the verdict on a string does
not change when the system URI beside it becomes known — and both are recorded
in `not_observed` in the summary JSON so a reader of that file alone cannot
mistake it for the whole picture.

- **`Quantity.system` is unknown.** The extractor selects it as `qty_system`
  and then drops it before the aggregation. So a `code` that is valid UCUM
  cannot be confirmed to sit *under* the UCUM system URI, and a code under some
  other system is not a UCUM claim at all. Fixing it is one column in
  `extract_value_shapes.py`'s `view.select`, plus the group key of pass 2.
- **A bare label is ambiguous.** The extractor writes `unit|code` only when a
  code exists *and* differs from the unit, so a label with no `|` means either
  `code == unit` or no code at all. Rows carry `code_known: no` rather than
  guessing. Only **3** of the 95 recorded a distinct code
  (`beats/minute|/min`, `breaths/minute|/min`, `F|[degF]`), and all three are
  valid.

  **Do not read that as "the other 92 are display-only strings."** The IG's own
  examples settle it the other way: `EX_MimicObservationLabevents.fsh` writes
  `valueQuantity = 1.3 $MimicUnits#mg/dL "mg/dL"`, so `code` and `unit` carry
  the *same* string and the extractor's encoding collapses them. Those 92 are
  coded — under `CodeSystem/mimic-units`, not under UCUM. So the 84.7M invalid
  occurrences are not absent UCUM claims; they are `Quantity.code` values in a
  local system that a ConceptMap can translate. See "Where this is going".

## What was built from it

`conceptmaps/build_units_cm_vs.py` — the ninth map — plus the committed table
`conceptmaps/units-ucum.csv` and its generator `build_units_table.py`. This file
supplied the inventory; the source side turned out to be the **CodeSystem**, not
these 95 strings, because MIMIC already codes its units:

| | |
|---|---|
| source | `ValueSet/mimic-units` — 505 concepts, `content: complete` |
| target | `http://unitsofmeasure.org` |
| resolver | `conceptmaps/units-ucum.csv`, gated by ucumate, offline |
| result | **505 rows: 299 mapped, 206 declined, collapsing to 169 distinct UCUM expressions** |

```sh
make units-table     # regenerate the table (offline, ucumate-gated)
make mappings        # build the map with everything else
```

Two things this file's 95-string view could not have told you:

- **The denominator is 505, not 95.** 95 is what `Observation.valueQuantity`
  uses; the rest are medication dosage strings, and about half of those are not
  units of measure at all. Of the 505, 87 parse as valid UCUM and 418 do not.
- **92 of the 95 observed strings are CodeSystem members.** The three that are
  not — `F`, `beats/minute`, `breaths/minute` — are exactly the three that
  carried a distinct `Quantity.code` (`[degF]`, `/min`, `/min`): display strings
  beside a correct UCUM code, which is the vital-signs profile already doing the
  right thing. The split between "coded under mimic-units" and "display beside
  real UCUM" is exactly clean.

### The gate found two defects this file had missed

The generator refuses to emit a row whose source is itself valid UCUM and whose
target has a different canonical form, unless that row carries a comment. Run
against the full 505 it fired on **nine** rows — the four listed above, and five
this file never saw, because they are medication units rather than observation
units:

    EA  -> {each}   the source parses as the EXA-AMPERE
    MG  -> mg       ... as the MEGAGAUSS  (M prefixing G, the gauss)
    Mg  -> mg       ... as the megagram — a different unit from `MG`, same string in two cases
    G   -> g        ... as the gauss
    u   -> [IU]     ... as the atomic mass unit

`MG` also corrected a comment that had been written by hand saying "megagram".
A rule that is decidable beats a reviewer reading a CSV, which is the whole
argument for making the gate fatal rather than advisory.

### What the mapping decided

- **Annotations kept**: `bpm` → `/min{beats}`, `insp/min` → `/min{insp}`. Both
  canonicalise to `s-1`, so no arithmetic changes; the annotation keeps the two
  distinguishable after translation, and 17.5M occurrences ride on them. Cost:
  MIMIC's own ETL chose plain `/min` where it populated a code itself.
- **Countable dose forms → annotations**: `tab` → `{tablet}`, `vial` →
  `{vial}`. Legal, dimensionless UCUM. A preparation descriptor that answers
  "what kind" rather than "how many" (`SOLN`, `OINT`, `LIQ`) is declined
  instead — annotating it would attach a number to something no number was
  recorded for.
- **`units` is declined**, despite 1.79M occurrences, because it is ambiguous
  *across* the codes carrying it: MIMIC records it on pH and on Heparin Dose per
  hour alike. A ConceptMap resolves one source code to one target regardless of
  the Observation it sits on, so any mapping would make one population wrong.
- **`equivalence: equivalent`**, unlike every other curated table in this repo.
  These rows restate a unit's notation rather than assert an undirected
  relationship, so filtering on `equivalent` keeps this field.

### Still open

`Quantity.code` is bound by no profile — the only mention in `input/fsh/` is the
`$MimicUnits` alias. The map builds and publishes regardless, but
`verify_mappings` reports `completeness NOT CHECKED` for the element,
`streams.undeclared()` cannot see the population, and the stream carries
`outside_occurrence_extract: True` so its codes are not reported as
never-observed on the strength of an extract that never covered them. Adding the
binding plus an `occurrences/elements.json` entry closes all three.

## Notes

One quirk worth knowing: **ucumate 1.0.8 returns no parser text.**
`ValidationFailure.messages` is `['']` for every failure, so the `messages`
column is present and always empty. It is kept rather than dropped because the
column is the right place for that text when a later version supplies it.
