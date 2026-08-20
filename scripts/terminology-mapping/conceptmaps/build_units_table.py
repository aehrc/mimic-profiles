#!/usr/bin/env python3
"""Generate conceptmaps/units-ucum.csv — MIMIC unit strings to UCUM.

THE ONE GENERATOR IN THIS REPO THAT NEEDS NO NETWORK. Every other table asks a
model-backed code-search service for a clinical concept and gates the answer
against a terminology server, which is why `make mappings` keeps them at arm's
length and why their rows rest on a confidence threshold. UCUM is a GRAMMAR, not
an enumeration: there is no concept to look up, and a proposed target is either
a parseable expression or it is not. So the gate here is a parser (ucumate),
it runs offline, it is decidable, and it fires on every row — which makes this
the only committed table in this repo whose every mapping is machine-checkable.

What is NOT machine-checkable is which unit a MIMIC string MEANT, and that is
where the judgement lives. It is written down as data in MAPPINGS below rather
than derived, because no rule connects `bpm` to `/min{beats}` and `K/uL` to
`10*3/uL`; a lexical rewrite engine over these strings is precisely the
confident-and-wrong machine the ICU d_items docstring argues against.

VALIDITY OF THE SOURCE IS NOT THE ORGANISING PRINCIPLE. It is tempting to treat
"already valid UCUM" as "already correct" and map only the rest. Four strings
carrying 13,060,056 occurrences say otherwise — they parse perfectly and denote
something other than what MIMIC records:

    K/uL   on Platelet Count, WBC   parses as KELVIN per microlitre  -> 10*3/uL
    m/uL   on Red Blood Cells       parses as METRES per microlitre  -> 10*6/uL
    uU/ML  on TSH                   microUnit per MEGAlitre          -> u[IU]/mL
    N/A    on dRVVT Screen          NEWTON PER AMPERE                -> declined

So every code gets an answer or a decline on its merits, and a rule catches
this class rather than a reviewer's attention: WHERE THE SOURCE STRING IS ITSELF
VALID UCUM AND ITS CANONICAL FORM DIFFERS FROM THE TARGET'S, THE ROW MUST CARRY
A COMMENT (see _check_dimension). A mapping that silently changes what a number
means is exactly the failure this repo refuses elsewhere, and here it is
detectable, so it is detected rather than trusted to review.

TWO POPULATIONS IN ONE CODESYSTEM. `mimic-units` is 505 concepts and they are
not one kind of thing:

  ~92   units MIMIC records on Observation.valueQuantity, 182M occurrences.
        Ordinary clinical units spelled the way a chart spells them — `mmHg`,
        `mEq/L`, `cmH2O`, `°F` — each with one unambiguous UCUM equivalent.
        This is the population units/mimic-units-validation.csv measured.
  ~413  medication DOSAGE units, from the prescription and infusion columns.
        About half are not units of measure at all: dose forms (`tab`, `vial`,
        `PUFF`), whole quantities belonging in another field (`(1,000 mg)`,
        `mEq / 250 mL NS`), and ETL artefacts (`mg\\ 0 mg`, `Umits`, `tiwst`).

ANNOTATIONS ARE KEPT. `bpm` maps to `/min{beats}` and not to `/min`, and
`insp/min` to `/min{insp}`. Both forms are valid and both canonicalise to
`s-1`, so this changes no arithmetic; what it buys is that the two stay
distinguishable after translation, which plain `/min` does not — 17.5M
occurrences ride on those two strings alone. The cost is that MIMIC's own ETL
chose plain `/min` where it populated a UCUM code itself, so a consumer joining
translated MIMIC data against untranslated MIMIC data will see two spellings of
one unit. That is a stated trade, made once here rather than per row.

FOUR TIERS, in order, and the first that answers wins:

  curated     MAPPINGS — the hand-authored answers, one per source code. Where
              a mapping needs defending it carries a COMMENTS entry.
  dose-form   DOSE_FORMS — a countable presentation mapped to the dimensionless
              UCUM annotation naming it, `tab` -> `{tablet}`. Legal UCUM, and
              the form FHIR's own examples use for counting doses.
  declined    DECLINED — considered and deliberately not mapped, with the reason
              on the row. Then _ARTEFACT, a STATED RULE rather than a list: a
              source string carrying a digit, a backslash, a tilde or an
              asterisk, or wrapped in parentheses, is a quantity or an ETL
              artefact rather than a unit. It runs LAST so an explicit answer
              always wins, which is why `mg/m2`, `cm3` and `10*3/uL` are
              unaffected.
  no row      everything else. NOT an error and not a decline: the build reports
              it as `no-row-in-curated-table`, the ordinary backlog reason, and
              it is the honest state for a code nobody has looked at.

Deliberately covers the WHOLE enumeration rather than lib/builders.table_population's
observed narrowing. That narrowing exists to keep thousands of never-used labels
out of a paid, model-backed service; here a row costs a dict lookup and a parse,
and the occurrence artifact does not describe this element anyway (see the
`units` stream in lib/streams.py).

Outputs:
  conceptmaps/units-ucum.csv          the committed table the build reads
  output/units-generation-log.json    what this run decided, per tier

Usage:
  make units-table
  uv run scripts/terminology-mapping/conceptmaps/build_units_table.py
  uv run .../build_units_table.py --dry-run     # report, write nothing
"""

import argparse
import csv
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common import paths                                          # noqa: E402
from conceptmaps.lib.canonical import TABLE_DIR                   # noqa: E402
from conceptmaps.lib.streams import enumeration, get              # noqa: E402

