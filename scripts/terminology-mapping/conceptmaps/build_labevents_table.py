#!/usr/bin/env python3
"""Generate conceptmaps/labevents-loinc.csv — the 1,622 lab analytes -> LOINC.

The sixth generated table and the largest population in this map by some
distance — 1,622 codes against the 646 of the microbiology organisms. It follows
build_outputevents_table.py in shape (one constraint, one pass, a dictionary-fed
pre-filter that declines items without searching them) and borrows the query
collapse and fan-out of build_micro_test_table.py. What is new here is that the
SEARCH TEXT IS NOT THE LABEL: it is the label plus the specimen, and that is the
whole argument of this script.

WHAT THE SOURCE CODES MEAN. mimic-d-labitems holds 1,622 analytes from MIMIC's
`d_labitems` dictionary, bound to Observation.code on MimicObservationLabevents.
Each is one row of a hospital laboratory results table.

THE SPECIMEN IS NOT IN THE LABEL, and only 807 of the 1,622 analytes are blood.
The rest are Urine 194, Other Body Fluid 192, CSF 99, Joint Fluid 72, Pleural 69,
Ascites 68, Bone Marrow 63, Stool 43 and a handful more. MIMIC keeps the specimen
in a separate `fluid` column, and `fluid` IS the LOINC System axis, so a search
on the bare label asks LOINC a question that has no specimen in it and gets the
default one back. Probed over 20 items spanning every fluid, specimen-correct
System on the 12 non-blood rows:

    bare label                            7 / 12
    label + fluid   (TEMPLATE below)     11 / 12
    label + fluid + category             12 / 12   <- rejected, see CATEGORY

Injecting the fluid fixes 7 of the 20 rows outright and breaks none:

    50833 Potassium        / Other Body Fluid   6298-4 Blood      -> 2821-7  Body fluid
    51910 (Albumin)        / Pleural            1751-7 Ser/Plas   -> 1748-3  Pleural
    51516 WBC              / Urine             26464-8 Blood @.61 -> 30405-5 Urine
    51498 Specific Gravity / Urine             33513-3 Specimen   -> 2965-2  Urine
    50983 Sodium           / Blood              2951-2 Ser/Plas   -> 2947-0  Blood
    50912 Creatinine       / Blood             39982-4 Urine      -> 38483-4 Blood
    50931 Glucose          / Blood             40858-3 Capillary  -> 2339-0  Blood

Note the last three: the fluid repairs BLOOD rows too, because `Sodium` alone
answers with serum/plasma and MIMIC recorded whole blood. And the four labels
that already name their own specimen (`Chloride, CSF`, `Sodium, Body Fluid`,
`Albumin, Pleural`, `Chloride, Ascites`) return the IDENTICAL code under all
three templates — so the injection buys the hard cases at no cost to the easy
ones, which is what makes it a rule rather than a trade.

WHERE MIMIC NAMES WHOLE BLOOD ITSELF, the `fluid` column is not the last word.
`fluid` is a specimen FAMILY, not a LOINC System: it says "this came from blood"
and cannot say serum, plasma or whole blood. For most analytes that is all MIMIC
knows and injecting `Blood` is the honest sentence. But for six analytes MIMIC
draws the distinction in the LABEL — `Potassium, Whole Blood` (50822) sits beside
a plain `Potassium` (50971), both filed under `fluid = Blood` — and injecting the
same word for both asked one question for two measurements. Seven of the eight
such pairs came back on the IDENTICAL LOINC code, the plain sibling carrying
3.15M, 3.12M, 3.08M and 2.75M observations onto a whole-blood target:

    50822 Potassium, Whole Blood  / Blood Gas   6298-4 |… in Blood|
    50971 Potassium               / Chemistry   6298-4 |… in Blood|   <- same code
    50824 Sodium, Whole Blood     / Blood Gas   2947-0 |… in Blood|
    50983 Sodium                  / Chemistry   2947-0 |… in Blood|   <- same code

MIMIC distinguishes them and the map did not, which is a contradiction internal
to the source rather than a judgement about LOINC. So where — and ONLY where — a
`<analyte>, Whole Blood` item exists, its plain sibling in the same fluid and in
category `Chemistry` is asked as `Serum or Plasma` instead of `Blood`. That is 10
items across 5 analytes, 15.4M observations. See SPECIMEN_OVERRIDE.

Scoped this tightly on purpose, and the scoping is the argument:

  * It fires only where MIMIC ITSELF names the contrast. An analyte with no
    `, Whole Blood` sibling — `Urea Nitrogen`, `Magnesium`, `Bilirubin, Total` —
    keeps `Blood`, because nothing in the source says otherwise and inventing the
    serum axis from a lab-section name is exactly the mistake below.
  * `category` is consulted only to pick WHICH member of a named contrast is the
    whole-blood one, never to decide the axis on its own. It cannot bear more:
    `51704 Platelet Count` and `51638 Hematocrit` are filed `Chemistry` and are
    whole-blood haematology, so a blanket "Chemistry means serum" rule would move
    them onto a serum target and break rows this one leaves alone. Blood Gas
    siblings keep `Blood` — `50809 Glucose` (Blood Gas, 211K) stays put while
    `50931 Glucose` (Chemistry, 2.75M) moves.
  * The sentence keeps its SHAPE. Only the specimen word changes; no new field
    joins the template, so the failure CATEGORY IS EXCLUDED documents below
    cannot come back through this door. The two rows it names, `52025 Delete` and
    `52043 Voided Specimen`, are Blood Gas and Other Body Fluid: neither is in a
    named contrast, and both are asked the byte-identical sentence they are today.

CATEGORY IS EXCLUDED, and this is the sharper finding. MIMIC also records
`category` (Chemistry 777 / Hematology 781 / Blood Gas 64). Adding it reaches
12/12 on the System axis and it still must not be used, because it MANUFACTURES
ANSWERS FOR JUNK:

    52025 Delete           / Blood / Blood Gas         -> 24338-6 |Gas panel - Blood| @0.85
    52043 Voided Specimen  / OBF   / Blood Gas         -> 24338-6 |Gas panel - Blood| @0.80

Both decline cleanly on the bare label AND with the fluid; only the category
sentence answers them. In-constraint, above threshold, past the gate, for rows
that mean "this record was deleted" — 52 items across the two families. An
isolating probe with the category word removed from the same sentence returns NO
MATCH for both, so it is `category` and not the phrasing that does it. That is
the "template rescues junk" failure build_outputevents_table.py documents, and it
is why the query key below is (label, specimen) and not (label, specimen,
category) — and why SPECIMEN_OVERRIDE above reads `category` to choose a word
inside the existing sentence rather than adding it to the sentence as a field.

The one thing category would have bought is `51265 Platelet Count`, where it
moves the answer off `777-3 |… by Automated count|` onto the methodless
`26515-7`. One removed method assertion does not pay for 52 fabricated ones.

WHY THE CONSTRAINT AND NOT THE CONFIDENCE, for the fourth LOINC stream running.
Against `http://loinc.org/vs` instead, with the same template, the most ordinary
analytes in the warehouse come back as LOINC PARTS at the confidences a real
answer scores:

    Sodium, Blood      LP32156-9 |Sodium|                          0.90
    Hemoglobin         LP32067-8 |Hemoglobin|                      1.00
    pH                 LP14752-7 |pH|                              1.00
    Lactate            LP15686-6 |Lactate|                         1.00
    Specific Gravity   LP15865-6 |Specific gravity|                1.00
    Delete             LA9047-7  |Deleted|  (an ANSWER LIST code!) 0.85

None is a legal Observation.code, four of the six score at or above 0.9, and the
junk label scores as high as `Sodium, Blood`. Constrained, the same six give
`2947-0`, `718-7`, `17433-4`, `32693-4`, `33513-3` and a clean decline.
$validate-code confirms LP32156-9 and 8480-6 sit outside the constraint while
2951-2, 2947-0, 718-7, 2744-1, 2160-0, 777-3, 6690-2 and 2823-3 sit inside, so
the constraint PREVENTS these rather than rejecting them after the fact. This is
the `Foley Catheter` lesson of build_d_items_table.py a fourth time.

STATUS = ACTIVE is not decoration here. It removes 6,852 codes from CLASSTYPE=1
(66,861 -> 60,009), reconciling exactly with DEPRECATED 3,159 + DISCOURAGED 1,067
+ TRIAL 2,626. The example that matters: `42570-2 |Sodium [Mass or Moles/volume]
in Serum or Plasma|` is DISCOURAGED, is in CLASSTYPE=1, and is a highly plausible
top match for MIMIC's several hundred `Sodium` rows. Only the status filter
excludes it.

WHY NOT ALSO CLASS = PULM, which was proposed and REJECTED. MIMIC's 64-item
`Blood Gas` category carries a respiratory tail — `Alveolar-arterial Gradient`,
`Tidal Volume`, `PEEP`, `Ventilation Rate`, `Ventilator`, `Intubated`,
`Assist/Control`, `Required O2` — whose LOINC counterparts are CLASSTYPE=2,
CLASS=PULM and therefore outside this constraint. `50801 Alveolar-arterial
Gradient` declines here and answers `19991-9` at 0.95 unconstrained, so this is a
real and knowable loss. Widening to
`(http://loinc.org)(CLASSTYPE=1,STATUS=ACTIVE);(http://loinc.org)(CLASS=PULM,STATUS=ACTIVE)`
adds only 833 codes and was verified not to disturb membership of anything.

It was rejected anyway, because membership is not answer stability. Run over a
16-row control set of ordinary analytes, the union CHANGED one of them:

    50804 Calculated Total CO2   narrow  20565-8 |CO2 total in Blood|
                                 union   34728-6 |CO2 total in Blood by calculation|

Deterministic, 5 runs each way. BOTH codes are CLASSTYPE=1/CHEM — both were
already inside the narrow constraint — so 833 added PULM codes reordered the
shortlist of a chemistry analyte whose correct answer never involved a PULM code
at all. That is build_micro_test_table.py's finding in a different vocabulary:
the perturbation is not confined to the subtree you add, so the blast radius of
the union is all 1,622 analytes and only 16 were sampled.

What the union buys, against that: ONE defensible mapping out of the 11
respiratory items (`50801` -> `19991-9` @0.85). The other three that start
answering are all sub-threshold and all wrong in the specific ways this pipeline
watches for — `76526-3 |Ventilation rate BY CARBON DIOXIDE MEASUREMENT|` invents
a capnography method, `20109-5 |Tidal volume … on ventilator|` asserts a circuit
context MIMIC never records, and `Assist/Control` gets
`20124-4 |Ventilation mode Ventilator|`, which is a CODE for what is really a
VALUE of ventilation mode. So the respiratory tail is left unmapped with the
proposal recorded, and `50801` is NOT rescued by hand: COMMENT_OVERRIDES cannot
pin a target code precisely so that it can never become a route around the
constraint and the threshold.

TWO PRE-SEARCH DECLINES, 7 rows, both read off the dictionary rather than off any
reading of an item — the build_outputevents_table.py pattern, where an item the
dictionary disqualifies is declined WITHOUT being searched, because a search it
should not have been sent would be answered confidently anyway.

  no-label (4)  `51771`, `51905`, `51955`, `52374` have a blank or whitespace
                `label`, which is why the IG's display for them fell back to the
                itemid. Sending the string "52374" to code-search is not a
                search. These are 4 of the 5 IG-vs-dictionary display
                differences, and the fifth is `52170` (' Rbc' vs 'Rbc'), a strip.

  specimen-conflict (3)  `51081 Creatinine, Serum`, `51964 Amylase, Serum` and
                `51977 Creatinine, Blood` all carry `fluid = Urine`. The label
                names one specimen and the dictionary column names another, so no
                template can state the specimen truthfully — and the failure is
                not theoretical: asked with the fluid injected, `51081` returns
                `33558-8 |Creatinine renal clearance in Urine and Serum or
                Plasma|` at 0.85, a DERIVED CLEARANCE that MIMIC never computed,
                in-constraint and above threshold. The template fuses the
                contradiction instead of declining it. Detected by MIMIC's own
                `<analyte>, <specimen>` suffix convention, which 191 labels
                follow: 188 agree with the `fluid` column and these 3 contradict
                it. See SPECIMEN_SUFFIX.

Deliberately NOT pre-filtered: the 52 `Delete` / `Voided Specimen` rows and the
10 flow-cytometer channel labels (`FL1-D`, `SSC-S`, `Dna`, whose `fluid` is the
non-specimen 'Q' or 'I'). They are searched like everything else and declined by
the constraint, which they demonstrably are. A source-label reject list naming
them was considered and dropped for build_micro_test_table.py's reason: the
constraint already handles them, and a list of labels seen to come back wrong is
curation against known rows, which is what COMMENT_OVERRIDES is forbidden to do.

ONE QUERY PER (LABEL, SPECIMEN), 1,615 searchable items collapsing to ~1,484
searches, the answer fanned back across the itemids sharing a key. A correctness
rule and not an optimisation, the same one build_micro_test_table.py makes for
its three shared labels: nothing distinguishes `50811` and `51222` (both
`Hemoglobin` in `Blood`) but the itemid and the category, so a map where they
disagree is wrong however plausible each row looks alone. The fan-out makes
divergence unrepresentable and main() asserts it anyway.

The key is the SPECIMEN the sentence states, not the raw `fluid` column, which
matters for exactly the rows SPECIMEN_OVERRIDE moves: `Glucose` in `Blood` used
to be one key spanning `50809` (Blood Gas) and `50931` (Chemistry), so one answer
had to serve both. It is now two keys, which is the point — the collapse must not
outlive the reason the two rows were ever the same question.

The LABEL ALONE would be the wrong key, not merely a coarser one: 1,622 items
carry 1,170 distinct labels, and `pH` spans four fluids while `Voided Specimen`
spans nine. Keying on the label would force one target across specimens that the
LOINC System axis exists to distinguish — the exact error the template is there
to prevent, reintroduced through the grouping.

THE GATE is build_outputevents_table.py's: membership asserted with
$validate-code against the constraint rather than assumed from the service having
been asked nicely (which subsumes STATUS = ACTIVE, since the constraint carries
it), and the target display replaced with the server's own LONG_COMMON_NAME so
verify-curated's display check passes by construction. LOINC needs no `active` or
`international core module` check: both SNOMED analogues are expressible on the
LOINC side, and LOINC has no national extensions.

There is deliberately NO reject list of the kind build_outputevents_table.py's
TOTAL_CODES is. One was looked for and cannot be written, because the one known
defect is not a property of the target:

    KNOWN DEFECT: `50823 Required O2` -> `11556-8 |pO2 in Blood|` at 0.85.
    Required O2 is an inspired-oxygen requirement (an FiO2 slot on the blood-gas
    worksheet), not an arterial partial pressure, so this makes the data say
    something false rather than merely vague. `11556-8` is a perfectly good
    target that is simply wrong for THIS source, so no property of the target
    code can reject it and no constraint change catches it — it is the
    `227719 AVA` case of build_d_items_table.py. Left in place and flagged here
    because this generator does not hand-write targets. A consumer should drop
    it.

SINGLE-TARGET LOINC, with the SNOMED second opinion probed and dropped. A pass
against `<<363787002 |Observable entity|` over the 8 items the LOINC constraint
declined produced ONE genuine rescue (`Tidal Volume` -> `13621006`, where all 31
LOINC tidal-volume codes carry an unstated inspired/expired/ventilator axis and
the SNOMED concept asserts nothing MIMIC does not record). On the actually
LOINC-hard population — stains, crystals, electrophoresis fractions, flow markers
and truncated labels — it returned NO MATCH on every one, and `Sodium` and
`Hemoglobin` return nothing usable at MIMIC's granularity. It also confirmed the
A-a gradient is a constraint artifact rather than a LOINC gap. One row does not
justify the per-row `target_system` columns and the lib/assemble changes a
mixed-target table needs. This repeats build_outputevents_table.py's finding.

EQUIVALENCE is not this script's concern. Every mapping a table supplies is
`relatedto`, set by lib/assemble.py when it builds the group.

Why it is NOT part of `make mappings`: same as the five generators before it. It
needs the network and an LLM-backed service, and it WRITES a build input.
Determinism lives in the split — this runs by hand, its output is committed, and
`make mappings` reads the committed CSV and never a server.

    make labevents-table ARGS=--insecure

Usage:
  uv run scripts/terminology-mapping/conceptmaps/build_labevents_table.py
  uv run .../build_labevents_table.py --only 50983,51516 --insecure
"""