STREAM = "units"
TABLE = TABLE_DIR / "units-ucum.csv"
LOG_NAME = "units-generation-log.json"

# The columns lib/curated.py reads, plus this generator's provenance. The
# provenance is COMPUTED, not recorded from a service: every column after
# `comment` is a fact ucumate re-derives from the two code columns, so a reader
# can audit any row without running anything, and a row cannot disagree with
# itself.
COLUMNS = [
    "mimic_code", "mimic_display", "ucum_code", "ucum_display", "comment",
    "tier", "source_valid_ucum", "source_canonical", "target_canonical",
    "dimension_changed",
]


# --------------------------------------------------------------------------- #
# Tier 1: the curated answers.
# --------------------------------------------------------------------------- #

# Observation.valueQuantity — the 182M-occurrence population. Ordered roughly by
# occurrence so the head of the distribution reads first.
_OBSERVATION = {
    "%": "%",
    "mmHg": "mm[Hg]",
    "mg/dL": "mg/dL",
    "mEq/L": "meq/L",
    "K/uL": "10*3/uL",
    "insp/min": "/min{insp}",
    "bpm": "/min{beats}",
    "g/dL": "g/dL",
    "IU/L": "[IU]/L",
    "fL": "fL",
    "ml": "mL",
    "sec": "s",
    "cmH2O": "cm[H2O]",
    "m/uL": "10*6/uL",
    "pg": "pg",
    "L/min": "L/min",
    "mL": "mL",
    "°F": "[degF]",
    "mmol/L": "mmol/L",
    "#/hpf": "/[HPF]",
    "mm Hg": "mm[Hg]",
    "ml/hr": "mL/h",
    "ng/mL": "ng/mL",
    "cm": "cm",
    "°C": "Cel",
    "g/dl": "g/dL",
    "Ratio": "1",
    "uIU/mL": "u[IU]/mL",
    "#/uL": "/uL",
    "ug/dL": "ug/dL",
    "kg": "kg",
    "ml/min": "mL/min",
    "pg/mL": "pg/mL",
    "ug/mL": "ug/mL",
    "cmH2O/L/seconds": "cm[H2O].s/L",
    "mg/L": "mg/L",
    "mA": "mA",
    "ng/dL": "ng/dL",
    "#/lpf": "/[LPF]",
    "mOsm/kg": "mosm/kg",
    "mV": "mV",
    "mm/hr": "mm/h",
    "mg/g": "mg/g",
    "mg/mg": "mg/mg",
    "min": "min",
    "Inch": "[in_i]",
    "mIU/mL": "m[IU]/mL",
    "U/mL": "U/mL",
    "mL/beat": "mL/{beat}",
    "mmHg.": "mm[Hg]",
    "umol/L": "umol/L",
    "RPM": "/min{rev}",
    "L/min/m2": "L/min/m2",
    "mg/24hr": "mg/(24.h)",
    "IU/mL": "[IU]/mL",
    "ng/mL FEU": "ng/mL{FEU}",
    "nmol/L": "nmol/L",
    "/min": "/min",
    "mL/m2": "mL/m2",
    "dynes.sec.cm-5/m2": "dyn.s/(cm5.m2)",
    "dynes*sec/cm5/m2": "dyn.s/(cm5.m2)",
    "dynes*sec/cm5": "dyn.s/cm5",
    "U/g/Hb": "U/g{Hb}",
    "GPL": "[GPL'U]",
    "MPL": "[MPL'U]",
    "ml/kg": "mL/kg",
    "U": "U",
    "hour": "h",
    "Liters": "L",
    "lbs": "[lb_av]",
    "ppm": "[ppm]",
    "psi": "[psi]",
    "hrs": "h",
    "mL/min": "mL/min",
    "kcal/kg": "kcal/kg",
    "g/kg": "g/kg",
    "msec": "ms",
    "U/L": "U/L",
    "uU/ML": "u[IU]/mL",
    "Degree": "deg",
    "Score": "{score}",
    "years": "a",
    "ng/mL DDU": "ng/mL{DDU}",
    "/hpf": "/[HPF]",
    "BU": "[beth'U]",
    "kcal/day": "kcal/d",
}

# Medication dosage. Only the strings whose intent is unambiguous — a case fix,
# a spelled-out word, or a rate written with `/hr` instead of `/h`. Anything
# needing a guess about WHAT is being dosed is declined or left to the backlog.
_MEDICATION = {
    # mass
    "mg": "mg", "MG": "mg", "Mg": "mg",
    "gram": "g", "GRAM": "g", "grams": "g", "Grams": "g", "gm": "g", "g": "g",
    "G": "g",
    "milligrams": "mg", "mcg": "ug", "MCG": "ug", "nanogram": "ng",
    # volume
    "ML": "mL", "mls": "mL", "cc": "mL", "cm3": "cm3", "L": "L",
    "uL": "uL", "nL": "nL", "pL": "pL", "mm^3": "mm3", "/mm3": "/mm3",
    # amount of substance / activity
    "mmol": "mmol", "meq": "meq", "mEq": "meq", "mEQ": "meq", "mEq.": "meq",
    "unit": "[IU]", "Unit": "[IU]", "UNIT": "[IU]", "_UNIT": "[IU]",
    "Units": "[IU]", "UNITS": "[IU]", "u": "[IU]",
    "International Units": "[IU]", "IU": "[IU]",
    "million units": "10*6.[IU]", "Million Units": "10*6.[IU]",
    # rates over time
    "/hour": "/h", "/hr": "/h",
    "mg/h": "mg/h", "mg/hr": "mg/h", "mg/hour": "mg/h", "Mg/hr": "mg/h",
    "g/h": "g/h", "g/hr": "g/h", "gm/hr": "g/h", "grams/hour": "g/h",
    "mcg/h": "ug/h", "mcg/hr": "ug/h", "mcg/hour": "ug/h",
    "mL/h": "mL/h", "mL/hr": "mL/h", "mL/hour": "mL/h", "cc/hr": "mL/h",
    "mg/min": "mg/min", "mgs/min": "mg/min", "mg//min": "mg/min",
    "mcg/min": "ug/min", "grams/min": "g/min",
    "mEq/hr": "meq/h", "mEq / hr": "meq/h", "mEq./hour": "meq/h",
    "unit/hour": "[IU]/h", "units/hour": "[IU]/h", "units/hr": "[IU]/h",
    "Units/Hr": "[IU]/h", "UNIT/HR": "[IU]/h", "U/hr": "[IU]/h",
    "units/min": "[IU]/min", "MILLI UNITS/MIN": "m[IU]/min",
    # rates per day
    "mg/day": "mg/d", "mg/24h": "mg/d", "mg/24 hour": "mg/d",
    "mg/24 hr": "mg/d", "mcg/day": "ug/d", "ml/day": "mL/d", "mL/Day": "mL/d",
    # per body weight
    "mg/kg": "mg/kg", "mcg/kg": "ug/kg",
    "mg/kg/min": "mg/(kg.min)", "mg/kg/hr": "mg/(kg.h)",
    "mg/kg/hour": "mg/(kg.h)",
    "mcg/kg/min": "ug/(kg.min)", "MCG/KG/MIN": "ug/(kg.min)",
    "mcg/kg/hr": "ug/(kg.h)", "mcg/kg/hour": "ug/(kg.h)",
    "Mcg/kg/hr": "ug/(kg.h)",
    "ng/kg/min": "ng/(kg.min)", "nanograms/kg/minute": "ng/(kg.min)",
    "mL/kg/hour": "mL/(kg.h)",
    "Units/kg": "[IU]/kg", "UNIT/KG": "[IU]/kg", "Units/Liter": "[IU]/L",
    "units/kg/hour": "[IU]/(kg.h)", "units/kg/hr": "[IU]/(kg.h)",
    "UNIT/kg/HR": "[IU]/(kg.h)",
    "unit/mL": "[IU]/mL", "unit/gram": "[IU]/g",
    # concentration and body surface
    "mg/mL": "mg/mL", "mg/ml": "mg/mL", "mcg/mL": "ug/mL", "mcg/ml": "ug/mL",
    "mg/m2": "mg/m2", "mL/mL": "mL/mL", "per L": "/L",
    # per administration event
    "mg/dose": "mg/{dose}", "mcg/dose": "ug/{dose}",
    "mg/actuation": "mg/{actuation}", "mcg/actuation": "ug/{actuation}",
    "mcg/spray": "ug/{spray}",
    # counts of things
    "cell": "{cell}", "Million Cells": "10*6.{cells}",
    "billion cell": "10*9.{cells}",
    # imperial, as MIMIC spells it
    "in": "[in_i]", "INCH": "[in_i]", "ounces": "[oz_av]", "tsp": "[tsp_us]",
    # per container, where the container is the thing dispensed
    "mL/Lumen": "mL/{lumen}", "mL/Syringe": "mL/{syringe}",
    # enzyme activity, lower-cased
    "nMol/ml/min": "nmol/(mL.min)",
}

MAPPINGS = {**_OBSERVATION, **_MEDICATION}