import argparse
import concurrent.futures
import csv
import gzip
# NOT `import http.client`: the fhirclient import below binds the name `http` to a
# function, so `HTTPException` in find_code's except clause raises
# AttributeError instead of retrying — which silently defeats the retry loop the
# docstring relies on, and only on the transport failures it exists to absorb.
from http.client import HTTPException
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.cli import add_common_args, DEFAULT_CODE_SEARCH  # noqa: E402
from common.fhirclient import configure_tls, http  # noqa: E402
# The module, not `from ... import SSL_CONTEXT`: configure_tls() REBINDS that global,
# so a name bound at import time would still be the pre-configuration context and
# --ca-bundle would be silently ignored.
from common import fhirclient  # noqa: E402
from conceptmaps.lib.canonical import LOINC  # noqa: E402
from conceptmaps.lib.curated import curated_columns  # noqa: E402
from conceptmaps.lib.igsource import source_concepts  # noqa: E402

# --------------------------------------------------------------------------- #
# The stated rules
# --------------------------------------------------------------------------- #

# LOINC's Laboratory class type, active codes only. 60,009 of LOINC's 247,255.
# CLASSTYPE is the axis that separates laboratory observations from clinical
# ones and from the Parts, which is what makes it the counterpart of CLASS=MICRO
# and CLASS/"IO_OUT.*" in the two LOINC streams before this one. See WHY THE
# CONSTRAINT AND NOT THE CONFIDENCE in the module docstring for what it prevents,
# and WHY NOT ALSO CLASS = PULM for the widening that was probed and rejected.
CONSTRAINT_VCL = '(http://loinc.org)(CLASSTYPE=1,STATUS=ACTIVE)'