# Prose for the rows where the code pair alone would mislead. Keyed on
# (mimic_code, ucum_code) so a note cannot survive its target being changed, and
# an entry matching no row is FATAL rather than skipped — the same contract as
# COMMENT_OVERRIDES in the code-search generators.
#
# Every row whose source parses as valid UCUM with a different canonical form
# MUST appear here; _check_dimension enforces it, so this table cannot silently
# lose the `K/uL` class.
COMMENTS = {
    ("K/uL", "10*3/uL"):
        "MIMIC writes `K` for `thousands`, on Platelet Count, White Blood "
        "Cells and 15 other haematology items. As UCUM the source string is "
        "valid and denotes KELVIN per microlitre, so this row changes what the "
        "number means rather than only how it is written — which is the point: "
        "the source spelling was wrong, not merely non-standard.",
    ("m/uL", "10*6/uL"):
        "MIMIC writes `m` for `millions`, on Red Blood Cells and Reticulocyte "
        "Count. As UCUM the source string is valid and denotes METRES per "
        "microlitre. Same class as `K/uL`.",
    ("uU/ML", "u[IU]/mL"):
        "Two case errors in one string, on Thyroid Stimulating Hormone. As "
        "UCUM `ML` is the MEGAlitre, so the source parses and denotes "
        "microUnits per megalitre — out by nine orders of magnitude. The "
        "intended unit is the microInternational Unit per millilitre.",
    ("MG", "mg"):
        "As UCUM `MG` is the MEGAGAUSS — `M` prefixing `G`, the gauss — so the "
        "source is not merely the wrong scale but the wrong DIMENSION "
        "entirely. MIMIC means the milligram; the string is a case error in a "
        "prescription column.",
    ("Mg", "mg"):
        "As UCUM `Mg` is the MEGAgram, a thousand million times the intended "
        "milligram. Note this differs from `MG` in the same table, which is "
        "not a mass at all — the two case variants of one MIMIC string parse "
        "as two unrelated units.",
    ("ML", "mL"):
        "As UCUM `ML` is the MEGAlitre. MIMIC means the millilitre.",
    ("G", "g"):
        "As UCUM `G` is the gauss, a unit of magnetic flux density. MIMIC "
        "means the gram.",
    ("u", "[IU]"):
        "As UCUM a bare `u` is the atomic mass unit. In MIMIC's prescription "
        "columns it is an abbreviation of `unit`, which for the drugs dosed "
        "this way (insulin, heparin) is the International Unit.",
    ("EA", "{each}"):
        "`EA` is `each`, a dispensing count. As UCUM it parses — as the "
        "EXA-AMPERE, 10^18 amperes. Found by _check_dimension rather than by "
        "reading the table, which is the whole argument for that gate: it is "
        "the same class as `K/uL` and `N/A`, and nobody had noticed it.",
    ("Ratio", "1"):
        "A dimensionless ratio of two like quantities — Cholesterol "
        "Total/HDL, Protein/Creatinine, CD4/CD8. UCUM spells that `1`. The "
        "source string names the KIND of quantity rather than a unit, so no "
        "scale information is lost here; there was none to lose.",
    ("Score", "{score}"):
        "Leukocyte Alkaline Phosphatase score: a dimensionless clinical "
        "score, not a measured quantity. Mapped to an annotated `1` so it "
        "stays distinguishable from a true ratio after translation.",
    ("U", "U"):
        "Left as the UCUM enzyme unit, which is what the string literally "
        "says. Note the three Observation codes carrying it are displayed `I`, "
        "`H` and `L`, which do not identify an assay — so this row is the "
        "literal reading rather than a confirmed one, and a consumer needing "
        "the assay's own unit should not rely on it.",
    ("bpm", "/min{beats}"):
        "The `{beats}` annotation is carried deliberately. It is dimensionless "
        "to UCUM — this canonicalises to `s-1` exactly as plain `/min` does — "
        "and it keeps beats per minute distinguishable from breaths per minute "
        "after translation. Note MIMIC's own ETL chose plain `/min` where it "
        "populated a UCUM code itself, so translated and untranslated MIMIC "
        "data will differ in spelling here.",
    ("insp/min", "/min{insp}"):
        "See `bpm`. `insp` is inspirations; the annotation keeps this distinct "
        "from heart rate after translation.",
    ("mL/beat", "mL/{beat}"):
        "Stroke volume. `{beat}` is an annotation, so this is millilitres to "
        "UCUM, which is the correct dimension for a per-beat volume.",
    ("RPM", "/min{rev}"): "Revolutions per minute, on ICU device settings.",
    ("U/g/Hb", "U/g{Hb}"):
        "Quantitative G6PD, reported per gram of haemoglobin. `{Hb}` annotates "
        "the gram rather than dividing by it a second time — the source "
        "string's second `/` is not a division.",
    ("ng/mL FEU", "ng/mL{FEU}"):
        "D-dimer in Fibrinogen Equivalent Units. FEU is a reporting "
        "convention, not a unit, so it annotates rather than scales; a "
        "consumer must NOT compare an FEU value with a DDU value numerically.",
    ("ng/mL DDU", "ng/mL{DDU}"):
        "D-dimer in D-Dimer Units, the other of the two conventions. See "
        "`ng/mL FEU` — the two differ by roughly a factor of two and this "
        "mapping does not reconcile them.",
    ("mOsm/kg", "mosm/kg"):
        "Osmolality. UCUM's osmole is `osm`, lower case, with the milli "
        "prefix spelled `m`.",
    ("mg/24hr", "mg/(24.h)"):
        "A 24-hour urine collection. Written as `mg/(24.h)` rather than "
        "`mg/d` to keep the collection period the source states, which is what "
        "the result is actually normalised to.",
    ("cmH2O/L/seconds", "cm[H2O].s/L"):
        "Airway resistance. The source's two `/` are not both divisions — the "
        "quantity is pressure x time / volume — so this row reorders the "
        "expression rather than transcribing it.",
    ("Degree", "deg"):
        "Head of Bed Measurement: an angle in degrees of arc, not a "
        "temperature.",
    ("Liters", "L"): "Spelled-out litre, on a fluid volume.",
    ("BU", "[beth'U]"):
        "Bethesda units, on Factor IX Inhibitor. One occurrence in the whole "
        "warehouse.",
    ("GPL", "[GPL'U]"):
        "IgG phospholipid units, on Anticardiolipin Antibody IgG.",
    ("MPL", "[MPL'U]"):
        "IgM phospholipid units, on Anticardiolipin Antibody IgM.",
    ("cc", "mL"):
        "Cubic centimetre as prescribers write it. Exactly equal to the "
        "millilitre, so nothing is lost; normalised because `cc` is not UCUM.",
    ("million units", "10*6.[IU]"):
        "Penicillin and similar, dosed in millions of International Units.",
    ("Million Units", "10*6.[IU]"): "See `million units`.",
    ("mm^3", "mm3"):
        "Cubic millimetre. The `^` is not UCUM exponent notation; UCUM writes "
        "the exponent as a bare digit.",
}

# --------------------------------------------------------------------------- #
# Tier 2: dose forms.
# --------------------------------------------------------------------------- #

# A COUNTABLE presentation, mapped to the dimensionless UCUM annotation naming
# it. `1 {tablet}` is valid UCUM and is the form FHIR's own dosage examples use.
#
# Only forms that can be COUNTED are here. A product descriptor that answers
# "what kind of preparation" rather than "how many" — `SOLN`, `OINT`, `GEL`,
# `LIQ`, `SUSP`, `CONC` — is not a quantity at all and is declined by
# NOT_A_QUANTITY below, because annotating it would put a number against
# something no number was recorded for.
DOSE_FORMS = {
    "tab": "{tablet}", "Tab": "{tablet}", "TAB": "{tablet}",
    "tablet": "{tablet}", "tablets": "{tablet}", "tabs": "{tablet}",
    "tABS": "{tablet}",
    "cap": "{capsule}", "Cap": "{capsule}", "CAP": "{capsule}",
    "caps": "{capsule}", "capsule": "{capsule}", "capsules": "{capsule}",
    "cp": "{capsule}", "cps": "{capsule}",
    "vial": "{vial}", "Vial": "{vial}", "VIAL": "{vial}",
    "puff": "{puff}", "PUFF": "{puff}", "puffs": "{puff}", "PUFFS": "{puff}",
    "drop": "{drop}", "Drop": "{drop}", "DROP": "{drop}", "drops": "{drop}",
    "DROPs": "{drop}", "DROPS": "{drop}", "DRP": "{drop}",
    "gtt": "{drop}", "GTT": "{drop}",
    "patch": "{patch}", "Patch": "{patch}", "PTCH": "{patch}",
    "PTCHS": "{patch}",
    "SUPP": "{suppository}",
    "neb": "{nebule}", "Neb": "{nebule}", "NEB": "{nebule}",
    "syringe": "{syringe}", "Syringe": "{syringe}", "SYR": "{syringe}",
    "bag": "{bag}", "BAG": "{bag}", "BAGS": "{bag}",
    "bottle": "{bottle}", "Bottle": "{bottle}", "btl": "{bottle}",
    "BTL": "{bottle}",
    "packet": "{packet}", "PKT": "{packet}", "PACK": "{packet}",
    "lozenge": "{lozenge}", "lozenges": "{lozenge}", "LOZ": "{lozenge}",
    "TROC": "{troche}",
    "enema": "{enema}", "Enema": "{enema}", "ENEMA": "{enema}",
    "Enemas": "{enema}", "ENE": "{enema}",
    "appl": "{applicator}", "Appl": "{applicator}",
    "application": "{application}",
    "SPRY": "{spray}", "AMP": "{ampule}", "PEN": "{pen}", "RING": "{ring}",
    "tube": "{tube}", "TUBE": "{tube}", "film": "{film}", "FILM": "{film}",
    "SWAB": "{swab}", "pills": "{pill}",
    "dose": "{dose}", "Dose": "{dose}", "DOSE": "{dose}", "doses": "{dose}",
    "ea": "{each}", "EA": "{each}",
    "CAN": "{can}", "JAR": "{jar}", "KIT": "{kit}", "CUP": "{cup}",
    "sheet": "{sheet}", "STRP": "{strip}",
    "scp": "{scoop}", "SCOOP": "{scoop}",
    "gummies": "{gummy}", "GUM": "{gum}",
}

# --------------------------------------------------------------------------- #
# Tier 3: declines.
# --------------------------------------------------------------------------- #

_AMBIGUOUS = (
    "Ambiguous across the Observation codes that carry it, so no single target "
    "is correct: MIMIC records it on pH (a dimensionless log activity, UCUM "
    "`[pH]`) and on Heparin Dose per hour (International Units per hour) "
    "alike. A ConceptMap resolves a source code to one target regardless of "
    "the Observation it sits on, so mapping this string would make one of "
    "those two populations wrong. The fix is upstream, in the ETL that wrote "
    "one unit string for two quantities.")

_NO_LOG = (
    "UCUM has no logarithm operator — `[lg]` is not a unit — so a log10 "
    "concentration cannot be written as a UCUM expression at all. Declined "
    "because the alternative is dropping the `log10` and publishing a target "
    "that claims the value is a linear concentration, which would be wrong by "
    "orders of magnitude and silent.")

NOT_A_QUANTITY = (
    "A preparation descriptor rather than a quantity: it answers what kind of "
    "product this is, not how much was given. Unlike the countable dose forms "
    "it cannot be annotated, because annotating it would attach a number to "
    "something no number was recorded for.")

_COMBINATION = (
    "Names one unit per ingredient of a combination product rather than one "
    "unit of measure — the string is a list. UCUM has no expression for `the "
    "unit of each of several ingredients`, and picking either component would "
    "attach the whole value to one of them. The fix is upstream: a combination "
    "product needs one ingredient per Dosage entry, each with its own "
    "Quantity.")