# One sentence, identical for every item that is asked about. TWO fields, not
# one: MIMIC keeps the specimen in its own column and `fluid` is the LOINC System
# axis, so the label alone asks a question with no specimen in it. Chosen over a
# bare label and over a label+fluid+category variant by running all three over 20
# items spanning every fluid — see THE SPECIMEN IS NOT IN THE LABEL and CATEGORY
# IS EXCLUDED, the latter being why `category` is absent from a sentence that
# otherwise had a use for it.
TEMPLATE = "Hospital laboratory analyte measured in {specimen}: {label}"

# Below this, code-search's answer is discarded and the item is left unmapped.
# Matches the five generators before it. The distribution is printed at the end
# of every run so it can be moved with evidence rather than by taste.
CONFIDENCE_THRESHOLD = 0.8

# MIMIC's convention for naming a specimen in the label itself: a trailing
# `, <specimen>`. 191 of the 1,622 labels use it. Where the suffix and the
# `fluid` column agree (188 rows) nothing happens — the probes confirmed such
# labels return the identical code with or without injection. Where they
# CONTRADICT (3 rows) the item is declined unasked, because no template can state
# a specimen the source disagrees with itself about, and the one measured attempt
# fused them into a derived clearance MIMIC never computed. See the
# specimen-conflict paragraph of the module docstring.
#
# Keyed by the suffix as MIMIC writes it, valued by the `fluid` column it
# implies. Applied uniformly to every label, so it is a stated rule and not a
# per-item judgement.
SPECIMEN_SUFFIX = {
    "serum": "Blood",
    "plasma": "Blood",
    "whole blood": "Blood",
    "blood": "Blood",
    "urine": "Urine",
    "csf": "Cerebrospinal Fluid",
    "cerebrospinal fluid": "Cerebrospinal Fluid",
    "ascites": "Ascites",
    "pleural": "Pleural",
    "joint fluid": "Joint Fluid",
    "synovial": "Joint Fluid",
    "body fluid": "Other Body Fluid",
    "stool": "Stool",
    "bone marrow": "Bone Marrow",
}
SPECIMEN_SUFFIX_RE = re.compile(r",\s*([A-Za-z ]+)$")