DECLINED = {
    "units": _AMBIGUOUS,
    "mcg-mg/mL": _COMBINATION,
    "mcg'ml-mg/ml": _COMBINATION,
    "mg-mcg": _COMBINATION,
    "mg-mg": _COMBINATION,
    "mg-mg-mcg-mg": _COMBINATION,
    "unit-mg-unit": _COMBINATION,
    "EU/dL": (
        "Ambiguous: `EU` is used for both Ehrlich units (urinary "
        "urobilinogen) and endotoxin units, which are unrelated quantities. "
        "MIMIC gives no way to tell which assay this row belongs to."),
    "MU": (
        "Ambiguous between the megaunit and an abbreviation of milliunit — a "
        "factor of 10^9 apart. Not resolvable from the string, and guessing "
        "either would misstate a dose."),
    "mL UDCUP": (
        "A volume fused with its container (unit-dose cup). The quantity is "
        "millilitres; the container belongs in the dispense record rather "
        "than in the unit."),
    "mg ER": (
        "A mass fused with a release characteristic (extended release). The "
        "quantity is milligrams; `ER` describes the formulation and belongs "
        "in the medication reference."),
    "mg/omg": "An ETL artefact: a zero mis-typed as the letter o.",
    "mgmg": "An ETL artefact: the unit string `mg` duplicated.",
    "log10 IU/mL": _NO_LOG,
    "log10 copies/mL": _NO_LOG,
    "log10 cop/mL": _NO_LOG,
    "N/A": (
        "The literal string `N/A`, recorded on 28 Observation codes including "
        "dRVVT and SCT screens, where the result is a ratio reported without "
        "a unit. It is a placeholder, not a unit. Note it parses as valid "
        "UCUM — NEWTON PER AMPERE — which is why it must be declined "
        "explicitly rather than left to a validity check to catch."),
    "+/-": (
        "A qualitative result marker on HCG, Urine, Qualitative. Not a unit; "
        "the value it accompanies is not a measured quantity."),
    "Pos/Neg": (
        "A qualitative result marker, not a unit. The Observation carrying it "
        "should use valueCodeableConcept rather than valueQuantity."),
    "-": "A placeholder for a missing unit, not a unit.",
    "___": "A placeholder for a missing unit, not a unit.",
    "gr": (
        "Ambiguous between the apothecary grain (UCUM `[gr]`, 64.8 mg) and an "
        "abbreviation of gram, which differ by a factor of 15. MIMIC gives no "
        "way to tell which was meant, and choosing either would silently "
        "rescale a dose."),
    "GR": "See `gr` — the same ambiguity, in upper case.",
    "gg": "Not a unit. No expansion of this string is recorded in MIMIC.",
    "gmgm": "An ETL artefact: the unit string `gm` duplicated.",
    "mEqmEq": "An ETL artefact: the unit string `mEq` duplicated.",
    "Umits": "A misspelling of `units`, and inheriting its ambiguity.",
    "tiwst": "A misspelling with no recoverable intent.",
    "mcq": (
        "Most likely a misspelling of `mcg`, but this generator does not "
        "correct spelling it cannot confirm: mapping it to the microgram "
        "would rest on a guess about a prescription dose."),
    "mch/kg/min": (
        "Most likely a misspelling of `mcg/kg/min`. Declined for the same "
        "reason as `mcq` — a guessed correction on an infusion rate."),
    "Notify": "A workflow instruction, not a unit.",
    "MD to order daily dose": "A workflow instruction, not a unit.",
    "bo": "Not a unit. No expansion of this string is recorded in MIMIC.",
    "NG/": "A truncated unit string; the denominator is missing.",
    "drop ou": (
        "`ou` is the administration site (oculus uterque, both eyes), not part "
        "of the unit. The quantity is `{drop}`, but the site belongs in "
        "Dosage.site rather than in the unit, and this generator does not "
        "split a source string across two fields."),
    "HALF TAB": (
        "A fractional quantity fused into the unit string. The value is 0.5 "
        "and the unit `{tablet}`, and splitting the two is an ETL fix rather "
        "than a mapping — a ConceptMap can only supply the unit."),
    "Quarter Tab": "See `HALF TAB`.",
    "PE (Phenytoin Sodium Equivalent)":
        "Names a dose-equivalence convention rather than a unit. Fosphenytoin "
        "is dosed in phenytoin sodium equivalents, which UCUM cannot express; "
        "`mg` alone would drop the convention and make the dose ambiguous.",
    "mg PE": "See `PE (Phenytoin Sodium Equivalent)`.",
    "mg PE/kg": "See `PE (Phenytoin Sodium Equivalent)`.",
    "Units VWF:RCo": (
        "Von Willebrand factor ristocetin cofactor activity units. An "
        "assay-specific activity unit with no UCUM expression; `[IU]` would "
        "lose the assay the value is only interpretable against."),
    "Units Humalog": (
        "An insulin unit qualified by the PRODUCT. The quantity is `[IU]`, but "
        "the product belongs in the medication reference rather than the "
        "unit, and mapping it to `[IU]` alone would let two different insulins "
        "compare as equal."),
    "Units Insulin 70 / 30": "See `Units Humalog`.",
    "Units Insulin Glargine": "See `Units Humalog`.",
    "Units Insulin NPH": "See `Units Humalog`.",
    "Units Regular": "See `Units Humalog`.",
    "(morphine)": (
        "Names the substance, not a unit. Morphine-equivalent dosing has no "
        "UCUM expression."),
    "% of current infusion rate": (
        "A relative instruction rather than a unit: the value is a proportion "
        "of another rate that this string does not identify."),
    "soak": NOT_A_QUANTITY,
    "spacer": NOT_A_QUANTITY, "NEEDLE": NOT_A_QUANTITY, "DEV": NOT_A_QUANTITY,
    "PUMP": NOT_A_QUANTITY, "CADD": NOT_A_QUANTITY, "CART": NOT_A_QUANTITY,
    "LOT": NOT_A_QUANTITY, "CPT": NOT_A_QUANTITY, "WAF": NOT_A_QUANTITY,
    "STCK": NOT_A_QUANTITY, "SPG": NOT_A_QUANTITY, "PAD": NOT_A_QUANTITY,
    "powder": NOT_A_QUANTITY, "PWDR": NOT_A_QUANTITY, "OINT": NOT_A_QUANTITY,
    "GEL": NOT_A_QUANTITY, "CRE": NOT_A_QUANTITY, "CREA": NOT_A_QUANTITY,
    "SOLN": NOT_A_QUANTITY, "SUSP": NOT_A_QUANTITY, "SYRP": NOT_A_QUANTITY,
    "ELIX": NOT_A_QUANTITY, "LIQ": NOT_A_QUANTITY, "CONC": NOT_A_QUANTITY,
    "CON": NOT_A_QUANTITY, "INH": NOT_A_QUANTITY, "INJ": NOT_A_QUANTITY,
    "AERA": NOT_A_QUANTITY, "AERO": NOT_A_QUANTITY, "EFT": NOT_A_QUANTITY,
    "ERT": NOT_A_QUANTITY, "BULK": NOT_A_QUANTITY, "TC": NOT_A_QUANTITY,
    "chamber": NOT_A_QUANTITY, "UDCUP": NOT_A_QUANTITY,
    "Floor Stock Bag": NOT_A_QUANTITY, "PPN Bag": NOT_A_QUANTITY,
    "TPN Bag": NOT_A_QUANTITY, "DBTL": NOT_A_QUANTITY, "SBTL": NOT_A_QUANTITY,
    "PKG": NOT_A_QUANTITY,
}

# The stated rule for the residue. A source string carrying a digit, a
# backslash, a tilde or an asterisk, or wrapped in parentheses, records a
# QUANTITY or an ETL accident rather than a unit — `(1,000 mg)`, `mg\\ 0 mg`,
# `-109,000 unit`, `*IV~mcg~mL~`, `1000ML NS`, and the bare numbers `100`
# through `600`. Applied LAST, so every explicit answer above wins first: that
# is what keeps `mg/m2`, `cm3`, `mm^3`, `10*3/uL` and `mg/24hr` out of it.
_ARTEFACT = re.compile(r"[0-9\\~*]|^\(|\)$")

_ARTEFACT_REASON = (
    "Records a quantity or an ETL accident rather than a unit of measure — it "
    "carries a digit, a backslash, a tilde or an asterisk, or is wrapped in "
    "parentheses. Declined by a stated rule applied uniformly to every source "
    "string no explicit answer above covers, rather than row by row. Where a "
    "whole dose was written into the unit column (`(1,000 mg)`, "
    "`mEq / 250 mL NS`) the fix is in the ETL that filled it, not here: a "
    "ConceptMap can supply a unit, never split a value out of one.")


# --------------------------------------------------------------------------- #
# Gates.
# --------------------------------------------------------------------------- #

def _judge(svc, term):
    """(valid, canonical) — canonical is (term, magnitude) or None.

    canonicalize() is wrapped because ucumate 1.0.8 lets a raw Java exception
    through on some inputs this CodeSystem really contains: `/0mg` and `0/mg`
    both validate and then raise ArithmeticException: Division by zero. Caught
    rather than allowed to abort the run — a source string that cannot be
    canonicalised is a fact about that string, and these two are declined by
    the artefact rule anyway. Deliberately NOT caught around validate(), where
    an exception would mean something this generator does not understand.
    """
    from ucumate import ValidationSuccess, CanonicalizationSuccess
    if not isinstance(svc.validate(term), ValidationSuccess):
        return False, None
    try:
        canonical = svc.canonicalize(term)
    except Exception:  # noqa: BLE001 — a JVM exception, not a Python one
        return True, ("(uncanonicalisable)", "")
    if isinstance(canonical, CanonicalizationSuccess):
        return True, (canonical.canonical_term, canonical.magnitude)
    # Valid but not convertible — an arbitrary unit such as [IU]. Distinct from
    # None-because-invalid, and never equal to another term's canonical form,
    # so a dimension comparison against it always demands a comment.
    return True, ("(arbitrary)", "")


def _check_targets(rows, svc):
    """Every target must parse. The gate no other table in this repo has."""
    bad = [r for r in rows
           if r["ucum_code"] and not _judge(svc, r["ucum_code"])[0]]
    for row in bad:
        print(f"  {row['mimic_code']!r} -> {row['ucum_code']!r} is not valid "
              f"UCUM", file=sys.stderr)
    if bad:
        sys.exit(f"  {len(bad)} target(s) do not parse. A target that does not "
                 f"parse is not a UCUM code, and publishing it would put a "
                 f"string in Quantity.code that no consumer can compute with.")


def _check_dimension(rows):
    """The rule that catches the `K/uL` class.

    A source string that is ITSELF valid UCUM already denotes something. If the
    target denotes something else, this row does not merely restyle the unit —
    it corrects it, and the number's meaning changes. That is legitimate and it
    is most of why this table exists, but it must be SAID, because the code
    pair alone looks like a spelling fix.

    Fatal rather than a warning: the four rows this fires on carry 13M
    occurrences, and a future edit that adds a fifth would otherwise land
    silently.
    """
    missing = [r for r in rows
               if r["dimension_changed"] == "yes" and not r["comment"]]
    for row in missing:
        print(f"  {row['mimic_code']!r} -> {row['ucum_code']!r}: source is "
              f"valid UCUM ({row['source_canonical']}) and the target is "
              f"{row['target_canonical']} — the meaning changes",
              file=sys.stderr)
    if missing:
        sys.exit(f"  {len(missing)} row(s) change what the value means and say "
                 f"nothing about it. Add a COMMENTS entry keyed on "
                 f"(mimic_code, ucum_code).")