# The one place `fluid` is overridden, and it is derived from the dictionary
# rather than listed here — a hand-written list of itemids would be curation
# against known rows, which COMMENT_OVERRIDES is forbidden to do and this has no
# more licence for. See WHERE MIMIC NAMES WHOLE BLOOD ITSELF.
#
# The trigger is MIMIC's own `<analyte>, Whole Blood` labels: where one exists,
# its plain siblings in the same fluid are, by MIMIC's own naming, not whole
# blood. `category` then says which sibling is which — Blood Gas keeps the fluid
# word, Chemistry is asked as serum or plasma. Both halves are needed: the label
# convention establishes THAT a contrast exists, the category says WHICH SIDE a
# row sits on, and neither is trusted to do the other's job.
WHOLE_BLOOD_SUFFIX_RE = re.compile(r",\s*whole blood\s*$", re.I)
SERUM_CATEGORY = "Chemistry"
SERUM_SPECIMEN = "Serum or Plasma"


def specimen_override(labitems):
    """{itemid: specimen word} for every item the fluid column under-states.

    Empty for all but the analytes MIMIC labels a whole-blood variant of. Keyed
    on (base label, fluid) so the contrast is scoped to one analyte in one
    specimen family and cannot leak across fluids.
    """
    contrasted = {(WHOLE_BLOOD_SUFFIX_RE.sub("", item["label"].strip())
                   .strip().casefold(), item["fluid"])
                  for item in labitems.values()
                  if WHOLE_BLOOD_SUFFIX_RE.search(item["label"].strip())}
    return {code: SERUM_SPECIMEN
            for code, item in labitems.items()
            if item["category"] == SERUM_CATEGORY
            and not WHOLE_BLOOD_SUFFIX_RE.search(item["label"].strip())
            and (item["label"].strip().casefold(), item["fluid"]) in contrasted}

# --------------------------------------------------------------------------- #
# Paths and provenance
# --------------------------------------------------------------------------- #

TERM = Path(__file__).resolve().parents[1]
OUT_CSV = Path(__file__).resolve().parent / "labevents-loinc.csv"
LOG_JSON = TERM / "output" / "labevents-generation-log.json"

# MIMIC-IV demo 2.2, the openly downloadable release that ships the hospital
# dictionary whole (1,622 rows, not a subset). Read for the specimen and the
# pre-filter only: the build never reads it at all, and the committed CSV is what
# keeps `make mappings` offline.
D_LABITEMS_GZ = (TERM / "sources" / "mimic-iv-demo" / "2.2" / "hosp"
                 / "d_labitems.csv.gz")

# This table targets LOINC, so it says so in its own header rather than
# borrowing the SNOMED naming. lib.curated.load_table normalises both to
# `target_code` / `target_display` for the build.
TARGET_COLUMNS = ("loinc_code", "loinc_display")
CURATED = curated_columns(TARGET_COLUMNS)

# What the service proposed on every row it was asked about, including the rows
# where the proposal was then rejected by the threshold or the constraint — so
# that "this item is unmapped" is auditable in the committed diff. The
# pre-filtered rows carry these blank, which is what distinguishes "asked and
# declined" from "never asked, and the comment says why".
#
# `codesearch_query` holds the FULL TEMPLATED SENTENCE here, where the four
# single-field streams record the bare string they collapsed on. The query key of
# this stream is a PAIR, so the label alone would not identify which query a row
# belongs to — `pH` in Blood and `pH` in Urine are two searches and would look
# like one in the CSV.
PROVENANCE_COLUMNS = ["codesearch_query", "codesearch_target",
                      "codesearch_display", "codesearch_confidence",
                      "codesearch_status", "codesearch_reasoning"]

# Recorded per row in the log only. `path` (cached / fast / agentic) says how
# this run fetched an answer, not anything about the answer, so it would show up
# as a wall of changed rows in a diff where no mapping moved.
LOG_ONLY_COLUMNS = ["path"]

# --------------------------------------------------------------------------- #
# Sources
# --------------------------------------------------------------------------- #


def ig_codes():
    """(code, display) for the 1,622 analytes, read from the IG's own ValueSet.

    Routed through the observation builder's own SOURCES declaration for the
    reason the five generators before it give: lib.curated.load_table rejects a
    row whose display differs from the IG's by so much as a character, so the
    generator and the build must read displays through the same function or the
    table this writes can fail the build that reads it.
    """
    from conceptmaps.build_observation_cm_vs import SOURCES

    source = next(s for s in SOURCES if s.get("table") == OUT_CSV)
    return dict(source_concepts(source))


def dictionary(expected):
    """itemid -> d_labitems row, checked against the IG enumeration.

    A missing itemid is fatal, and so is a label difference — with ONE stated
    exception. build_outputevents_table.py makes every difference fatal because
    its dictionary and its IG agree exactly; here they differ on 5 of 1,622 rows,
    and all 5 are the same phenomenon rather than a relabelling:

        52170  IG 'Rbc'    dictionary ' Rbc'   -> whitespace, a strip
        51771  IG '51771'  dictionary ''       -> blank label, so the IG's
        51905  IG '51905'  dictionary ' '         display fell back to the
        51955  IG '51955'  dictionary ''          itemid
        52374  IG '52374'  dictionary ''

    So the exception is exactly: the dictionary label strips to the IG display,
    or it is blank and the IG display is the itemid. Anything else stays fatal,
    because an item relabelled upstream is precisely the one whose mapping a
    human should read again — the same check, for the same reason, that
    load_table makes on the committed table.
    """
    if not D_LABITEMS_GZ.is_file():
        sys.exit(f"  {D_LABITEMS_GZ} not found. It carries the `fluid` column "
                 f"the template injects — without it every one of the 815 "
                 f"non-blood analytes would be searched with no specimen and "
                 f"resolve against serum or plasma by default. Download "
                 f"MIMIC-IV demo 2.2 (no credentialing needed):\n"
                 f"    https://physionet.org/files/mimic-iv-demo/2.2/hosp/d_labitems.csv.gz")

    rows = {}
    with gzip.open(D_LABITEMS_GZ, "rt", newline="") as fh:
        for row in csv.DictReader(fh):
            if row["itemid"] in expected:
                rows[row["itemid"]] = row

    missing = sorted(set(expected) - set(rows))
    if missing:
        sys.exit(f"  {len(missing)} IG code(s) are not in "
                 f"{D_LABITEMS_GZ.name}: {missing[:8]}. The IG and the "
                 f"dictionary are different MIMIC releases — re-check which "
                 f"before generating a table from them.")

    drifted = []
    for code in sorted(expected):
        ig_label, dict_label = expected[code], rows[code]["label"]
        if dict_label == ig_label:
            continue
        if dict_label.strip() == ig_label:
            continue                       # whitespace only — 52170
        if not dict_label.strip() and ig_label == code:
            continue                       # blank label, IG fell back to itemid
        drifted.append((code, ig_label, dict_label))
    if drifted:
        for code, ig_label, dict_label in drifted:
            print(f"    {code} IG {ig_label!r} vs dictionary {dict_label!r}",
                  file=sys.stderr)
        sys.exit(f"  {len(drifted)} label(s) differ between the IG and "
                 f"{D_LABITEMS_GZ.name} beyond the blank-and-whitespace cases "
                 f"this script states. An item that was relabelled upstream is "
                 f"one whose mapping should be re-read, not one to generate "
                 f"around.")
    return rows