def _check_comments_used(rows):
    """A COMMENTS entry matching no row is fatal, never skipped.

    Same contract as COMMENT_OVERRIDES in the code-search generators: a note
    must not survive the target it was written about being changed.
    """
    used = {(r["mimic_code"], r["ucum_code"]) for r in rows}
    orphans = sorted(set(COMMENTS) - used)
    if orphans:
        sys.exit(f"  {len(orphans)} COMMENTS entr(y/ies) match no row: "
                 f"{orphans}. A comment cannot outlive its mapping — delete "
                 f"it, or fix the key.")


def _check_known(known):
    """Every code this generator answers for must still be in the IG."""
    declared = set(MAPPINGS) | set(DOSE_FORMS) | set(DECLINED)
    stale = sorted(declared - set(known))
    if stale:
        sys.exit(f"  {len(stale)} declared code(s) are not in the IG "
                 f"CodeSystem: {stale}. The upstream enumeration changed — "
                 f"delete them, or this table maps codes nothing can carry.")


# --------------------------------------------------------------------------- #

def build_rows(known, svc):
    """One row per source code this generator has an answer or a decline for."""
    rows = []
    for code, display in known.items():
        if code in MAPPINGS:
            tier, ucum, comment = "curated", MAPPINGS[code], ""
        elif code in DOSE_FORMS:
            tier, ucum, comment = "dose-form", DOSE_FORMS[code], ""
        elif code in DECLINED:
            tier, ucum, comment = "declined", "", DECLINED[code]
        elif _ARTEFACT.search(code):
            tier, ucum, comment = "declined-by-rule", "", _ARTEFACT_REASON
        else:
            continue  # no row: the build reports it as a backlog, not a gap

        source_valid, source_canonical = _judge(svc, code)
        target_canonical = _judge(svc, ucum)[1] if ucum else None
        changed = ""
        if ucum and source_valid:
            changed = "yes" if source_canonical != target_canonical else "no"

        rows.append({
            "mimic_code": code,
            "mimic_display": display,
            "ucum_code": ucum,
            # UCUM publishes no display for an expression, and inventing one
            # would be this repo asserting a name UCUM does not. The expression
            # is its own display, which is also what makes the pair auditable.
            "ucum_display": ucum,
            "comment": COMMENTS.get((code, ucum), comment),
            "tier": tier,
            "source_valid_ucum": "yes" if source_valid else "no",
            "source_canonical": _fmt(source_canonical),
            "target_canonical": _fmt(target_canonical),
            "dimension_changed": changed,
        })
    return rows


def _fmt(canonical):
    return f"{canonical[0]} x{canonical[1]}" if canonical else ""


def write_table(rows, path):
    ordered = sorted(rows, key=lambda r: r["mimic_code"])
    with open(path, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(ordered)
    return ordered


def main(argv=None):
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--table", type=Path, default=TABLE,
                    help="where to write (default: %(default)s)")
    ap.add_argument("--out-dir", type=Path, default=paths.OUTPUT,
                    help="where the generation log goes (default: %(default)s)")
    ap.add_argument("--dry-run", action="store_true",
                    help="run every gate and report, but write nothing")
    args = ap.parse_args(argv if argv is not None else sys.argv[1:])

    known = dict(enumeration(get(STREAM)))
    print(f"  {len(known):,} code(s) in the IG CodeSystem", file=sys.stderr)
    _check_known(known)

    from ucumate import UCUMService
    svc = UCUMService()

    rows = build_rows(known, svc)
    _check_targets(rows, svc)
    _check_dimension(rows)
    _check_comments_used(rows)

    tiers = Counter(r["tier"] for r in rows)
    mapped = sum(1 for r in rows if r["ucum_code"])
    print(f"  {len(rows):,} row(s): {mapped:,} mapped, "
          f"{len(rows) - mapped:,} declined", file=sys.stderr)
    for tier, n in sorted(tiers.items()):
        print(f"    {tier:<18} {n:>4}", file=sys.stderr)
    print(f"  {len(known) - len(rows):,} code(s) get NO ROW — the build "
          f"reports them as no-row-in-curated-table", file=sys.stderr)
    print(f"  {sum(1 for r in rows if r['dimension_changed'] == 'yes')} row(s) "
          f"change the source's meaning, each with a comment", file=sys.stderr)

    if args.dry_run:
        print("  --dry-run: nothing written", file=sys.stderr)
        return 0

    ordered = write_table(rows, args.table)
    print(f"  wrote {args.table.name} ({len(ordered):,} rows)", file=sys.stderr)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    log = {
        "stream": STREAM,
        "table": args.table.name,
        "method": "curated table, gated by offline UCUM parsing (ucumate)",
        # No threshold, no constraint and no service: the three settings every
        # other generation log records do not exist here. Saying so explicitly
        # keeps lib/stats.py's absent codesearch block from reading as a gap.
        "settings": {
            "network": False,
            "confidence_threshold": None,
            "search_constraint": None,
            "annotations_preserved": True,
        },
        "enumerated": len(known),
        "rows": len(rows),
        "mapped": mapped,
        "declined": len(rows) - mapped,
        "no_row": len(known) - len(rows),
        "tiers": dict(sorted(tiers.items())),
        "meaning_changed": sorted(
            r["mimic_code"] for r in rows if r["dimension_changed"] == "yes"),
    }
    log_path = args.out_dir / LOG_NAME
    log_path.write_text(json.dumps(log, indent=1) + "\n")
    print(f"  wrote {log_path.name}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