def searchable(item):
    """(True, '') if this item should be asked about, else (False, reason).

    Two declines, both read off the dictionary and applied to every item
    identically. See TWO PRE-SEARCH DECLINES in the module docstring.
    """
    label, fluid = item["label"].strip(), item["fluid"]
    if not label:
        return False, "the dictionary records no label for it"

    match = SPECIMEN_SUFFIX_RE.search(label)
    suffix = match.group(1).strip().lower() if match else None
    implied = SPECIMEN_SUFFIX.get(suffix)
    if implied and implied != fluid:
        return False, (f"its label names {suffix!r} while the dictionary files "
                       f"it under fluid {fluid!r}")
    return True, ""


def constraint_url():
    """CONSTRAINT_VCL as a resolvable implicit-ValueSet canonical."""
    return ("http://fhir.org/VCL?v1="
            + urllib.parse.quote(CONSTRAINT_VCL, safe=""))


def service_info(service):
    """code-search's self-reported configuration, or None if it won't say."""
    try:
        with urllib.request.urlopen(
                f"{service.rstrip('/')}/api/v1/info", timeout=30,
                context=fhirclient.SSL_CONTEXT) as response:
            return json.load(response)
    except Exception:                                 # noqa: BLE001
        return None


def find_code(service, text, timeout, attempts=4):
    """code-search's best match for `text`, constrained to CONSTRAINT_VCL.

    Retries transport failures, for the reason the generators before it give: a
    dropped connection is not an answer, and a run that quietly mixes 'no match'
    with 'the service was not running' produces a table that understates coverage
    and reads exactly like a real result. Exhausted retries raise, and main()
    refuses to write the CSV.
    """
    body = json.dumps({
        "text": text,
        "url": constraint_url(),
        "system": LOINC,
        "max_candidates": 1,
        "effort": "balanced",
    }).encode()
    last = None
    for attempt in range(attempts):
        request = urllib.request.Request(
            f"{service.rstrip('/')}/api/v1/find-code", data=body,
            headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(
                    request, timeout=timeout,
                    context=fhirclient.SSL_CONTEXT) as response:
                return json.load(response)
        except (urllib.error.URLError, ConnectionError, TimeoutError,
                HTTPException) as exc:
            last = exc
            if attempt < attempts - 1:
                time.sleep(2 ** attempt)
    raise RuntimeError(f"{attempts} attempt(s) failed: {last}")


# --------------------------------------------------------------------------- #
# The validation gate
# --------------------------------------------------------------------------- #


def in_constraint(fhir_base, code):
    """True if `code` is a member of CONSTRAINT_VCL, per the server.

    Asserted rather than assumed. code-search was asked to honour the constraint
    and demonstrably does — the LOINC Parts that dominate the unconstrained
    answers never appear here — but 'the service was asked nicely' is not a
    property a committed table should rest on. It subsumes STATUS = ACTIVE,
    because the constraint carries it.
    """
    query = urllib.parse.urlencode({
        "url": constraint_url(), "system": LOINC, "code": code})
    status, body = http(
        "GET", f"{fhir_base.rstrip('/')}/ValueSet/$validate-code?{query}")
    if status != 200 or not body:
        return False
    return any(p["name"] == "result" and p.get("valueBoolean")
               for p in body.get("parameter", []))


def preferred_display(fhir_base, code):
    """The concept's LONG_COMMON_NAME on this server, or None if absent.

    The server's own display, not whatever string code-search carried next to
    the code, which is what keeps a display in the committed table a real
    designation of its concept by construction.
    """
    query = urllib.parse.urlencode({"system": LOINC, "code": code})
    status, body = http(
        "GET", f"{fhir_base.rstrip('/')}/CodeSystem/$lookup?{query}")
    if status != 200 or not body or body.get("resourceType") != "Parameters":
        return None
    for parameter in body.get("parameter", []):
        if parameter["name"] == "display":
            return parameter["valueString"]
    return None


def gate(fhir_base, code):
    """('ok', display) if `code` is usable, else (reason, None).

    Used as a filter rather than an assertion: a target that fails here is
    treated exactly as an absent one and the item is left unmapped with the
    rejected proposal recorded.

    No TOTAL_CODES-style reject list, deliberately — see KNOWN DEFECT in the
    module docstring for the one failure that cannot be written as a property of
    the target and is therefore flagged rather than filtered.
    """
    if not in_constraint(fhir_base, code):
        return "out-of-constraint", None
    display = preferred_display(fhir_base, code)
    if not display:
        return "absent", None
    return "ok", display


# --------------------------------------------------------------------------- #
# Reviewed comments
# --------------------------------------------------------------------------- #


# Prose notes on individual mappings, keyed on (mimic_code, loinc_code).
#
# NOT equivalence — every mapping this table supplies is `relatedto`, fixed by
# lib/assemble.py. Keyed on the PAIR, and fatal when an entry matches no row, for
# the reasons build_d_items_table.py sets out: the note was written about one
# specific target concept, and a silent miss means a human's reading of a row
# quietly evaporates.
#
# Comments only — this mechanism deliberately cannot pin a loinc_code. The moment
# it can, it becomes a way to hand-write mappings that bypass
# CONFIDENCE_THRESHOLD and the gate, and the table stops being 'what the service
# returned, gated'. That restriction is load-bearing for THIS stream in
# particular: `50801 Alveolar-arterial Gradient` has a known correct target
# (`19991-9`) that this constraint cannot reach, and hand-writing it here is
# exactly the shortcut the mechanism exists to forbid.
#
# Empty because no row of this table has been reviewed yet: the first run of this
# script is the dry run whose output decides which rows need a note. Two
# candidates are already known from the probes — `50823 Required O2` on
# `11556-8 |pO2 in Blood|`, the KNOWN DEFECT above, and `51265 Platelet Count` on
# `777-3 |… by Automated count|`, which asserts an automated method where MIMIC's
# label names none.
COMMENT_OVERRIDES = {}


def apply_comments(rows):
    """Attach the reviewed comments to their rows. Fatal on drift."""
    by_pair = {(r["mimic_code"], r["loinc_code"]): r
               for r in rows if r["loinc_code"]}
    for (code, target), comment in sorted(COMMENT_OVERRIDES.items()):
        row = by_pair.get((code, target))
        if row is None:
            current = next((r for r in rows if r["mimic_code"] == code), None)
            now = ("is no longer in the IG" if current is None else
                   f"now targets {current['loinc_code'] or '(unmapped)'}")
            sys.exit(f"  comment {code} -> {target} does not apply: the item "
                     f"{now}. The note was written about {target}, so it "
                     f"cannot be carried over. Re-read the row, then update or "
                     f"delete the entry.")
        if not comment:
            sys.exit(f"  comment {code} -> {target} is empty — delete the "
                     f"entry rather than leaving it blank.")
        row["comment"] = comment


# --------------------------------------------------------------------------- #
# Row construction
# --------------------------------------------------------------------------- #


def blank_row(code, label):
    row = {c: "" for c in CURATED + PROVENANCE_COLUMNS + LOG_ONLY_COLUMNS}
    row["mimic_code"] = code
    row["mimic_display"] = label
    return row


def decline_unasked(row, why_not):
    """A row the pre-filter declined. The codesearch_* columns stay blank, which
    is what distinguishes "asked and declined" from "never asked"."""
    row["codesearch_status"] = "not-searchable"
    row["comment"] = (
        f"Not sent to code-search: {why_not}, so no sentence could state what "
        f"was measured and in what. An answer here would be the service coding "
        f"a string MIMIC does not stand behind.")
    return row


def search_query(label, specimen, fhir_base, service, timeout):
    """One code-search call for one (label, specimen), its answer gated.

    Returns the fields to copy onto every itemid sharing that key, so that
    analytes differing only by itemid cannot end up on different targets. The
    proposal is recorded whether or not it survives — a query rejected at
    CONFIDENCE_THRESHOLD or at the constraint keeps its `codesearch_target` and
    `codesearch_reasoning`, so the committed table shows what was considered and
    on what ground it was declined.
    """
    text = TEMPLATE.format(label=label, specimen=specimen)
    answer = {c: "" for c in PROVENANCE_COLUMNS + LOG_ONLY_COLUMNS
              + ["loinc_code", "loinc_display", "comment"]}
    answer["codesearch_query"] = text

    confidence = 0.0
    try:
        result = find_code(service, text, timeout)
    except Exception as exc:                          # noqa: BLE001
        answer["codesearch_status"] = f"error: {str(exc)[:80]}"
        result = None
    if result is not None:
        answer["path"] = result.get("path", "")
        matches = result.get("matches") or []
        if not matches:
            answer["codesearch_status"] = "no-match"
        else:
            match = matches[0]
            confidence = float(match.get("confidence") or 0.0)
            answer["codesearch_confidence"] = f"{confidence:.2f}"
            answer["codesearch_reasoning"] = (match.get("reasoning") or "").strip()
            answer["codesearch_target"] = match["code"]
            answer["codesearch_display"] = match.get("display", "")
            if confidence < CONFIDENCE_THRESHOLD:
                answer["codesearch_status"] = "below-threshold"
            else:
                status, display = gate(fhir_base, match["code"])
                answer["codesearch_status"] = status
                if status == "ok":
                    answer.update(loinc_code=match["code"],
                                  loinc_display=display)
                    return answer

    answer["comment"] = declined_comment(answer, confidence)
    return answer


def recorded_answers(path):
    """{sentence: answer} for every sentence the committed table records.

    Keyed on `codesearch_query` — the FULL TEMPLATED SENTENCE the service was
    given — and that key is the whole safety argument for --replay. A reused
    answer is only ever reused for the identical question, so changing the
    template, the specimen word or a label invalidates exactly the rows whose
    sentence changed and nothing else: a new question simply is not in this
    index, and gets asked. There is no way to launder a stale answer into a
    changed query, because the query is the key.

    What it does NOT cover is a change to the CONSTRAINT or the THRESHOLD, which
    change how an answer is judged rather than what was asked. The sentences
    would all still match and every recorded verdict would be the old rule's.
    Re-run without --replay after touching either.

    Rows the pre-filter declined carry no sentence and are skipped; they are
    re-derived from the dictionary on every run anyway.
    """
    with open(path, newline="") as fh:
        return {row["codesearch_query"]: {
                    **{c: row.get(c, "") for c in PROVENANCE_COLUMNS},
                    **{c: row.get(c, "") for c in TARGET_COLUMNS},
                    "comment": row.get("comment", ""),
                    # LOG_ONLY, and a property of the run that fetched the
                    # answer rather than of the answer. A replay did not fetch
                    # it, so it reports none.
                    "path": "",
                }
                for row in csv.DictReader(fh)
                if row.get("codesearch_query")}


def declined_comment(answer, confidence):
    """Why a row carries no target. load_table requires one, and rightly: an
    empty target is a claim that the source could not answer, and a claim has to
    say what it rests on.

    Phrased against the templated sentence rather than the label, because that is
    the string the service was actually given — and because the label alone would
    not say which specimen was asked about.
    """
    asked = answer["codesearch_query"]
    proposal = (f"{answer['codesearch_target']} "
                f"|{answer['codesearch_display']}| at {confidence:.2f}")
    return {
        "no-match": (f"code-search returned no match for {asked!r} within "
                     f"{CONSTRAINT_VCL}."),
        "below-threshold": (f"code-search proposed {proposal} for {asked!r}, "
                            f"below the {CONFIDENCE_THRESHOLD} threshold."),
        "out-of-constraint": (f"code-search proposed {proposal} but that code "
                              f"is not a member of {CONSTRAINT_VCL}."),
        "absent": f"code-search proposed {proposal} but that code is not known.",
    }.get(answer["codesearch_status"],
          f"code-search: {answer['codesearch_status']}.")


# --------------------------------------------------------------------------- #
# Reporting
# --------------------------------------------------------------------------- #


def report(rows, queries):
    """What the run found. Printed so it can be pasted into a write-up."""
    mapped = [r for r in rows if r["loinc_code"]]
    asked = [r for r in rows if r["codesearch_status"] != "not-searchable"]
    print(f"\n  {len(rows)} item(s) over {len(queries)} quer(ies): "
          f"{len(mapped)} mapped, {len(rows) - len(mapped)} declared unmapped "
          f"({len(rows) - len(asked)} of them never asked — see pre-filter)")

    statuses = {}
    for row in rows:
        statuses[row["codesearch_status"]] = \
            statuses.get(row["codesearch_status"], 0) + 1
    print("\n  answer status")
    for status, count in sorted(statuses.items()):
        print(f"    {status:<18} {count:>5}")

    # One confidence per QUERY, not per item: counting a key shared by three
    # itemids three times would overstate how many independent answers the run
    # actually got.
    by_query = {}
    for row in rows:
        if row["codesearch_confidence"]:
            by_query[row["codesearch_query"]] = \
                float(row["codesearch_confidence"])
    scored = sorted(by_query.values())
    if scored:
        print(f"\n  code-search confidence, {len(scored)} quer(ies) answered")
        buckets = [(1.0, 1.01), (0.9, 1.0), (0.8, 0.9), (0.7, 0.8), (0.0, 0.7)]
        for low, high in buckets:
            hits = [s for s in scored if low <= s < high]
            label = f"{low:.2f}" if high > 1.0 else f"{low:.2f}–{high:.2f}"
            bar = "#" * min(len(hits), 60)
            print(f"    {label:<12} {len(hits):>5}  {bar}")
        print(f"    threshold {CONFIDENCE_THRESHOLD}: "
              f"{sum(1 for s in scored if s >= CONFIDENCE_THRESHOLD)} kept, "
              f"{sum(1 for s in scored if s < CONFIDENCE_THRESHOLD)} dropped")

    # Coverage by specimen, which is the axis this stream's template exists to
    # serve — if the fluid injection is doing its job the non-blood fluids should
    # not be dramatically worse than Blood.
    by_fluid = {}
    for row in rows:
        fluid = row["_fluid"]
        total, hit = by_fluid.get(fluid, (0, 0))
        by_fluid[fluid] = (total + 1, hit + (1 if row["loinc_code"] else 0))
    print("\n  coverage by specimen")
    for fluid, (total, hit) in sorted(by_fluid.items(),
                                      key=lambda kv: -kv[1][0]):
        print(f"    {fluid:<22} {hit:>4}/{total:<5} {100 * hit / total:5.1f}%")

    # How many distinct targets the mapped rows share. A generic target is not
    # wrong, but several analytes landing on one code means a consumer
    # aggregating by Observation.code merges them, so it is worth seeing.
    if mapped:
        shared = {}
        for row in mapped:
            shared.setdefault((row["loinc_code"], row["loinc_display"]),
                              []).append(row)
        collisions = [(k, v) for k, v in shared.items() if len(v) > 1]
        print(f"\n  {len(mapped)} mapped row(s) over {len(shared)} distinct "
              f"target(s); {len(collisions)} target(s) carry more than one item")
        for (code, display), group in sorted(
                collisions, key=lambda kv: (-len(kv[1]), kv[0][0]))[:20]:
            labels = ", ".join(r["mimic_display"] for r in group)
            print(f"    {code:<10} {display[:40]:<42} {len(group):>3}  "
                  f"{labels[:60]}")

    commented = [r for r in rows if r["loinc_code"] and r["comment"]]
    if commented:
        print(f"\n  {len(commented)} mapped row(s) carrying a reviewed comment")
        for row in commented:
            print(f"    {row['mimic_code']} {row['mimic_display'][:26]:<26} "
                  f"-> {row['loinc_code']:<10} {row['loinc_display'][:40]}")


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #


def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    add_common_args(parser)
    parser.add_argument("--service",
                        default=DEFAULT_CODE_SEARCH or "http://localhost:3000",
                        help="code-search base URL (default: $CODE_SEARCH_URL "
                             "or %(default)s)")
    parser.add_argument("--workers", type=int, default=6,
                        help="concurrent code-search calls (default: %(default)s)")
    parser.add_argument("--timeout", type=int, default=600,
                        help="per-call timeout in seconds (default: %(default)s)")
    parser.add_argument("--only",
                        help="comma-separated mimic codes to ask about, for "
                             "tuning TEMPLATE against a handful of items. "
                             "Implies --dry-run: a table built from a subset "
                             "would drop every item it did not ask about.")
    parser.add_argument("--dry-run", action="store_true",
                        help="report only; do not write the CSV")
    parser.add_argument("--replay", action="store_true",
                        help="reuse the committed table's answer for any "
                             "sentence it already records, and ask code-search "
                             "only for sentences that are new. Safe across a "
                             "template or specimen change, which simply produces "
                             "new sentences; NOT safe across a constraint or "
                             "threshold change, which re-judges old ones.")
    args = parser.parse_args()

    configure_tls(args.ca_bundle, args.insecure)
    if not args.fhir_base:
        sys.exit("  no --fhir-base and ONTOSERVER_URL unset — the validation "
                 "gate needs a terminology server.")

    codes = ig_codes()
    if not codes:
        sys.exit("  no source codes — CodeSystem-mimic-d-labitems.json is "
                 "missing from input/resources/, so this would write an empty "
                 "table over a real one.")
    labitems = dictionary(codes)
    items = sorted(codes.items())
    if args.only:
        wanted = {c.strip() for c in args.only.split(",") if c.strip()}
        unknown = wanted - set(codes)
        if unknown:
            sys.exit(f"  --only names code(s) not in the IG: {sorted(unknown)}")
        items = [i for i in items if i[0] in wanted]
        args.dry_run = True

    # The pre-filter runs first, so an item the dictionary disqualifies is
    # declined without joining a query and cannot drag a search along with it.
    # Derived once, off the whole dictionary rather than off `items`, so that
    # --only cannot change what any surviving row is asked: a subset run that
    # happened to exclude `50822 Potassium, Whole Blood` would otherwise stop
    # seeing the contrast and quietly ask `50971` the old sentence.
    overrides = specimen_override(labitems)

    rows_by_code, asked = {}, {}
    for code, label in items:
        row = blank_row(code, label)
        # Carried for the report and the log, then dropped before the CSV is
        # written — the committed table's columns are CURATED + PROVENANCE.
        row["_fluid"] = labitems[code]["fluid"]
        row["_category"] = labitems[code]["category"]
        # What the SENTENCE will say, which is the fluid column for all but the
        # rows SPECIMEN_OVERRIDE moves. Kept beside `_fluid` rather than
        # replacing it: the report breaks coverage down by the dictionary's own
        # specimen families, and that stays the right axis for reading it.
        row["_specimen"] = overrides.get(code, labitems[code]["fluid"])
        ok, why_not = searchable(labitems[code])
        if ok:
            asked[code] = row
        else:
            decline_unasked(row, why_not)
        rows_by_code[code] = row

    # One search per (label, specimen), not per item. The label is the
    # DICTIONARY's, stripped — `mimic_display` in the committed table stays the
    # IG's exact string, which load_curated requires, and `codesearch_query`
    # records the sentence actually sent, so the collapse is visible in the CSV.
    #
    # Keyed on the specimen the sentence states, not on `fluid`: two rows are the
    # same question only if they are asked the same question, and after
    # SPECIMEN_OVERRIDE those are no longer the same thing.
    queries = {}
    for code, row in asked.items():
        key = (labitems[code]["label"].strip(), row["_specimen"])
        queries.setdefault(key, []).append(code)
    ordered = sorted(queries)

    print(f"  {len(items)} IG code(s)"
          + (f" (subset of {len(codes)}, --only)" if args.only else ""))
    print(f"  dictionary: {D_LABITEMS_GZ.relative_to(TERM.parents[1])} "
          f"({len(labitems)} matched)")
    print(f"  pre-filter: {len(asked)} searchable; "
          f"{len(items) - len(asked)} declined unasked")
    # Loaded after the collapse so the count below is against the queries this
    # run will actually make, which is the number a reader wants to see.
    recall = None
    if args.replay:
        if not OUT_CSV.is_file():
            sys.exit(f"  --replay needs {OUT_CSV.name} and it does not exist. "
                     f"Run without --replay to build it once.")
        recall = recorded_answers(OUT_CSV)

    print(f"  queries:    {len(asked)} item(s) collapse to {len(ordered)} "
          f"distinct (label, specimen) key(s)")
    if args.replay:
        fresh = [k for k in ordered
                 if TEMPLATE.format(label=k[0], specimen=k[1]) not in recall]
        print(f"  mode:       REPLAY — {len(ordered) - len(fresh)} sentence(s) "
              f"answered from {OUT_CSV.name}, {len(fresh)} to ask")
        for key in fresh:
            print(f"                new: "
                  f"{TEMPLATE.format(label=key[0], specimen=key[1])}")
    print(f"  specimen:   {len(overrides)} item(s) asked as "
          f"{SERUM_SPECIMEN!r} rather than their fluid column "
          f"(MIMIC names a whole-blood sibling)")
    print(f"  gate:       {args.fhir_base}")
    print(f"  service:    {args.service}")
    print(f"  constraint: {CONSTRAINT_VCL}")
    print(f"  template:   {TEMPLATE}")
    print(f"  threshold:  {CONFIDENCE_THRESHOLD}")
    print(f"  comments:   {len(COMMENT_OVERRIDES)}\n")

    reused = 0

    def work(key):
        nonlocal reused
        label, specimen = key
        recorded = (recall or {}).get(
            TEMPLATE.format(label=label, specimen=specimen))
        if recorded is not None:
            reused += 1
            return dict(recorded)
        answer = search_query(label, specimen, args.fhir_base, args.service,
                              args.timeout)
        members = sorted(queries[key])
        fanned = f"x{len(members)}" if len(members) > 1 else ""
        print(f"    {label[:28]:<28} {specimen[:18]:<20} "
              f"{answer['codesearch_status']:<18} "
              f"{answer['loinc_code'] or '—':<10} "
              f"{answer['loinc_display'][:32]:<34} {fanned}", flush=True)
        return answer

    with concurrent.futures.ThreadPoolExecutor(args.workers) as pool:
        answers = dict(zip(ordered, pool.map(work, ordered)))

    if recall is not None:
        print(f"\n  reused {reused} of {len(ordered)} sentence(s) from "
              f"{OUT_CSV.name}; {len(ordered) - reused} asked")

    # Fan each query's one answer back across the itemids sharing its key. This
    # is what makes `50811` and `51222` — both `Hemoglobin` in `Blood` —
    # disagreeing unrepresentable.
    for key, members in queries.items():
        for code in members:
            rows_by_code[code].update(answers[key])

    # Sorted by mimic_code so a re-run diffs only where an answer changed, not
    # wherever the thread pool happened to finish first.
    rows = sorted(rows_by_code.values(), key=lambda r: r["mimic_code"])

    # A transport failure is not an answer, so a partial run writes nothing.
    failed = [r for r in rows if r["codesearch_status"].startswith("error")]
    if failed:
        print(f"\n  {len(failed)} of {len(rows)} code-search call(s) failed "
              f"after retries — NOT writing {OUT_CSV.name}.")
        for row in failed[:5]:
            print(f"    {row['mimic_code']} {row['mimic_display'][:26]:<26} "
                  f"{row['codesearch_status'][:70]}")
        if len(failed) > 5:
            print(f"    … and {len(failed) - 5} more")
        sys.exit("  Fix the service and re-run; cached answers make the "
                 "retry cheap.")

    # The invariant the (label, specimen) collapse exists to guarantee, asserted
    # rather than assumed. The fan-out above makes divergence structurally
    # impossible, so this can only fire if the grouping and the fan-out ever stop
    # agreeing — and the whole point of the rule is that a reader should not have
    # to trust that they do.
    diverged = {key: sorted({rows_by_code[c]["loinc_code"] or "(unmapped)"
                             for c in members})
                for key, members in queries.items()
                if len({rows_by_code[c]["loinc_code"] for c in members}) > 1}
    if diverged:
        for key, targets in sorted(diverged.items()):
            print(f"    {key}: {targets}", file=sys.stderr)
        sys.exit(f"  {len(diverged)} quer(ies) whose itemids ended up on "
                 f"different targets, which the (label, specimen) collapse "
                 f"exists to prevent. NOT writing {OUT_CSV.name}.")

    apply_comments(rows)
    report(rows, ordered)

    if args.dry_run:
        print("\n  --dry-run: nothing written")
        return

    columns = CURATED + PROVENANCE_COLUMNS
    with open(OUT_CSV, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns)
        writer.writeheader()
        writer.writerows({c: row[c] for c in columns} for row in rows)
    print(f"\n  wrote {OUT_CSV.relative_to(TERM.parents[1])}")

    LOG_JSON.parent.mkdir(parents=True, exist_ok=True)
    LOG_JSON.write_text(json.dumps({
        "constraint_vcl": CONSTRAINT_VCL,
        "constraint_url": constraint_url(),
        "template": TEMPLATE,
        "confidence_threshold": CONFIDENCE_THRESHOLD,
        # Which mode wrote this file. Under `replay` most answers are the
        # earlier run's, reused because the sentence was unchanged; a log
        # claiming a full run would overstate what this file rests on.
        "run_mode": ("replay" if args.replay else "search"),
        **({"replay": {"sentences": len(ordered), "reused": reused,
                       "asked": len(ordered) - reused,
                       "source": OUT_CSV.name}} if args.replay else {}),
        "pre_filter": {
            "dictionary": str(D_LABITEMS_GZ.relative_to(TERM.parents[1])),
            "specimen_suffix": SPECIMEN_SUFFIX,
            "declined_unasked": {
                code: rows_by_code[code]["comment"]
                for code in sorted(set(codes) - set(asked))},
        },
        # Every row whose sentence states something other than its `fluid`
        # column, with the sibling that licensed it, so the override is
        # auditable without re-deriving it from the dictionary. Empty is the
        # expected state for a dictionary that names no whole-blood variant.
        "specimen_override": {
            "rule": (f"an item whose category is {SERUM_CATEGORY!r} and whose "
                     f"(label, fluid) also exists as '<label>, Whole Blood' is "
                     f"asked as {SERUM_SPECIMEN!r}"),
            "items": {code: {"label": labitems[code]["label"].strip(),
                             "fluid": labitems[code]["fluid"],
                             "asked_as": specimen}
                      for code, specimen in sorted(overrides.items())},
        },
        # Which itemids shared a query, so the collapse is auditable without
        # re-deriving it from the dictionary.
        "query_key": ["label", "specimen"],
        "shared_queries": {f"{label} [{specimen}]": sorted(members)
                           for (label, specimen), members
                           in sorted(queries.items())
                           if len(members) > 1},
        "comment_overrides": {f"{code}->{target}": comment
                              for (code, target), comment
                              in sorted(COMMENT_OVERRIDES.items())},
        "fhir_base": args.fhir_base,
        "codesearch_service": service_info(args.service),
        "rows": rows,
    }, indent=2) + "\n")
    print(f"  wrote {LOG_JSON.relative_to(TERM.parents[1])}")


if __name__ == "__main__":
    main()
