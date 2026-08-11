#!/usr/bin/env python3
# Raw docstring: it quotes the instance-index regex `#\s*\d+` verbatim, and in a
# plain string those are invalid escapes.
r"""Generate conceptmaps/chartevents-standard.csv — the 2,982 ICU chart items.

The seventh generated table, the last stream issue #20 lists, and the FIRST
MIXED-TARGET table in this repo: it names its target system per ROW, because
which terminology answers is a result of the search rather than a property of
the stream. Every table before it aims at exactly one system and says so in its
column headings; this one carries `target_system, target_code, target_display`
and lib/curated.py checks each row's system against the ones the source
declared. See lib/curated.py MIXED_TARGET_COLUMNS for the shape and
lib/assemble.py for how one stream then spans two R4 groups.

WHAT THE SOURCE CODES MEAN. mimic-chartevents-d-items holds 2,982 items from
MIMIC's `d_items` dictionary whose `linksto` is `chartevents`, bound to
Observation.code on MimicObservationChartevents. Each is one column of an ICU
bedside flowsheet. It is by some distance the largest coded Observation
population in the warehouse — 313.6M occurrences, 68.0% of every occurrence of
Observation.code — and until this stream lands all of it sits in the
`no-stream-yet` bucket of output/occurrence-buckets.csv.

THE POPULATION IS NOT ONE THING, which is the whole argument for two systems.
Reading the 2,982 labels against their `category` there are four kinds:

  ~400  quantitative bedside measurement — vital signs, haemodynamics,
        ventilator settings. LOINC is exact here: `Heart Rate` -> 8867-4,
        `Central Venous Pressure` -> 60985-9, `Respiratory Rate` -> 9279-1.

   160  bedside LABORATORY analytes charted in the flowsheet (`category = Labs`:
        `Hemoglobin`, `Arterial O2 pressure`, `WBC`). These are LOINC
        CLASSTYPE=1 and nothing else reaches them — `2703-7 |Oxygen [Partial
        pressure] in Arterial blood|` and `718-7 |Hemoglobin [Mass/volume] in
        Blood|` are both Laboratory-class, so a Clinical-only constraint makes
        the whole category unmappable, and SNOMED has no target for them at
        MIMIC's granularity at all (a filtered $expand of <<363787002 for
        haemoglobin returns 13 concepts, none of them whole-blood Hb mass
        concentration).

 ~1400  NURSING ASSESSMENT — skin and wound detail, line sites, neurological
        and GI observations, positioning, limb colour. This is where SNOMED CT
        earns its place: `Position`, `Speech` and `RUE Color` are all refused by
        LOINC above threshold and answered correctly by SNOMED
        (`397155001 |Body position|`, `363918005`, `248412009 |Color of
        extremity|`).

  ~500  NOT AN OBSERVATION OF THE PATIENT — care-plan documentation slots, note
        templates, device alarm limits, workflow fields. Most decline on the
        constraint. 216 of them demonstrably do not, and are pre-filtered — see
        THE PRE-SEARCH DECLINES.

Neither terminology covers this population alone, which is what makes the
mixed-target shape worth its machinery. Note that build_outputevents_table.py
and build_labevents_table.py both probed a SNOMED second opinion and REJECTED
it: there, one rescued row did not pay for per-row `target_system` columns and
the lib/assemble change. Here the SNOMED-only tail is the largest single slice
of the population, so the same trade comes out the other way.

THE RESOLUTION RULE, applied identically to every query and involving no per-item
judgement:

    LOINC pass (CONSTRAINT_VCL)   answers >= threshold and passes the gate
                                  -> that is the mapping, target_system = LOINC
    otherwise SNOMED pass (CONSTRAINT_ECL) on the SAME text
                                  -> that is the mapping, target_system = SNOMED
    otherwise                     -> unmapped, BOTH proposals recorded

LOINC first rather than SNOMED first because the bound element is
Observation.code and LOINC is the observation-code terminology; SNOMED is
consulted for what LOINC does not carry. The consequence is stated rather than
hidden: a SNOMED answer never competes with a LOINC one, so an item LOINC
answers adequately and SNOMED answers better keeps the LOINC code. The
alternative — run both always and pick the higher confidence — was not taken,
because confidence is not comparable across two services' searches of two
different terminologies, and picking on it would be exactly the "confidence
separates good from bad" assumption every stream in this repo has had to unlearn.

WHY THE CONSTRAINT AND NOT THE CONFIDENCE, for the seventh stream running.
Unconstrained, both systems answer ordinary labels with concepts that are not
legal Observation.code values, at the confidences a real answer scores:

    Hemoglobin        LOINC  LP32067-8 |Hemoglobin|         a PART       1.00
    Position          LOINC  LP73131-2 |Position|           a PART       1.00
    Therapeutic Bed   SNOMED 706104005                  physical object  1.00
    Position          SNOMED 246268007 |Position|          attribute     1.00
    Multi Lumen …     SNOMED 469489009               physical object     0.85
    Arterial O2 …     SNOMED 25579001                     procedure      0.85

$validate-code confirms none of the six is a member of the constrained space it
would have come from, so the constraint PREVENTS them rather than rejecting them
afterwards. Four of the six score 1.00. This is the `Foley Catheter` lesson of
build_d_items_table.py for the seventh time.

THE LOINC CONSTRAINT IS THE UNION OF CLASSTYPE 1, 2 AND 4, and both the union
and the later addition of 4 are changes of mind recorded here because the
reasoning matters.

SURVEY (CLASSTYPE=4) WAS ADDED SECOND, and the argument for it is that this
population is largely nursing assessment and CLASSTYPE=4 is where LOINC keeps
nursing assessment instruments. The first table generated without it covered
`param_type = Numeric` items at 85.3% of occurrences and `Text` items at 50.3%,
and Text is 69.7% of the stream — so the gap is qualitative nursing
documentation, which is exactly Survey's content.

IT IS NOT ADDITIVE, and this paragraph is a correction of what this docstring
claimed before the widening was run. The claim was that widening "cannot displace
an existing mapping", on the evidence that every code the 1|2 constraint landed
on is itself CLASSTYPE=2 (`91380-6`, `83186-7`, `80344-5`, `8693-4`, ...). That
check was real but it does not support that conclusion: it shows no existing
target was EXCLUDED from the widened pool, not that none would be OUTCOMPETED
inside it. This stream runs ONE union query, so a Survey code that scores higher
displaces the answer that used to win. Measured on the first full run, 56
mappings moved to a CLASSTYPE=4 target, carrying 8.5M occurrences.

Some of those displacements are clearly better — `227341 History of falling
(within 3 mnths)` moved from `91380-6 |Number of falls in the past 3 months|` to
`59454-9 |History of falling … [Morse Fall Scale]|`, and `227343 Ambulatory aid`
from SNOMED `165251008 |Walking aid use|` to `59456-4 |Ambulatory aid [Morse Fall
Scale]|`, which is the instrument MIMIC is actually charting. That is the
argument for the widening. It is not the argument that was originally written
here, and "additive" was simply wrong.

WHAT THE WIDENING ACTUALLY BOUGHT, from the first full run under it: 147 of the
866 LOINC mappings target a CLASSTYPE=4 code, carrying 11.1M occurrences —
Morse Fall Scale, NIH Stroke Scale, NSRAS, CAM-ICU, OMAHA and CCC items, which
is exactly the nursing-assessment content the stream was missing. A 12-label
probe had predicted one threshold crossing; the population produced 147. The
probe understated it by two orders of magnitude, which is the general lesson
about probes in this file.

THE CACHE MAKES A CONSTRAINT CHANGE EXPENSIVE TO INTERPRET, and this is the part
to read before trusting a diff. code-search caches on (text, url, system), so
changing CONSTRAINT_VCL changes the URL and every LOINC query becomes a fresh LLM
evaluation. On the first run under 1|2|4, 202 mappings changed target and only 76
of them are attributable to either deliberate change — 56 to Survey and 20 to the
scale gate. The remaining 126, carrying 12.3M occurrences, moved for no reason
this repo can name: same label, same pool, different answer. Two of those are
regressions on high-volume items:

    220277 O2 saturation pulseoxymetry  59408-5 |… by Pulse oximetry|
                                     -> 2708-6  |Oxygen saturation in Arterial
                                                 blood|      6.3M occ, LESS
                                                 specific than the item is
    223983 LLE Color                    SNOMED 248412009 |Colour of extremity|
                                     -> 39107-8 |Color of Skin|

`248412009` is the concept THE SNOMED CONSTRAINT section above cites as a case
where SNOMED earns its place, so that one moved against this file's own stated
judgement.

So the headline moved +0.38 points while 8% of the stream changed target, mostly
for unattributable reasons. A NEXT STEP THAT WOULD SETTLE IT: re-run with a
semantically identical but textually different constraint — `CLASSTYPE/"2|1"`
instead of `CLASSTYPE/"1|2"` — which changes the cache key without changing the
pool, and diff against the committed 1|2 table. That isolates pure run-to-run
LLM variance from any constraint effect, and it is the measured variance this
docstring has admitted twice that it does not have. Note that re-running the
ORIGINAL `1|2` cannot do this: it is a cache HIT and would replay bit-identical
answers by construction.

THE 1-AND-2 UNION CAME FIRST, and this is the argument it rested on, kept because
adding Survey does not retire it: the question of whether to merge classes or run
them as disjoint passes is the same question whether there are two classes or
three. Probing on one code-search
deployment, `Heart rate Alarm - High` came back as a UNION-ONLY answer — both
narrow class passes declined it and the union proposed `19946-3 |Maximum heart
rate setting Apnea Monitor Alarm|`, a code that is itself CLASSTYPE=2 and was
therefore inside the clinical pass all along. That is the merged-constraint
failure build_micro_test_table.py documents, and it argued for two disjoint
passes with an exactly-one-may-answer rule.

It did not reproduce on the deployment that generates this table. There, the
clinical pass finds `19946-3` directly, the laboratory pass finds `718-7`
directly, and the union returns exactly what the correct narrow pass returns —
inventing nothing and suppressing nothing. With no measured harm from merging,
the split would be complexity without a correctness argument, so this stream
uses ONE union pass.

(Those probe cells were re-run and reported "stable". They were not: the service
caches on (text, url, system), so a repeat of an identical query is a cache hit
and bit-identical BY CONSTRUCTION. No probe in this file has a measured
variance, and nothing here should be read as claiming one. What the union rests
on instead is the first full run: across all 2,124 queries only 9 of 859 LOINC
rows are non-`Labs` items landing on Laboratory codes, ~1%, and every one of
those is caused by a bare abbreviation rather than by the merged pool — a
disjoint Laboratory pass would have found the same code with no clinical-pass
competitor to displace it. Meanwhile the union carries `Labs` at 88.8%, the
best-covered category in the stream.)

Which is also the reason this docstring names a deployment at all. Table
generation is the one stage whose output is not a pure function of this repo,
and the probes behind these settings were run against TWO code-search
deployments backed by different models — the settings were then re-derived
against the one that generates. output/chartevents-generation-log.json records
`codesearch_service` verbatim, as every generation log here does, so which model
produced a given table is answerable from the committed artefacts rather than
from memory.

THE SNOMED CONSTRAINT IS <<363787002 |Observable entity| ALONE, and is NOT the
`(<<71388002 OR <<404684003 OR <<272379006)` of the two ICU procedure streams.
Two reasons, one structural and one measured. Structurally, a clinical FINDING
belongs in Observation.value, not in Observation.code, so the 129k concepts
<<404684003 would add are wrong for this binding whatever they retrieve.
Measured, widening converts correct declines into confident wrong answers:

    Heart rate Alarm - High   <<363787002        no match          (right)
                              +<<404684003  3424008 |Tachycardia|  0.85
    ETT Location              <<363787002        no match          (right)
                              +<<404684003  419991009 |ETT present|

Asserting tachycardia on a patient because a monitor's alarm LIMIT was charted
is the most falsifying error available in this dataset, and the narrow
constraint is what refuses it. Adding <<272379006 |Event| on top contributes
3,326 concepts and changed no answer for the better on any probe.

TEMPLATE IS THE IDENTITY WRAPPER `{}` — the bare label, the second stream to
send no context after build_micro_org_table.py, and for a sharper reason. MIMIC
records a `category` per item and injecting it was the obvious move; it was
probed over 20 labels against two systems and REJECTED, because it makes junk
answer with the template's own words:

    Coefficient Hospital Mortality   bare label     no match in EITHER system
      + "charted under Scores - APACHE IV (2)"  ->  1351474005 |APACHE IV score|
      reasoning: "FSN matches APACHE IV score observable entity"          0.85

"APACHE IV" appears nowhere in that item's label — it is a regression
coefficient, not a score — and the category word alone conjured an above-
threshold answer that both systems refuse on the label. A second deployment
produced the same failure with a different code, `84243-5 |Nurse Intensive care
unit Flowsheet|`, reasoning "Closest match for 'ICU flowsheet observation'". The
service codes the sentence when the label carries no clinical content, which is
the failure build_labevents_table.py records for `category` and the reason that
stream's query key is (label, fluid) and not (label, fluid, category).

RE-TESTED AFTER THE FIRST FULL RUN, because that run exposed a failure class the
20-label probe set did not contain: ABBREVIATIONS the category would have
disambiguated. `224017 GU Catheter Size` -> `78945-3 |Guiding catheter size|`,
reasoning "GU = Guiding" — GU is Genitourinary, so 674k Foley sizes are filed as
cardiac guiding-catheter sizes. `224702 PCV Level` (Respiratory, hence Pressure
Control Ventilation) -> a haematocrit. `228273 FM Measures` (Family Mtg Note) ->
fetal movement. `220561 ZINR` -> `286617004 |Zinc intake|`. That is a real cost
of the identity wrapper and it deserved a decisive experiment rather than a
defence of the original choice.

Two candidates were run over 25 items — the 12 known abbreviation defects, 3
contentless labels the wrapper protects, 3 rows where the category might
REINFORCE an error, and 7 correct controls — through the full resolution rule,
gate and threshold. Bar set in advance: fix >= 6 defects, rescue NO contentless
label, disturb <= 1 control.

    T1  `ICU flowsheet observation charted under {category}: {label}`
        6 of 12 fixed, but 2 rescues and 2 controls lost         FAIL
    T2  `{label} ({category})`
        4 of 12 fixed, 2 rescues, 2 controls lost                FAIL

T2 existed to test the theory that a parenthetical adds context without
contributing a codeable noun phrase. FALSIFIED: the CATEGORY VALUE is itself
codeable content. Both templates answered `226893 Coefficient Hospital
Mortality` with `1351474005 |APACHE IV score|`, T2 reasoning "APACHE IV score
matches; coefficient/version qualifiers not separately coded" — it took "APACHE
IV" from the category string and discarded the word the label is about. T1 coded
its own words again too, on `229570 Plan-ID` -> `84243-5 |Nurse Intensive care
unit Flowsheet|`.

Both also lose `224082 Turn` -> `282984004 |Ability to turn|` (2.41M
occurrences) outright, displace `224093 Position`, and defeat the service's
deterministic fast path so that every query goes through LLM evaluation with
confidences compressed toward 0.85 — flattening the signal a reviewer triages
on. T2 makes one known defect HARDER to catch, raising `226766
MapApacheIIValue` on the wrong `9264-3 |Apache II score|` from 0.85 to 0.95.

So the abbreviation defects stay, documented rather than fixed: no template
setting removes them without buying worse. They are the `227719 AVA` and
`50823 Required O2` case again — a target that is perfectly good for some other
source and simply wrong for this one — and the only remaining lever is a
per-item abbreviation glossary, which is curation against rows seen to fail and
is what COMMENT_OVERRIDES exists to forbid.

THE PRE-SEARCH DECLINES, 216 items, read off the dictionary and applied to every
item identically — the build_labevents_table.py pattern, where an item the
dictionary disqualifies is declined WITHOUT being searched because a search it
should not have been sent would be answered confidently anyway.

  Care Plans (133)  every one is `<X> NCP - {Goal | Expected outcomes |
                    Outcomes met | Interventions}`, a nursing-care-plan
                    documentation slot. `228890 Pain NCP - Interventions`
                    returns `80340-3 |Nonpharmacologic intervention for pain|`
                    at 0.90 on the BARE label, in-constraint and past the gate:
                    a care-plan slot recording that an intervention was
                    documented is not the observable that intervention would be.
                    No constraint or threshold catches it.

  Alarms (38)       every one is `<X> Alarm - {High | Low}`, a device alarm
                    LIMIT. `220046 Heart rate Alarm - High` maps wrongly in BOTH
                    systems under the settings above — LOINC `19946-3` at 0.85
                    (and an apnea monitor's, not an ICU monitor's) and SNOMED
                    `364075005 |Heart rate|` at exactly 0.80. An alarm threshold
                    is a device setting, not a measurement of the patient, and
                    coding it as the measurement makes the data say a value was
                    observed that never was.

  Generic Proc      (28) every one is a procedural-workflow attestation —
  Note              `Timeout Performed By`, `Patient Identified Correctly`,
                    `Side (Gen Proc)`, `Hand Cleansing prior to procedure`. The
                    first full run mapped 13 of them, to the safety-checklist
                    LOINC codes and to `258154008 |Washing hands|`: all
                    structurally the Care Plans case, a record that a step
                    happened rather than an observation of the patient.

  alarms by label   (17) an alarm limit does not stop being one because the
                    dictionary filed it under the device. The Centrimag, ECMO,
                    HeartWare, VAD and IABP flow and pressure alarms sit outside
                    `Alarms`, and 2 of them mapped in the first run —
                    `229847 SvO2 Alarm (Lo) (CH)` to `19224-5 |Mixed venous
                    oxygen saturation|`, `229258 Flow Alarm (Lo) (LVAD)` to
                    `444479000 |Flow rate|` — a threshold SETTING coded as the
                    measurement it is a threshold for. See ALARM_LABEL_RE.

Every one is a uniform property of a dictionary field, not a list of labels seen
to come back wrong — the distinction build_micro_test_table.py draws when it
declines to write a reject list. That is also why `Restraint/Support Systems`,
`OT Notes`, `MD Progress Note` and `Adm History/FHPA` are NOT pre-filtered
despite each holding some documentation slots: the first run mapped genuine
functional-status observables there (`227831 Grooming` -> `96767-9`,
`227854 Weight Bearing Status` -> `364579007`, `227346 Mental status` ->
`8693-4`), so a blanket decline would destroy value that the constraint is
successfully finding.

ONE QUERY PER COLLAPSED LABEL, CASE-FOLDED — 2,766 searchable items collapsing
to 2,124 searches. 629 of the 2,982 labels carry an instance index (`Impaired
Skin Site #1` … `#10`, `Angio Site # 2`), and stripping `#\s*\d+` leaves 94
families. This is a correctness rule and not an optimisation, the same one
build_micro_test_table.py and build_labevents_table.py make: nothing
distinguishes `Pressure Ulcer Stage #3` from `#7` but the index, so a map where
they receive different targets is wrong however plausible each row looks alone.
The fan-out makes divergence unrepresentable and main() asserts it anyway.

The key is case-folded for the same reason, learned from the first full run: the
service is not case-stable, and `Face to Face Eval (Non-violent)` mapped to
`51848-0` while `(Non-Violent)` came back unmapped — one capital letter, three
affected families. Casing is not meaning.

The collapsed label is otherwise the whole query key, which was measured rather
than assumed: keying on (collapsed label, category) yields the identical count of
distinct keys over the full population, i.e. no collapsed label spans two
categories, so category can add nothing to the key. That matters because the
template sends the label alone — a key finer than the text sent would issue two
identical searches and invite them to disagree.

NOT collapsed: LATERALITY. `RUE`/`LUE`/`RLE`/`LLE Temp` disagree in the first
run's output and it is tempting to fold them the way the instance index is
folded. It would be wrong. LOINC carries genuinely lateralised codes and 24
mapped rows use them — `Dorsal PedPulse R` -> `74782-4 |… Dorsal pedal artery -
right|` and `Dorsal PedPulse L` -> `8902-9 |… - left|` are CORRECT and must
differ, as are both `Pupil Size` items. A regex cannot tell a family whose
target has no laterality (where the limbs should agree) from one whose target
does (where they must not), so folding would trade four noisy families for four
correctly lateralised ones. The limb divergence is a real defect with no clean
instrument; it is left standing rather than papered over.

THE GATE is per system, because the two terminologies fail differently. LOINC:
membership asserted with $validate-code against the constraint rather than
assumed from the service having been asked nicely, and the display replaced with
the server's own LONG_COMMON_NAME. SNOMED: the three checks
verify_curated_snomed.py enforces — exists, is active, is in the international
core module rather than a national extension — plus the server's preferred term
as the display. LOINC needs no active or extension check: STATUS=ACTIVE is
carried by the constraint itself and LOINC has no national extensions.

TWO GATES RUN AFTER THAT ONE, and they check different things. The SCALE GATE
asks whether the target's SCALE_TYP can hold the values the warehouse observed,
and runs on LOINC only, for the reason THE GATE IS ASYMMETRIC gives. The INTENT
GATE asks whether a label naming a goal, a setting or an ordered value reached a
target that says so, and runs on BOTH — a `Goal <X>` column mapped to plain `<X>`
records an intention as a measurement, and two of the four rows it catches are
SNOMED. See THE INTENT GATE above the constants.

THE REPLAY (`--replay`) re-decides the committed table under the current gates
instead of searching again, and exists because the two halves of this script age
at different rates. The search is expensive, non-deterministic and cached
somewhere else; the gates are pure functions of what the search already returned,
and every input they need — both passes, their targets, displays, confidences and
statuses, the observed shape and the LOINC SCALE_TYP — is a column in the
committed file. Changing a gate therefore does not need 2,766 LLM calls to find
out what it did, and after a cache reset that is the difference between a minute
and a full re-run whose answers may not even reproduce.

It is NOT a substitute for a full run, and the boundary is exactly the sentence
sent: a new constraint, template, threshold or pre-filter changes what was ASKED,
so nothing in the file answers the new question and replaying it would launder
stale answers into a file that looks freshly built. `run_mode` in the log records
which of the two wrote it, for that reason.

One thing a replay genuinely cannot read off the file. THE RESOLUTION RULE asks
SNOMED only where LOINC produced no usable target, so a row LOINC won has an
EMPTY SNOMED block — an absence, not a recorded decline. A gate that rejects that
LOINC answer makes the SNOMED pass relevant for the first time, and declining the
row without it would rest the decline on a search nobody ran. So the replay makes
exactly those calls and reports how many.

EQUIVALENCE is not this script's concern. Every mapping a table supplies is
`relatedto`, set by lib/assemble.py when it builds the group — including across
both systems, since the resolver and not the row decides it.

Why it is NOT part of `make mappings`: same as the six generators before it. It
needs the network and an LLM-backed service, and it WRITES a build input.
Determinism lives in the split — this runs by hand, its output is committed, and
`make mappings` reads the committed CSV and never a server.

    make chartevents-table ARGS=--insecure

Usage:
  uv run scripts/terminology-mapping/conceptmaps/build_chartevents_table.py
  uv run .../build_chartevents_table.py --only 220045,224093 --insecure
"""

import argparse
import concurrent.futures
import csv
import gzip
# NOT `import http.client`: the fhirclient import below binds the name `http` to
# a function, so `HTTPException` in find_code's except clause would raise
# AttributeError instead of retrying — silently defeating the retry loop on
# exactly the transport failures it exists to absorb.
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
# The module, not `from ... import SSL_CONTEXT`: configure_tls() REBINDS that
# global, so a name bound at import time would still be the pre-configuration
# context and --ca-bundle would be silently ignored.
from common import fhirclient  # noqa: E402
from conceptmaps.lib.canonical import LOINC, SNOMED  # noqa: E402
from conceptmaps.lib.curated import (curated_columns,  # noqa: E402
                                     MIXED_TARGET_COLUMNS)
from conceptmaps.lib.igsource import source_concepts  # noqa: E402
from verify.verify_curated_snomed import INTL_MODULE, lookup  # noqa: E402

# --------------------------------------------------------------------------- #
# The stated rules
# --------------------------------------------------------------------------- #

# LOINC's Laboratory, Clinical AND Survey class types, active codes only.
#
# THREE classes, because this population spans all three: `category = Labs` is
# 160 bedside analytes whose targets are CLASSTYPE=1 only, the vital signs and
# assessments are CLASSTYPE=2, and the nursing assessment instruments are
# CLASSTYPE=4. See THE LOINC CONSTRAINT IS THE UNION in the module docstring for
# the two-disjoint-passes alternative that was probed, why the merge failure it
# rested on does not reproduce on this deployment, and the evidence for adding
# Survey.
#
# The 1|2 pool was measured at 85,008 of LOINC's 247,255 (60,009 + 24,999, which
# $expand confirmed sum exactly, so neither class is silently dropped by the
# regex form). What Survey adds has NOT been measured on the generating
# deployment — tx.fhir.org will not honour a CLASSTYPE filter, and no number is
# asserted here that this repo cannot show its working for. The generation log
# records the constraint verbatim, so the count is derivable from any run.
CONSTRAINT_VCL = '(http://loinc.org)(CLASSTYPE/"1|2|4",STATUS=ACTIVE)'

# SNOMED CT observable entities, and deliberately NOT the procedure/finding/event
# union the two ICU procedure streams use. A finding belongs in
# Observation.value, not Observation.code, and widening was measured turning a
# correct decline into `3424008 |Tachycardia|` for a monitor alarm LIMIT. See
# THE SNOMED CONSTRAINT in the module docstring.
CONSTRAINT_ECL = "<<363787002"

# The identity wrapper: the label is sent exactly as the dictionary spells it,
# minus any instance index. Kept as a named constant so the log records what was
# sent, and because a future stream reading this one should see that "no
# template" was a decision with evidence behind it rather than an omission — see
# TEMPLATE IS THE IDENTITY WRAPPER for the category-injected variant that was
# probed and rejected for manufacturing an APACHE IV score out of thin air.
TEMPLATE = "{}"

# Below this, code-search's answer is discarded and the pass is treated as
# having declined. Matches the six generators before it. The distribution is
# printed at the end of every run so it can be moved with evidence rather than
# by taste. Note the comparison is `>=` here as everywhere else in this repo: a
# proposal landing exactly on the threshold is accepted, and two junk answers
# were observed doing precisely that — which is what the category pre-filter
# below handles, rather than giving this one stream a threshold rule that
# differs from the other six.
CONFIDENCE_THRESHOLD = 0.8

# MIMIC's instance index: `Impaired Skin Site #1`, `Angio Site # 2`,
# `CT #1 Suction Amount`. Stripped before searching so an item family asks one
# question, and the answer is fanned back across every member. A regex applied
# to every label, so it is a stated rule and not a per-item judgement.
INSTANCE_INDEX_RE = re.compile(r"#\s*\d+")

# Categories whose every member is a documentation slot or a device setting
# rather than an observation of the patient. Declined WITHOUT being searched,
# because both were measured answering confidently and wrongly on the bare label
# with the constraints above. See BOTH PRE-SEARCH DECLINES for the evidence and
# for why these two and not the other ~360 non-observation items.
DECLINED_CATEGORIES = {
    "Care Plans": ("every item is a `<X> NCP - {Goal | Expected outcomes | "
                   "Outcomes met | Interventions}` nursing-care-plan "
                   "documentation slot, not an observation of the patient"),
    "Alarms": ("every item is a `<X> Alarm - {High | Low}` device alarm limit, "
               "which is a monitor setting rather than a measurement of the "
               "patient"),
    "Generic Proc Note": ("every item is a procedural-workflow attestation — "
                          "`Timeout Performed By`, `Patient Identified "
                          "Correctly`, `Hand Cleansing prior to procedure` — "
                          "recording that a step of the safety checklist "
                          "happened, not an observation of the patient"),
}

# --------------------------------------------------------------------------- #
# THE SCALE GATE
# --------------------------------------------------------------------------- #
#
# The three checks in gate() below assert that a proposed target is in the
# constraint, exists, is active, and has a confirmed display. None of them can
# see the defect that actually dominates this stream: a target whose SCALE
# contradicts the data. Audited over all 848 committed LOINC mappings against
# valueshapes/observation-value-shapes.csv, 185 of them (21%, 26.3M occurrences)
# name a code whose SCALE_TYP disagrees with what MIMIC records.
#
# EVERY COUNT IN THE FOUR CLAUSES BELOW IS FROM THAT AUDIT — i.e. against the
# table as committed BEFORE this gate existed and before CONSTRAINT_VCL gained
# CLASSTYPE=4. They are what the rule was designed against, not what it did.
#
# WHAT IT ACTUALLY DID, on the first run under both changes: 111 rejections on the
# LOINC pass and 114 warnings. 27 of the 111 recovered a SNOMED target, so 84 rows
# end up unmapped with a decisive status of `scale-mismatch` — which is the number
# that reaches mapping-statistics.csv, and the reason that column and the log
# disagree by 27 is worth knowing before someone reconciles them.
#
# The design prediction was that coverage would FALL, to roughly 56.7%. It rose,
# to 57.81%, because the Survey widening landed 147 mappings while the gate
# removed 84. Those two changes were priced in one run and their effects are
# therefore entangled; see THE CACHE MAKES A CONSTRAINT CHANGE EXPENSIVE TO
# INTERPRET for what that costs.
#
# One prediction was WRONG in a way worth recording. `223907 Pupil Size Right`
# was expected to lose `8642-1 |Right pupil Diameter Auto|` and fall through to
# SNOMED `363953003 |Size of pupil|`. It did not, and it should not have: 97% of
# its value mass is `3mm`/`2mm`/`4mm`, so the numeric-as-string clause below
# classifies it WARN and keeps the target. The earlier estimate had been computed
# before that clause existed and was not revised when it was added. The clause is
# right and the prediction was stale — but `363953003` remains the better concept
# for a penlight observation, and that is now a COMMENT_OVERRIDES question rather
# than something the gate will fix.
#
# That 185 is NOT 185 bad mappings, and the difference is the whole design:
#
#   REJECT  SCALE_TYP is `Doc` or `-`                    69 rows,  5.22M occ
#           A document type or a panel. `223792 Pain Management` ->
#           `34858-1 |Pain medicine Note|`, `224101 Chest PT R/L` ->
#           `42272-5 |XR Chest PA and Lateral|` (chest physiotherapy coded as a
#           chest X-ray), `225135 Consults` -> `11488-4 |Consult note|`. A panel
#           code is a grouping code and `hasMember` is empty on every chartevents
#           Observation, so it groups nothing. Unconditional: no threshold, no
#           per-item judgement.
#
#   REJECT  SCALE_TYP=Qn but the observed domain is QUALITATIVE  18 rows, 2.82M
#           `224027 Skin Temperature` -> `60839-8` Qn, charted `Warm | Cool |
#           Hot | Cold`; `223951 Capillary Refill R` -> `44971-0 |Capillary
#           refill [Time]|` Qn, charted `Normal <3 Seconds | Abnormal >3
#           Seconds`; `224373 Sputum Amount` -> `38200-2 |Volume of Sputum|` Qn,
#           charted `Small | Moderate | Scant | Copious`. Each asserts a measured
#           number that was never measured.
#
#   WARN    SCALE_TYP=Qn but the domain is a NUMBER WEARING A UNIT  10 rows,
#           4.24M occ. `224415 ETT Mark (cm)` charts `23cm`, `22cm`;
#           `223837 ETT Size (ID)` charts `7.5mm`. The target is RIGHT and the
#           ETL is wrong — it should emit valueQuantity. Rejecting these would
#           destroy correct mappings to fix someone else's bug, so they are
#           reported and kept. NUMERIC_VALUE_RE is what tells the two apart.
#
#   WARN    a Nom/Ord target carrying numeric data  88 rows, 14.0M occ. The
#           inverse, and mostly NOT a mapping defect: `9267-6 |Glasgow coma score
#           eye opening|` is Ord and unambiguously the right code for GCS eye
#           opening; all six Braden subscales are the same. MIMIC emits `4` as a
#           Quantity where LOINC expects a coded ordinal, which is a
#           representation question. Gating these would destroy 88 correct
#           mappings, so it does not.
#
# EXPECTED EFFECT, measured before writing this: 87 rejections, 8.04M
# occurrences. Coverage GOES DOWN — 57.44% -> 56.74% by occurrence and 1217 ->
# 1153 codes, or as far as 54.87% / 1130 if none of the SNOMED fallthroughs
# survive membership. A gate removes wrong answers; it does not find right ones,
# and a stream whose coverage rose after adding one would be evidence the gate
# was not working.
#
# What it buys is that 23 of the rejections (5.86M occ) fall through to a
# MATERIALLY BETTER SNOMED target, because rejecting the LOINC answer is what
# lets the resolution rule reach one:
#
#     223907 Pupil Size Right   8642-1 |Right pupil Diameter Auto| (Qn)
#                            -> 363953003 |Size of pupil|              0.85
#     224027 Skin Temperature   60839-8 |Skin temperature| (Qn)
#                            -> 364537001 |Temperature of skin|        0.95
#     223951 Capillary Refill R 44971-0 |Capillary refill [Time]| (Qn)
#                            -> 15527001 |Capillary filling|           0.95
#
# `363953003 |Size of pupil|` is exactly the concept COMMENT_OVERRIDES below
# records as the one this stream could not reach; the scale gate reaches it
# without being told about that item.
#
# THE GATE IS ASYMMETRIC AND THAT IS A REAL COST, stated because it will not be
# visible in the statistics. SNOMED models the same fact as `370132008 |Scale
# type|`, so the check could in principle be symmetric — but it is populated on
# only 4 of the 173 distinct SNOMED concepts this table targets, 0.0% by
# occurrence. So LOINC answers are checkable and SNOMED answers are not, and
# since the resolution rule falls through to SNOMED when LOINC declines, adding
# this gate SHIFTS volume from the checkable system to the uncheckable one. The
# rejections above are still worth it — a wrong LOINC code is not improved by
# being unfalsifiable — but nobody should read the result as SNOMED having earned
# those rows on merit.
#
# The observed shape is a committed build input, not a live query: see
# valueshapes/README.md for the HPC job that produces it. Absent that file this
# gate disables itself with a warning rather than failing the build, because a
# scale check that cannot run is not the same failure as a scale check that
# fails.

# LOINC publishes SCALE_TYP on every concept; a terminology server may answer
# with either the abbreviation or the LOINC Part code that carries it, so both
# spellings are accepted. Measured against tx.fhir.org, which returns Parts.
SCALE_TYP_PARTS = {
    "LP7753-9": "Qn", "LP7750-5": "Nom", "LP7751-3": "Ord", "LP7747-1": "-",
    "LP32888-7": "Doc", "LP7752-1": "OrdQn", "LP7749-7": "Nar",
    "LP7748-9": "Multi", "LP436123-6": "SemiQn",
}

# A document type or a panel is never a legal Observation.code for a single
# flowsheet value.
SCALE_TYP_NEVER = {"Doc", "-"}

# Which SCALE_TYP values are compatible with each shape the warehouse observed.
# `SemiQn` counts as quantitative: LOINC files the blood-gas pH codes there
# (`2744-1`), and the four rows affected chart ordinary numbers.
SCALE_COMPATIBLE = {
    "Qn": {"Qn", "OrdQn", "SemiQn"},
    "NomOrd": {"Nom", "Ord", "OrdQn", "Multi", "Nar"},
    "Nar": {"Nar", "Nom", "Multi"},
}

# A value that is a number wearing a unit — `23cm`, `7.5mm`, `14 French`,
# `3mm`. An item whose value mass is mostly these is quantitative data that the
# ETL stringified, so a Qn target is correct and the defect is upstream. The
# threshold is on OCCURRENCE mass rather than on distinct values, because
# `Pupil Size Right` charts `3mm` 1418 times and `Pinpoint` 44 times and it is
# the 44 that must not decide the item's shape.
NUMERIC_VALUE_RE = re.compile(r"^[<>]?=?\s*\d+(\.\d+)?\s*[A-Za-z%/°]*\.?$")
NUMERIC_VALUE_FRACTION = 0.90

# --------------------------------------------------------------------------- #
# THE INTENT GATE
# --------------------------------------------------------------------------- #
#
# A flowsheet column can record what the patient WAS, or what someone INTENDED
# the patient to be. `223791 Pain Level` is the first; `223794 Pain Level
# Acceptable` is the second — the pain score this patient has agreed is tolerable
# — and they are different facts about different things. Dropping the modifier
# turns a care target into a measurement, and a consumer summing Observation.code
# cannot tell that it happened, because the code it reads is a perfectly ordinary
# one that simply is not what the row means.
#
# Left unchecked, the two searches did drop it, and at volume:
#
#   223794 Pain Level Acceptable        -> 106724-8   |Pain level|            972K
#   228299 Goal Richmond-RAS Scale      -> 1345050000 |RASS score|            916K
#   224688 Respiratory Rate (Set)       -> 9279-1     |Respiratory rate|      342K
#   229742 Activity/Mobility (RN Daily Mobility Goal) -> 363803005 |Mobility|   4K
#
# This is the failure the outputevents TOTAL_CODES list and the datetimeevents
# DEVICE_CARE_CODES list exist to stop, met a third time: a target that is right
# about the analyte and wrong about what the column is FOR. Unlike those two it
# needs no list of target codes, because the tell is on the SOURCE side and the
# check is an agreement between the two — which is why it is a gate here rather
# than a reject list.
#
# THE RULE. If the MIMIC label carries an intent word and the target's server-
# confirmed display carries none, the answer is declined `intent-dropped`. Both
# halves matter: the modifier must be present in the label to arm the check, and
# the check passes as soon as the target says the same thing in any of the words
# a terminology uses for it. Applied to BOTH systems, unlike the scale gate — two
# of the four rows above are SNOMED, and a LOINC-only check would have caught
# half the defect while reporting it as handled.
#
# It DECLINES, it does not rescue. `224688 Respiratory Rate (Set)` has a correct
# target — `33438-3 |Breath rate mechanical --on ventilator|` — and this gate
# will not go and get it, for build_labevents_table.py's reason: a generator that
# hand-picks a replacement when it dislikes an answer is curating against known
# rows, and the row is more useful declined with its proposal recorded than
# mapped to a code no rule produced.
#
# MEASURED over the committed table before being turned on: 51 of the 2,982
# labels arm it, 12 of those have a target, and it splits them 8 kept / 4
# declined with nothing misfiled either way. The eight it keeps are the proof it
# is an agreement check and not a blanket ban on the word — `220339 PEEP set`
# reaches `20077-4 |… setting Ventilator|` and four temporary-pacemaker rows
# reach their `… setting` codes, all of which state the modifier and all of which
# survive. The remaining 39 armed labels are already declined for other reasons,
# so the gate cannot change them.
#
# Word boundaries on both sides, so `Onset`, `Offset` and `Sunset` do not arm it
# and `Somatosensory` does not satisfy it.
INTENT_LABEL_RE = re.compile(
    r"(?<![A-Za-z])(goals?|desired|acceptable|ordered|prescribed|planned"
    r"|targets?|sett?ings?|set)(?![A-Za-z])", re.I)

# The words a terminology uses when it means the same thing. Wider than the label
# list on purpose: the label has to name the modifier MIMIC's way, and the target
# is allowed to name it any of the ways LOINC and SNOMED do.
INTENT_TARGET_RE = re.compile(
    r"(?<![A-Za-z])(sett?ings?|set|goals?|targets?|ordered|prescribed"
    r"|intended|desired|planned|reference|limit)(?![A-Za-z])", re.I)


def intent_verdict(label, display):
    """('ok', '') or ('reject', why) for one (label, target display) pair.

    Abstains — returns ok — when the label carries no intent word, which is the
    2,931 labels this check has nothing to say about.
    """
    modifier = INTENT_LABEL_RE.search(label or "")
    if not modifier:
        return "ok", ""
    if INTENT_TARGET_RE.search(display or ""):
        return "ok", ""
    return "reject", (
        f"the label carries {modifier.group(0)!r}, so the column records an "
        f"intended or set value, and the target's display states no such "
        f"modifier — mapping it here would record the intent as a measurement")

# --------------------------------------------------------------------------- #
# THE SCALE RESCUE — BUILT, MEASURED, AND REJECTED
# --------------------------------------------------------------------------- #
#
# There is no sub-threshold acceptance in this stream. A LOINC proposal below
# CONFIDENCE_THRESHOLD is discarded, as in every other generator here. This block
# records an attempt to change that, because it was implemented and run rather
# than argued about, and the numbers are the reason it is gone.
#
# THE IDEA: accept a LOINC proposal in the 0.70–0.80 band IF the scale check
# positively agrees with the observed value shape. The argument was that 0.8 is
# calibrated for `equivalent` while this table asserts `relatedto` on every row
# (fixed by lib/assemble.py), that under relatedto a target coarser than the item
# is a TRUE statement, and that coarseness is what the 0.70–0.80 band is full of —
# so a service confidence and a deterministic scale match agreeing is different
# evidence from one signal at 0.8.
#
# IT WORKED, in the sense of moving the number: 238 rows admitted, 17.5M
# occurrences, taking the stream from 58.48% to 64.04% by occurrence and from
# 1,243 to 1,481 mapped codes. It also found real things, including the defect
# NOT collapsed: LATERALITY says has no clean instrument — `224771 RLE Temp`,
# `224773 LLE Temp` and `224769 LUE Temp` all landing on the one non-lateralised
# `81673-6 |Temperature of Extremity|`, which is correct.
#
# IT WAS REJECTED ON PRECISION. 167 of the 238 sat at exactly 0.70, the floor,
# carrying 12.7M of the 17.5M — so most of the gain came from the least confident
# value the rule would accept. Inspection of both bands found roughly one in eight
# admitted rows naming the wrong concept at the right scale:
#
#     228412 Strength R Arm       -> 83174-3 |Grip strength … Dynamometer|
#     224701 PSV Level            -> 11726-7 |Circulatory system Peak systolic|
#                                    PSV here is Pressure Support Ventilation
#     224289 Arterial line Site   -> 99716-3 |Dialysis access site appearance|
#     224281 Multi Lumen Site     -> 99716-3 |Dialysis access site appearance|
#     224106 Cooling Device       -> 88668-9 |Prehospital therapeutic hypothermia|
#     223976 RUE Color            -> 39107-8 |Color of Skin|, where NOT collapsed:
#                                    LATERALITY names SNOMED `248412009 |Colour of
#                                    extremity|` as the right answer for this item
#
# Raising the floor to 0.75 was measured and does NOT fix this: it drops 167 rows
# and 12.7M occurrences while leaving a comparable error rate, because
# `Multi Lumen Site Appear` and `Cooling Device` are both 0.75 rows. It buys less
# volume at the same precision, which is the worst of the three options.
#
# So scale agreement is NECESSARY evidence and not SUFFICIENT evidence. A
# deterministic check can tell that a target is the wrong KIND of thing; it cannot
# tell that it is the wrong thing. Removing the rescue restores an invariant worth
# more than the 5.5 points it costs: every mapping in this table cleared 0.8 and
# passed the gate, with no exceptions to explain.
#
# What is NOT reverted is THE SECOND PASS below, which survives on its own terms —
# 69 of its 109 wins cleared 0.8 unaided. Its other 40 depended on this rescue and
# are now refused.
#
# Do not reintroduce this as a hand-reviewed accept list. Picking the good rows out
# of the 238 is curation against rows seen to fail, which COMMENT_OVERRIDES exists
# to forbid.

# --------------------------------------------------------------------------- #
# THE SECOND PASS
# --------------------------------------------------------------------------- #
#
# When BOTH systems answer `no-match` on the bare label, and only then, the two
# searches are retried with the item's observed value domain appended. 889 codes
# are in that state carrying 43.6M occurrences, 13.89% of the stream — the
# largest single block left.
#
# WHY IT IS SAFE HERE AND NOWHERE ELSE. Sending the value domain as part of every
# query was tried as a template (T3) and REJECTED: over the item set TEMPLATE IS
# THE IDENTITY WRAPPER describes, it fixed real defects but displaced two correct
# controls — `224093 Position` moved off `397155001 |Body position|` and
# `224082 Turn` off `282984004 |Ability to turn|` — and compressed confidences
# toward 0.85, flattening the signal a reviewer triages on. That is the same
# failure T1 and T2 were rejected for.
#
# A row where both systems returned no-match HAS NO TARGET TO DISPLACE. The
# entire objection to T3 was collateral damage, so restricting it to this bucket
# removes the objection rather than arguing with it. The worst case is an
# additional wrong mapping where there was previously nothing, which the
# constraint, the threshold and the scale gate all still stand in the way of.
#
# MEASURED on the labels in this bucket: `224650 Ectopy Type 1` — 5.27M
# occurrences and the second-largest unmapped item in the stream — goes from
# no-match in both systems to `76281-5 |Type of arrhythmia on EKG|` at 0.85 once
# its domain (`None`, `PVC's`, `PAC's`, `Vent. Bigeminy`) is sent.
# `226732 O2 Delivery Device(s)` reaches `107117-4 |Method of oxygen delivery|`
# at 0.75, the right concept, which the scale rescue above may now admit.
#
# The augmented text is recorded in `codesearch_query_2` so that a row mapped by
# this pass is distinguishable from one mapped on the bare label — they are
# different claims and should not be read as the same one.
#
# WHAT IT ACTUALLY DID on the first run: fired on 365 rows (the 889 minus those
# with no string domain to send), mapped 109 of them — 95 LOINC, 14 SNOMED —
# carrying 8.2M occurrences. `226732 O2 Delivery Device(s)` landed
# `107117-4 |Method of oxygen delivery|` at 0.85 as predicted.
#
# THE PREDICTED HEADLINE WIN DID NOT LAND, and the likely reason is a defect in
# this design rather than variance. `224650 Ectopy Type 1` — 5.27M occurrences,
# the largest item in the bucket — was expected to reach
# `76281-5 |Type of arrhythmia on EKG|` at 0.85, measured in a probe. On the real
# run it came back LOINC no-match. The probe and the run do not send the same
# string:
#
#     probe  Ectopy Type 1 (recorded values: Atrial Bigeminy, Nod/Junc Escape,
#            Nodal Bigeminy, None, PAC's, PVC's, Vent. Bigeminy, ...)
#     run    Ectopy Type (recorded values: None, PVC's, PAC's, Vent. Bigeminy,
#            Atrial Bigeminy, ...)
#
# Two differences, and the second is the suspect. The label loses its instance
# index to the collapse, which is correct. But the values are FREQUENCY RANKED,
# and the modal value of a nursing flowsheet field is very often a sentinel —
# `None`, `Not applicable`, `---`, `Other`. Ranking by occurrence therefore leads
# the list with the one value that carries no clinical content, and buries the
# ones that say what the field is. The probe's alphabetical order happened to put
# `Atrial Bigeminy` first and answered; the run's frequency order puts `None`
# first and did not.
#
# Frequency ranking is right for the SCALE gate, where occurrence mass is exactly
# the question. It looks actively wrong for the QUERY. The untested fix is to drop
# sentinel values from the augmentation, or to send informative values first; both
# are single-line changes and neither has been measured, so the ranking is left as
# it is rather than swapped on a hunch. This is the next thing to probe.
SECOND_PASS_VALUES = 12

# An alarm limit does not stop being an alarm limit because the dictionary filed
# it under the device rather than under `Alarms`. 17 items match this outside the
# three categories above — the Centrimag, ECMO, HeartWare, VAD and IABP flow and
# pressure alarms — and the category filter alone reaches none of them.
#
# This is the category rule's OWN rationale, applied where the categorisation
# does not reach, and not a new judgement: `229847 SvO2 Alarm (Lo) (CH)` was
# measured mapping to `19224-5 |Mixed venous oxygen saturation|` and
# `229258 Flow Alarm (Lo) (LVAD)` to `444479000 |Flow rate|`, i.e. a threshold
# SETTING coded as the measurement it is a threshold for — exactly what the
# `Alarms` category is pre-filtered to prevent. The other 15 declined on the
# constraint anyway, so the rule mostly confirms what the search already does;
# it is here because "mostly" is not a property a committed table should rest
# on.
ALARM_LABEL_RE = re.compile(r"\bAlarms?\b", re.IGNORECASE)

# --------------------------------------------------------------------------- #
# Paths and provenance
# --------------------------------------------------------------------------- #

TERM = Path(__file__).resolve().parents[1]
# `-standard`, not `-loinc` or `-snomed`: this table names its target system per
# row. lib/stats.py derives the log name by dropping that last token, which is
# why the two have to stay in step.
OUT_CSV = Path(__file__).resolve().parent / "chartevents-standard.csv"
LOG_JSON = TERM / "output" / "chartevents-generation-log.json"

# MIMIC-IV demo 2.2, the openly downloadable release that ships the ICU
# dictionary whole (4,014 rows, not a subset). Read for `category` only — for
# the pre-filter, not for the query, since the template sends the bare label.
# The build never reads it at all; the committed CSV is what keeps `make
# mappings` offline.
D_ITEMS_GZ = TERM / "sources" / "mimic-iv-demo" / "2.2" / "icu" / "d_items.csv.gz"

# What the FULL warehouse records next to each Observation.code — the observed
# shape the scale gate compares LOINC's SCALE_TYP against. Committed build
# inputs from one HPC run, exactly like occurrences/code-occurrences.csv; see
# valueshapes/README.md.
VALUE_SHAPES_CSV = TERM / "valueshapes" / "observation-value-shapes.csv"
VALUE_DOMAINS_CSV = TERM / "valueshapes" / "observation-value-domains.csv"
CHART_SYSTEM = ("http://mimic.mit.edu/fhir/mimic/CodeSystem/"
                "mimic-chartevents-d-items")

TARGET_COLUMNS = MIXED_TARGET_COLUMNS
CURATED = curated_columns(TARGET_COLUMNS)

# What the service proposed, on every row it was asked about, including the rows
# where the proposal was then rejected — so that "this item is unmapped" is
# auditable from the committed diff alone.
#
# Three blocks. The unprefixed `codesearch_*` five mirror the DECISIVE pass, and
# keep those exact names because lib/stats.py reads `codesearch_status` and
# `codesearch_confidence` to build the per-stream statistics and the
# near-threshold view. The `codesearch_loinc_*` and `codesearch_snomed_*` blocks
# record each pass in its own right, which is what makes "why did this row get a
# SNOMED code rather than a LOINC one" answerable from the CSV — the question a
# mixed-target table exists to invite and therefore has to answer.
#
# A blank `codesearch_snomed_*` block means the SNOMED pass was NEVER RUN because
# LOINC already answered, which is a different fact from its having declined, and
# the resolution rule makes it the common case.
PROVENANCE_COLUMNS = [
    "codesearch_query",
    # The augmented text, present only on rows the SECOND PASS was run for. Blank
    # therefore means "the bare label was enough, or a candidate was found and no
    # retry was warranted" — and a row mapped from this column is a different
    # claim from one mapped on the bare label.
    "codesearch_query_2",
    "codesearch_target", "codesearch_display", "codesearch_confidence",
    "codesearch_status", "codesearch_reasoning",
    "codesearch_loinc_status", "codesearch_loinc_target",
    "codesearch_loinc_display", "codesearch_loinc_confidence",
    "codesearch_snomed_status", "codesearch_snomed_target",
    "codesearch_snomed_display", "codesearch_snomed_confidence",
    # The scale gate's three inputs and its finding, recorded on EVERY row the
    # LOINC pass reached a gate on — including the rows it passed. A gate whose
    # verdict is only visible when it fires cannot be audited from the committed
    # diff, and "this row was checked and agreed" is the fact that makes the
    # 489 agreeing mappings evidence rather than absence of evidence.
    "observed_shape", "loinc_scale_typ", "scale_note",
]

# Recorded per row in the log only. `path` (cached / fast / agentic) says how
# this run fetched an answer, not anything about the answer, so it would show up
# as a wall of changed rows in a diff where no mapping moved.
LOG_ONLY_COLUMNS = ["path"]

# --------------------------------------------------------------------------- #
# Sources
# --------------------------------------------------------------------------- #


def ig_codes():
    """(code, display) for the 2,982 items, read from the IG's own CodeSystem.

    Routed through the observation builder's own SOURCES declaration for the
    reason the six generators before it give: lib.curated.load_table rejects a
    row whose display differs from the IG's by so much as a character, so the
    generator and the build must read displays through the same function or the
    table this writes can fail the build that reads it.
    """
    from conceptmaps.build_observation_cm_vs import SOURCES

    source = next(s for s in SOURCES if s.get("table") == OUT_CSV)
    return dict(source_concepts(source))


def dictionary(expected):
    """itemid -> d_items row, checked against the IG enumeration.

    A missing itemid is fatal and so is a label difference, with no exceptions —
    build_labevents_table.py has to carve out five blank-label rows, and this
    dictionary and this IG agree on all 2,982 exactly, so there is nothing to
    excuse and any future difference is real drift.

    An item relabelled upstream is precisely the one whose mapping a human
    should read again; this is the same check, for the same reason, that
    load_table makes on the committed table.
    """
    if not D_ITEMS_GZ.is_file():
        sys.exit(f"  {D_ITEMS_GZ} not found. It carries the `category` column "
                 f"the pre-filter reads — without it the 216 documentation, "
                 f"attestation and alarm-limit items would be searched, and "
                 f"those were measured answering above threshold and wrongly. "
                 f"Download MIMIC-IV "
                 f"demo 2.2 (no credentialing needed):\n"
                 f"    https://physionet.org/files/mimic-iv-demo/2.2/icu/d_items.csv.gz")

    rows = {}
    with gzip.open(D_ITEMS_GZ, "rt", newline="") as fh:
        for row in csv.DictReader(fh):
            if row["itemid"] in expected:
                rows[row["itemid"]] = row

    missing = sorted(set(expected) - set(rows))
    if missing:
        sys.exit(f"  {len(missing)} IG code(s) are not in {D_ITEMS_GZ.name}: "
                 f"{missing[:8]}. The IG and the dictionary are different MIMIC "
                 f"releases — re-check which before generating a table from "
                 f"them.")

    drifted = [(code, expected[code], rows[code]["label"])
               for code in sorted(expected)
               if rows[code]["label"] != expected[code]]
    if drifted:
        for code, ig_label, dict_label in drifted:
            print(f"    {code} IG {ig_label!r} vs dictionary {dict_label!r}",
                  file=sys.stderr)
        sys.exit(f"  {len(drifted)} label(s) differ between the IG and "
                 f"{D_ITEMS_GZ.name}. An item that was relabelled upstream is "
                 f"one whose mapping should be re-read, not one to generate "
                 f"around.")
    return rows


def observed_shapes():
    """mimic_code -> ('Qn'|'NomOrd'|'Nar'|'', numeric_value_fraction).

    Read from the two committed valueshapes CSVs. Returns {} with a warning if
    they are absent: a scale check that cannot run is a weaker build, not a
    broken one, and requiring the files would make this generator unrunnable for
    anyone who has not fetched them.

    The numeric fraction is computed over the value domain's OCCURRENCE mass, so
    it says "this item is numbers wearing units" rather than "this item has some
    values that look numeric" — see NUMERIC_VALUE_RE.
    """
    if not VALUE_SHAPES_CSV.is_file():
        print(f"  WARNING: {VALUE_SHAPES_CSV.name} not found — the scale gate "
              f"is DISABLED for this run. 87 mapping(s) that contradict the "
              f"observed value shape will be accepted. Fetch it per "
              f"valueshapes/README.md.", file=sys.stderr)
        return {}

    hints = {}
    with open(VALUE_SHAPES_CSV, newline="") as fh:
        for row in csv.DictReader(fh):
            if row["system"] == CHART_SYSTEM:
                hints[row["code"]] = row["scale_hint"]

    mass, numeric, values = {}, {}, {}
    if VALUE_DOMAINS_CSV.is_file():
        with open(VALUE_DOMAINS_CSV, newline="") as fh:
            for row in csv.DictReader(fh):
                if row["system"] != CHART_SYSTEM:
                    continue
                count = int(row["occurrences"])
                code = row["code"]
                mass[code] = mass.get(code, 0) + count
                if NUMERIC_VALUE_RE.match(row["value"].strip()):
                    numeric[code] = numeric.get(code, 0) + count
                # (rank, value) so the frequency order the HPC job established
                # survives being read back, rather than being re-sorted here.
                values.setdefault(code, []).append((int(row["rank"]),
                                                    row["value"]))

    return {code: {"hint": hint,
                   "numeric": numeric.get(code, 0),
                   "mass": mass.get(code, 0),
                   "values": [v for _, v in sorted(values.get(code, []))]}
            for code, hint in hints.items()}


def query_shape(codes, shapes):
    """The observed shape for one COLLAPSED LABEL, over every itemid sharing it.

    The gate runs per query, not per item, because search_query does — so the
    members' shapes have to be reconciled into one. Members that DISAGREE yield
    a blank hint, which makes the gate abstain: the same rule the label collapse
    applies everywhere else, that a family which cannot agree is not a family a
    machine should decide for.

    The numeric fraction is summed over the members' occurrence mass rather than
    averaged over the members, so `Impaired Skin Site #1` charted 90,000 times
    is not outvoted by `#10` charted twice.
    """
    seen = [shapes[c] for c in codes if c in shapes]
    hints = {s["hint"] for s in seen if s["hint"]}
    mass = sum(s["mass"] for s in seen)
    numeric = sum(s["numeric"] for s in seen)
    # The value domain for the second pass: the members' domains merged and
    # re-ranked by the occurrence mass each value actually carries, so a family
    # asks about the values its patients were charted rather than about whichever
    # member the dictionary happens to list first.
    pooled = {}
    for s in seen:
        for rank, value in enumerate(s["values"]):
            # No per-value counts survive into the shapes dict, so members are
            # merged on rank — worse than merging on count, and the reason the
            # single-member case (which is most of them) is exact and the
            # multi-member case is only approximately frequency-ordered.
            pooled[value] = min(pooled.get(value, 10 ** 6), rank)
    return {"hint": hints.pop() if len(hints) == 1 else "",
            "numeric_fraction": (numeric / mass) if mass else 0.0,
            "members_observed": len(seen),
            "values": [v for v, _ in sorted(pooled.items(),
                                            key=lambda kv: (kv[1], kv[0]))]}


def scale_verdict(scale_typ, hint, numeric_fraction):
    """('ok'|'reject'|'warn', why) for one (SCALE_TYP, observed shape) pair.

    The stated rule, applied identically to every row — see THE SCALE GATE.
    Split out from gate() so it is testable without a terminology server, and so
    the WARN cases can be reported without being silently dropped.
    """
    if scale_typ is None:
        return "ok", "SCALE_TYP not published by the server"
    if scale_typ in SCALE_TYP_NEVER:
        kind = ("a document type" if scale_typ == "Doc" else "a panel")
        return "reject", (f"LOINC SCALE_TYP={scale_typ}, i.e. {kind}, which is "
                          f"not a legal Observation.code for a single flowsheet "
                          f"value")
    if not hint:
        return "ok", "no usable observed shape (mixed, unused, or absent)"
    if scale_typ in SCALE_COMPATIBLE[hint]:
        return "ok", ""
    if hint == "NomOrd" and scale_typ in ("Qn", "SemiQn"):
        if numeric_fraction >= NUMERIC_VALUE_FRACTION:
            return "warn", (f"LOINC SCALE_TYP={scale_typ} but MIMIC records "
                            f"strings; {numeric_fraction:.0%} of the value mass "
                            f"is a number wearing a unit, so the target is right "
                            f"and the ETL should emit valueQuantity")
        return "reject", (f"LOINC SCALE_TYP={scale_typ} but MIMIC records a "
                          f"qualitative domain ({numeric_fraction:.0%} of the "
                          f"value mass is numeric), so this target asserts a "
                          f"measurement that was never made")
    return "warn", (f"LOINC SCALE_TYP={scale_typ} but MIMIC records "
                    f"{hint} data — a representation mismatch rather than a "
                    f"wrong target")


def collapsed(label):
    """The label with its instance index stripped — what actually gets searched.

    `Impaired Skin Site #1` -> `Impaired Skin Site`
    `Angio Site # 2`        -> `Angio Site`
    `Impaired Skin #1- Location` -> `Impaired Skin - Location`

    Trailing separators left by the strip are cleaned up so the sent string
    reads as a label rather than as the residue of one.
    """
    stripped = INSTANCE_INDEX_RE.sub("", label)
    return re.sub(r"\s{2,}", " ", stripped).strip().strip("-").strip()


def searchable(item):
    """(True, '') if this item should be asked about, else (False, reason).

    Two declines, both read off the dictionary and applied to every item
    identically — one on `category`, one on the label. See THE PRE-SEARCH
    DECLINES in the module docstring.
    """
    why_not = DECLINED_CATEGORIES.get(item["category"])
    if why_not:
        return False, why_not
    if ALARM_LABEL_RE.search(item["label"]):
        return False, ("its label names an alarm, so it is a device alarm "
                       "limit — a monitor setting rather than a measurement of "
                       "the patient — whatever category the dictionary files "
                       "it under")
    if not collapsed(item["label"]):
        # No label survives the index strip, so there is no question to ask.
        # Not observed in the current dictionary; here because a label of `#1`
        # alone would otherwise be sent as the empty string.
        return False, "the dictionary records no label for it beyond an index"
    return True, ""


# --------------------------------------------------------------------------- #
# The two searches
# --------------------------------------------------------------------------- #


def loinc_constraint_url():
    """CONSTRAINT_VCL as a resolvable implicit-ValueSet canonical."""
    return "http://fhir.org/VCL?v1=" + urllib.parse.quote(CONSTRAINT_VCL,
                                                          safe="")


def snomed_constraint_url():
    """CONSTRAINT_ECL as a resolvable implicit-ValueSet canonical."""
    return (f"{SNOMED}?fhir_vs=ecl/"
            + urllib.parse.quote(CONSTRAINT_ECL, safe=""))


def constraint_url(system):
    return (loinc_constraint_url() if system == LOINC
            else snomed_constraint_url())


def constraint_text(system):
    """The constraint as written in this file, for a comment or a log line."""
    return CONSTRAINT_VCL if system == LOINC else CONSTRAINT_ECL


def service_info(service):
    """code-search's self-reported configuration, or None if it won't say.

    Recorded in the log because table generation is the one stage whose output
    is not a pure function of this repo: the settings above were tuned against a
    particular deployment and model, and this is what makes that checkable later
    rather than remembered.
    """
    try:
        with urllib.request.urlopen(
                f"{service.rstrip('/')}/api/v1/info", timeout=30,
                context=fhirclient.SSL_CONTEXT) as response:
            return json.load(response)
    except Exception:                                 # noqa: BLE001
        return None


def find_code(service, text, system, timeout, attempts=4):
    """code-search's best match for `text` within `system`'s constraint.

    Retries transport failures, for the reason the generators before it give: a
    dropped connection is not an answer, and a run that quietly mixes 'no match'
    with 'the service was not running' produces a table that understates
    coverage and reads exactly like a real result. Exhausted retries raise, and
    main() refuses to write the CSV.
    """
    body = json.dumps({
        "text": text,
        "url": constraint_url(system),
        "system": system,
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
# The validation gates, one per system
# --------------------------------------------------------------------------- #


def in_constraint(fhir_base, system, code):
    """True if `code` is a member of `system`'s constraint, per the server.

    Asserted rather than assumed. code-search was asked to honour the constraint
    and demonstrably does — the LOINC Parts and SNOMED physical objects that
    dominate the unconstrained answers never appear here — but 'the service was
    asked nicely' is not a property a committed table should rest on.
    """
    query = urllib.parse.urlencode({
        "url": constraint_url(system), "system": system, "code": code})
    status, body = http(
        "GET", f"{fhir_base.rstrip('/')}/ValueSet/$validate-code?{query}")
    if status != 200 or not body:
        return False
    return any(p["name"] == "result" and p.get("valueBoolean")
               for p in body.get("parameter", []))


def preferred_display(fhir_base, system, code):
    """The concept's display on this server, or None if absent.

    The server's own string — LOINC's LONG_COMMON_NAME, SNOMED's preferred term
    — and not whatever display code-search carried next to the code, which is
    what keeps a display in the committed table a real designation of its
    concept by construction.
    """
    query = urllib.parse.urlencode({"system": system, "code": code})
    status, body = http(
        "GET", f"{fhir_base.rstrip('/')}/CodeSystem/$lookup?{query}")
    if status != 200 or not body or body.get("resourceType") != "Parameters":
        return None
    for parameter in body.get("parameter", []):
        if parameter["name"] == "display":
            return parameter["valueString"]
    return None


def loinc_scale_typ(fhir_base, code):
    """LOINC's SCALE_TYP for `code`, normalised to its abbreviation.

    None means the server did not publish it, which the scale rule treats as
    "cannot check" rather than "incompatible" — the same posture the rest of this
    file takes toward a question the server declines to answer.
    """
    query = urllib.parse.urlencode({"system": LOINC, "code": code,
                                    "property": "SCALE_TYP"})
    status, body = http(
        "GET", f"{fhir_base.rstrip('/')}/CodeSystem/$lookup?{query}")
    if status != 200 or not body:
        return None
    for parameter in body.get("parameter", []):
        if parameter["name"] != "property":
            continue
        key = value = None
        for part in parameter.get("part", []):
            if part["name"] == "code":
                key = part.get("valueCode")
            elif part["name"].startswith("value"):
                value = (part.get("valueString") or part.get("valueCode")
                         or (part.get("valueCoding") or {}).get("code"))
        if key == "SCALE_TYP" and value:
            return SCALE_TYP_PARTS.get(value, value)
    return None


def gate(fhir_base, system, code):
    """('ok', display) if `code` is usable, else (reason, None).

    Used as a filter rather than an assertion: a target that fails here is
    treated exactly as an absent one and the pass counts as having declined.

    Per system, because the two terminologies fail differently. SNOMED gets the
    three checks verify_curated_snomed.py enforces on top of membership —
    exists, active, international core rather than a national extension — and an
    extension concept in particular resolves on the server it was authored
    against and nowhere else, which is invisible by reading a CSV and would
    survive the build. LOINC needs neither: STATUS=ACTIVE is carried by the
    constraint itself, and LOINC has no national extensions.
    """
    if not in_constraint(fhir_base, system, code):
        return "out-of-constraint", None
    if system == SNOMED:
        result = lookup(fhir_base, code)
        if result is None:
            return "absent", None
        active, module, names = result
        if not active:
            return "retired", None
        if module != INTL_MODULE:
            return "extension", None
        display = preferred_display(fhir_base, SNOMED, code)
        if not display or display not in names:
            return "no-display", None
        return "ok", display
    display = preferred_display(fhir_base, system, code)
    if not display:
        return "absent", None
    return "ok", display


# --------------------------------------------------------------------------- #
# Reviewed comments
# --------------------------------------------------------------------------- #


# Prose notes on individual mappings, keyed on (mimic_code, target_code).
#
# NOT equivalence — every mapping this table supplies is `relatedto`, fixed by
# lib/assemble.py. Keyed on the PAIR, and fatal when an entry matches no row,
# for the reasons build_d_items_table.py sets out: the note was written about
# one specific target concept, and a silent miss means a human's reading of a
# row quietly evaporates.
#
# Comments only — this mechanism deliberately cannot pin a target code OR a
# target system. The moment it can, it becomes a way to hand-write mappings that
# bypass CONFIDENCE_THRESHOLD, the gate and the LOINC-before-SNOMED resolution
# rule, and the table stops being 'what the service returned, gated'. The
# restriction bites harder on a mixed-target table than on any before it,
# because "this row should have gone to the other system" is exactly the
# override a reader will want to write.
#
# Empty because no row of this table has been reviewed yet: the first run of
# this script is the dry run whose output decides which rows need a note. One
# candidate is already known from the probes — `223907 Pupil Size Right`, where
# the constrained LOINC search reaches the automated-pupillometer variant
# (`8642-1`) although MIMIC's nurses chart pupil size by penlight, and SNOMED's
# `363953003 |Size of pupil|` carries no laterality at all. There is no good
# answer in either system, so it is a comment rather than a different target.
COMMENT_OVERRIDES = {}


def apply_comments(rows):
    """Attach the reviewed comments to their rows. Fatal on drift."""
    by_pair = {(r["mimic_code"], r["target_code"]): r
               for r in rows if r["target_code"]}
    for (code, target), comment in sorted(COMMENT_OVERRIDES.items()):
        row = by_pair.get((code, target))
        if row is None:
            current = next((r for r in rows if r["mimic_code"] == code), None)
            now = ("is no longer in the IG" if current is None else
                   f"now targets {current['target_code'] or '(unmapped)'}")
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
        f"Not sent to code-search: {why_not}. An answer here would be the "
        f"service coding a string MIMIC does not stand behind.")
    return row


def one_pass(service, fhir_base, text, system, timeout, shape=None, label=None):
    """Run one system's search and gate it. Returns a dict describing the pass.

    `code` and `display` are set only when the pass produced a usable target;
    `status` says what happened either way, and `target`/`confidence` keep the
    proposal even where it was then rejected.

    `shape` is the observed value shape for this query, from query_shape(). It is
    consulted only on the LOINC pass, because SNOMED publishes `370132008 |Scale
    type|` on 4 of the 173 concepts this table targets and a check that can
    answer for 2% of rows is not a check — see THE GATE IS ASYMMETRIC.

    `label` is the bare MIMIC label, passed separately from `text` because the
    SECOND PASS appends the value domain to the text and the intent gate must
    read the modifier off what MIMIC wrote, not off what this script appended.
    """
    result = {"status": "", "target": "", "display": "", "confidence": "",
              "reasoning": "", "path": "", "code": "", "preferred": "",
              "scale_typ": "", "scale_note": "", "intent_note": ""}
    try:
        answer = find_code(service, text, system, timeout)
    except Exception as exc:                          # noqa: BLE001
        result["status"] = f"error: {str(exc)[:80]}"
        return result

    result["path"] = answer.get("path", "")
    matches = answer.get("matches") or []
    if not matches:
        result["status"] = "no-match"
        return result

    match = matches[0]
    confidence = float(match.get("confidence") or 0.0)
    result["confidence"] = f"{confidence:.2f}"
    result["reasoning"] = (match.get("reasoning") or "").strip()
    result["target"] = match["code"]
    result["display"] = match.get("display", "")
    # No exceptions: a sub-threshold proposal is discarded unread, in this stream
    # as in every other generator here. A scale-agreement carve-out for the
    # 0.70–0.80 band was built, run and rejected on precision — see THE SCALE
    # RESCUE for the numbers, so that it is not proposed again as if untried.
    if confidence < CONFIDENCE_THRESHOLD:
        result["status"] = "below-threshold"
        return result

    status, display = gate(fhir_base, system, match["code"])
    result["status"] = status
    if status != "ok":
        return result

    # The intent gate runs on the SERVER-CONFIRMED display rather than on the
    # service's `display`, for the same reason the scale gate runs after
    # membership: the proposal's own display is whatever the service echoed back,
    # and a check on the modifier has to read the terminology's own words. Both
    # systems, unlike the scale gate below — see THE INTENT GATE.
    verdict, why = intent_verdict(label if label is not None else text, display)
    if verdict == "reject":
        result["intent_note"] = why
        result["status"] = "intent-dropped"
        return result

    # The scale gate runs LAST, after membership: a code that is not in the
    # constraint has already failed for a more basic reason, and asking the
    # server for its SCALE_TYP would be a request whose answer cannot matter.
    if system == LOINC and shape is not None:
        scale_typ = loinc_scale_typ(fhir_base, match["code"])
        result["scale_typ"] = scale_typ or ""
        verdict, why = scale_verdict(scale_typ, shape["hint"],
                                     shape["numeric_fraction"])
        # Only a WARN or a REJECT gets a note. scale_verdict explains its `ok`
        # cases too, which is useful at a prompt and misleading in a column: the
        # report counts warnings by the presence of this field, and an `ok` row
        # carrying "no usable observed shape" would be tallied as a defect.
        # `loinc_scale_typ` plus `observed_shape` already say a row was checked.
        result["scale_note"] = why if verdict != "ok" else ""
        if verdict == "reject":
            result["status"] = "scale-mismatch"
            return result

    result["code"] = match["code"]
    result["preferred"] = display
    return result


def search_query(label, fhir_base, service, timeout, shape=None):
    """The two passes for one collapsed label, resolved into one answer.

    LOINC first; SNOMED only where LOINC did not produce a usable target. See
    THE RESOLUTION RULE in the module docstring for why that order and why the
    two are not compared on confidence.

    Returns the fields to copy onto every itemid sharing the label, so that
    items differing only by an instance index cannot end up on different
    targets.
    """
    text = TEMPLATE.format(label)
    # The TARGET columns and `comment` only — NOT the whole of CURATED. What
    # this returns is fanned onto every itemid sharing the label with .update(),
    # so seeding it with `mimic_code` / `mimic_display` would blank the source
    # side of every row it touched.
    answer = {c: "" for c in PROVENANCE_COLUMNS + LOG_ONLY_COLUMNS
              + list(TARGET_COLUMNS) + ["comment"]}
    answer["codesearch_query"] = text

    loinc = one_pass(service, fhir_base, text, LOINC, timeout, shape, label)
    _record(answer, "loinc", loinc)
    answer["observed_shape"] = (shape or {}).get("hint", "")
    answer["loinc_scale_typ"] = loinc["scale_typ"]
    answer["scale_note"] = loinc["scale_note"]
    if loinc["code"]:
        _decide(answer, LOINC, loinc)
        return answer

    snomed = one_pass(service, fhir_base, text, SNOMED, timeout, label=label)
    _record(answer, "snomed", snomed)
    if snomed["code"]:
        _decide(answer, SNOMED, snomed)
        return answer

    # SECOND PASS. Both systems answered `no-match` on the bare label, so there
    # is no target to displace and the value domain can be sent without the
    # collateral damage that rejected it as a template. Any other pair of
    # statuses — below-threshold, out-of-constraint, scale-mismatch — means a
    # candidate WAS found and the bare-label answer stands; retrying those would
    # be T3 again by the back door.
    if (shape and shape.get("values")
            and loinc["status"] == "no-match"
            and snomed["status"] == "no-match"):
        values = ", ".join(shape["values"][:SECOND_PASS_VALUES])
        text_2 = f"{label} (recorded values: {values})"
        answer["codesearch_query_2"] = text_2

        loinc_2 = one_pass(service, fhir_base, text_2, LOINC, timeout, shape,
                           label)
        _record(answer, "loinc", loinc_2)
        answer["loinc_scale_typ"] = loinc_2["scale_typ"]
        answer["scale_note"] = loinc_2["scale_note"]
        if loinc_2["code"]:
            _decide(answer, LOINC, loinc_2)
            return answer

        snomed_2 = one_pass(service, fhir_base, text_2, SNOMED, timeout,
                            label=label)
        _record(answer, "snomed", snomed_2)
        if snomed_2["code"]:
            _decide(answer, SNOMED, snomed_2)
            return answer

        # The second pass also declined. Report ITS statuses, not the bare
        # label's: they are what the row's comment has to rest on, and keeping
        # the first pass's `no-match` would claim less was tried than was.
        loinc, snomed = loinc_2, snomed_2

    # Neither pass produced a target. The DECISIVE block mirrors the LOINC pass,
    # because that is the one every item is asked in and the one whose rejection
    # a reader meets first; the SNOMED pass is recorded in its own block and
    # named in the comment. A transport failure in either is surfaced as the
    # decisive status so main() can refuse to write the file.
    failed = next((p for p in (loinc, snomed)
                   if p["status"].startswith("error")), None)
    _decide(answer, LOINC, failed or loinc)
    answer["comment"] = declined_comment(
        answer["codesearch_query_2"] or text, loinc, snomed)
    return answer


def _pass_from_row(row, prefix, preferred=""):
    """One committed pass's outcome, in the shape one_pass() returns.

    The table keeps each pass in its own block precisely so that "why did this
    row get a SNOMED code rather than a LOINC one" is answerable from the file,
    and that is exactly the provenance a replay needs — see THE REPLAY.

    Three fields the blocks do not carry. `reasoning` is written once, on the
    DECISIVE pass, so it is claimed here only by the pass that matches the
    decisive block and left blank on the other rather than attributed to a search
    that did not produce it. `path` says how a run FETCHED an answer and is a
    property of that run, not of the answer, so a replay has none to report.
    `preferred` is the server-confirmed display the winning pass earned, which
    the row holds as `target_display` — supplied by the caller.
    """
    decisive = (row["codesearch_status"] == row[f"codesearch_{prefix}_status"]
                and row["codesearch_target"] == row[f"codesearch_{prefix}_target"])
    return {
        "status": row[f"codesearch_{prefix}_status"],
        "target": row[f"codesearch_{prefix}_target"],
        "display": row[f"codesearch_{prefix}_display"],
        "confidence": row[f"codesearch_{prefix}_confidence"],
        "reasoning": row["codesearch_reasoning"] if decisive else "",
        "path": "", "code": "", "preferred": preferred,
        "scale_typ": row["loinc_scale_typ"] if prefix == "loinc" else "",
        "scale_note": row["scale_note"] if prefix == "loinc" else "",
        "intent_note": "",
    }


def replay_query(label, row, fhir_base, service, timeout):
    """Re-decide one committed answer under the current gates. See THE REPLAY.

    Returns (answer, calls) where `calls` is the number of code-search requests
    it had to make — 0 for all but the rows a gate newly rejects on the LOINC
    pass, which open a SNOMED pass the committed run never had reason to run.
    """
    answer = {c: "" for c in PROVENANCE_COLUMNS + LOG_ONLY_COLUMNS
              + list(TARGET_COLUMNS) + ["comment"]}
    for column in PROVENANCE_COLUMNS + list(TARGET_COLUMNS) + ["comment"]:
        answer[column] = row.get(column, "")

    # A row with no target cannot lose one. Every gate here only ever rejects, so
    # replaying an already-declined row could not change it and asking the
    # service about it would be spending a search to confirm a decline.
    if not answer["target_code"]:
        return answer, 0

    system = answer["target_system"]
    prefix = "loinc" if system == LOINC else "snomed"
    won = _pass_from_row(row, prefix, preferred=answer["target_display"])

    verdict, why = intent_verdict(label, answer["target_display"])
    if verdict == "ok":
        return answer, 0

    won.update(status="intent-dropped", intent_note=why)
    _record(answer, prefix, won)
    answer["target_system"] = ""
    answer["target_code"] = ""
    answer["target_display"] = ""

    loinc = won if prefix == "loinc" else _pass_from_row(row, "loinc")
    snomed = won if prefix == "snomed" else _pass_from_row(row, "snomed")

    # THE ONE THING A REPLAY CANNOT READ OFF THE FILE. The resolution rule asks
    # SNOMED only where LOINC produced no usable target, so a row LOINC won has
    # an EMPTY SNOMED block — not a recorded decline, an absence. Rejecting the
    # LOINC answer makes that pass relevant for the first time, and skipping it
    # would decline a row on the strength of a search nobody ran. So this is the
    # one case the replay goes to the service for, and it is bounded by the
    # number of rows a gate newly rejects.
    calls = 0
    if prefix == "loinc" and not snomed["status"]:
        snomed = one_pass(service, fhir_base, answer["codesearch_query"],
                          SNOMED, timeout, label=label)
        calls = 1
        _record(answer, "snomed", snomed)
        if snomed["code"]:
            _decide(answer, SNOMED, snomed)
            return answer, calls

    failed = next((p for p in (loinc, snomed)
                   if p["status"].startswith("error")), None)
    _decide(answer, LOINC, failed or loinc)
    answer["comment"] = declined_comment(
        answer["codesearch_query_2"] or answer["codesearch_query"], loinc, snomed)
    return answer, calls


def _record(answer, prefix, result):
    """Copy one pass's outcome into its own provenance block."""
    answer[f"codesearch_{prefix}_status"] = result["status"]
    answer[f"codesearch_{prefix}_target"] = result["target"]
    answer[f"codesearch_{prefix}_display"] = result["display"]
    answer[f"codesearch_{prefix}_confidence"] = result["confidence"]


def _decide(answer, system, result):
    """Promote one pass to the decisive block, and map the row if it succeeded.

    The unprefixed `codesearch_*` columns are what lib/stats.py reads, so this
    is where a mixed-target row acquires the single status and confidence the
    per-stream statistics are computed from.
    """
    answer["codesearch_status"] = result["status"]
    answer["codesearch_target"] = result["target"]
    answer["codesearch_display"] = result["display"]
    answer["codesearch_confidence"] = result["confidence"]
    answer["codesearch_reasoning"] = result["reasoning"]
    answer["path"] = result["path"]
    if result["code"]:
        answer["target_system"] = system
        answer["target_code"] = result["code"]
        answer["target_display"] = result["preferred"]


def declined_comment(text, loinc, snomed):
    """Why a row carries no target. load_table requires one, and rightly: an
    empty target is a claim that the source could not answer, and a claim has to
    say what it rests on.

    Names BOTH searches, because on this table "unmapped" means two terminologies
    were asked and neither answered — a comment naming only LOINC would understate
    what was tried and invite someone to re-try SNOMED by hand.

    `text` is whichever string was actually sent last: for a row the SECOND PASS
    ran on, that is the value-augmented one, so the comment says the domain was
    tried rather than leaving a reader to wonder.
    """
    return (f"{_pass_comment(text, loinc, LOINC)} "
            f"{_pass_comment(text, snomed, SNOMED)}")


def _pass_comment(text, result, system):
    name = "LOINC" if system == LOINC else "SNOMED CT"
    constraint = constraint_text(system)
    status = result["status"]
    if not status:
        return f"{name} was not searched."
    proposal = f"{result['target']} |{result['display']}| at {result['confidence']}"
    return {
        "no-match": (f"{name}: no match for {text!r} within {constraint}."),
        "below-threshold": (f"{name}: proposed {proposal}, below the "
                            f"{CONFIDENCE_THRESHOLD} threshold."),
        "out-of-constraint": (f"{name}: proposed {proposal} but that code is "
                              f"not a member of {constraint}."),
        "absent": f"{name}: proposed {proposal} but that code is not known.",
        "retired": f"{name}: proposed {proposal}, which is retired.",
        "extension": (f"{name}: proposed {proposal}, which is not in the "
                      f"international core module."),
        "no-display": (f"{name}: proposed {proposal}, whose display the server "
                       f"does not confirm."),
        "scale-mismatch": (f"{name}: proposed {proposal}, which passed the "
                           f"constraint but {result['scale_note']}."),
        "intent-dropped": (f"{name}: proposed {proposal}, which passed the "
                           f"constraint but {result['intent_note']}."),
    }.get(status, f"{name}: {status}.")


# --------------------------------------------------------------------------- #
# Reporting
# --------------------------------------------------------------------------- #


def report(rows, queries):
    """What the run found. Printed so it can be pasted into a write-up."""
    mapped = [r for r in rows if r["target_code"]]
    asked = [r for r in rows if r["codesearch_status"] != "not-searchable"]
    print(f"\n  {len(rows)} item(s) over {len(queries)} quer(ies): "
          f"{len(mapped)} mapped, {len(rows) - len(mapped)} declared unmapped "
          f"({len(rows) - len(asked)} of them never asked — see pre-filter)")

    # The split this table exists to make visible.
    print("\n  target system")
    for system in (LOINC, SNOMED):
        hit = sum(1 for r in mapped if r["target_system"] == system)
        share = 100 * hit / len(mapped) if mapped else 0.0
        print(f"    {system:<28} {hit:>5}  {share:5.1f}% of mapped")

    statuses = {}
    for row in rows:
        statuses[row["codesearch_status"]] = \
            statuses.get(row["codesearch_status"], 0) + 1
    print("\n  decisive answer status")
    for status, count in sorted(statuses.items()):
        print(f"    {status:<18} {count:>5}")

    # Per pass as well, because the decisive block hides how often SNOMED was
    # asked at all — and "LOINC answered, so SNOMED was never run" is the fact a
    # reader of a mixed-target table most needs.
    for prefix in ("loinc", "snomed"):
        counts = {}
        for row in rows:
            counts[row[f"codesearch_{prefix}_status"] or "(not run)"] = \
                counts.get(row[f"codesearch_{prefix}_status"] or "(not run)",
                           0) + 1
        print(f"\n  {prefix} pass status")
        for status, count in sorted(counts.items()):
            print(f"    {status:<18} {count:>5}")

    # One confidence per QUERY, not per item: counting a family shared by ten
    # itemids ten times would overstate how many independent answers the run
    # actually got.
    by_query = {}
    for row in rows:
        if row["codesearch_confidence"]:
            by_query[row["codesearch_query"]] = \
                float(row["codesearch_confidence"])
    scored = sorted(by_query.values())
    if scored:
        print(f"\n  decisive confidence, {len(scored)} quer(ies) answered")
        buckets = [(1.0, 1.01), (0.9, 1.0), (0.8, 0.9), (0.7, 0.8), (0.0, 0.7)]
        for low, high in buckets:
            hits = [s for s in scored if low <= s < high]
            label = f"{low:.2f}" if high > 1.0 else f"{low:.2f}–{high:.2f}"
            bar = "#" * min(len(hits), 60)
            print(f"    {label:<12} {len(hits):>5}  {bar}")
        print(f"    threshold {CONFIDENCE_THRESHOLD}: "
              f"{sum(1 for s in scored if s >= CONFIDENCE_THRESHOLD)} kept, "
              f"{sum(1 for s in scored if s < CONFIDENCE_THRESHOLD)} dropped")

    # Coverage by category, which is the axis the pre-filter and the expected
    # failure modes both live on — the note, restraint and workflow categories
    # SHOULD be low, and a clinical category that is low is a finding.
    by_category = {}
    for row in rows:
        total, hit = by_category.get(row["_category"], (0, 0))
        by_category[row["_category"]] = (total + 1,
                                         hit + (1 if row["target_code"] else 0))
    print("\n  coverage by category")
    for category, (total, hit) in sorted(by_category.items(),
                                         key=lambda kv: -kv[1][0])[:25]:
        print(f"    {category:<30} {hit:>4}/{total:<5} "
              f"{100 * hit / total:5.1f}%")

    # How many distinct targets the mapped rows share. A generic target is not
    # wrong, but several items landing on one code means a consumer aggregating
    # by Observation.code merges them, so it is worth seeing.
    if mapped:
        shared = {}
        for row in mapped:
            shared.setdefault((row["target_system"], row["target_code"],
                               row["target_display"]), []).append(row)
        collisions = [(k, v) for k, v in shared.items() if len(v) > 1]
        print(f"\n  {len(mapped)} mapped row(s) over {len(shared)} distinct "
              f"target(s); {len(collisions)} target(s) carry more than one item")
        for (_system, code, display), group in sorted(
                collisions, key=lambda kv: (-len(kv[1]), kv[0][1]))[:20]:
            labels = ", ".join(r["mimic_display"] for r in group)
            print(f"    {code:<12} {display[:38]:<40} {len(group):>3}  "
                  f"{labels[:56]}")

    # The scale gate's own account of itself. Printed whether or not it fired,
    # because "checked and agreed" is a result and a silent gate is not
    # auditable — and because the WARN rows are defects this script deliberately
    # does NOT act on, so they have to be reported or they vanish.
    checked = [r for r in rows if r["loinc_scale_typ"]]
    if checked:
        rejected = [r for r in rows
                    if r["codesearch_loinc_status"] == "scale-mismatch"]
        warned = [r for r in checked if r["scale_note"] and r not in rejected]
        print(f"\n  scale gate: {len(checked)} row(s) had a LOINC SCALE_TYP to "
              f"check, {len(rejected)} rejected, {len(warned)} kept with a "
              f"warning")
        for row in sorted(rejected, key=lambda r: r["mimic_code"])[:20]:
            print(f"    REJECT {row['mimic_code']} "
                  f"{row['mimic_display'][:26]:<28} "
                  f"{row['codesearch_loinc_target']:<10} "
                  f"SCALE_TYP={row['loinc_scale_typ']:<5} "
                  f"observed={row['observed_shape'] or '—'}")
        if len(rejected) > 20:
            print(f"    … and {len(rejected) - 20} more")
        for row in sorted(warned, key=lambda r: r["mimic_code"])[:12]:
            print(f"    warn   {row['mimic_code']} "
                  f"{row['mimic_display'][:26]:<28} "
                  f"{row['target_code'] or '—':<10} "
                  f"SCALE_TYP={row['loinc_scale_typ']:<5} "
                  f"observed={row['observed_shape'] or '—'}")
        if len(warned) > 12:
            print(f"    … and {len(warned) - 12} more — see `scale_note` in "
                  f"{OUT_CSV.name}")

    # The two additive changes, each reported on its own so the run says which
    # one earned what.
    #
    # THEY ARE NOT DISJOINT, contrary to what was claimed when they were
    # implemented together. The argument was that the second pass fires only on
    # no-match-in-both while the rescue needs a candidate, so no row could be
    # touched by both. Wrong: the second pass's RETRY can return a sub-threshold
    # candidate, which the rescue then accepts. 40 rows did exactly that on the
    # first run under both — `224088 Pressure Reducing Device` reaches
    # `54973-3 |Pressure reducing device for bed…|` at 0.75 on the augmented
    # query and is admitted by the rescue, not by the threshold. The two compose,
    # which is useful, but it means neither block below is a clean attribution and
    # the overlap is printed rather than assumed away.
    second = [r for r in rows if r["codesearch_query_2"]]
    if second:
        won = [r for r in second if r["target_code"]]
        print(f"\n  second pass: {len(second)} row(s) retried with their value "
              f"domain, {len(won)} mapped")
        for row in sorted(won, key=lambda r: r["mimic_code"])[:20]:
            print(f"    {row['mimic_code']} {row['mimic_display'][:26]:<28} "
                  f"{row['target_system'].rsplit('/', 1)[-1]:<9} "
                  f"{row['target_code']:<12} {row['target_display'][:34]}")
        if len(won) > 20:
            print(f"    … and {len(won) - 20} more")

    commented = [r for r in rows if r["target_code"] and r["comment"]]
    if commented:
        print(f"\n  {len(commented)} mapped row(s) carrying a reviewed comment")
        for row in commented:
            print(f"    {row['mimic_code']} {row['mimic_display'][:26]:<26} "
                  f"-> {row['target_code']:<12} {row['target_display'][:38]}")


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
                             "tuning the settings against a handful of items. "
                             "Implies --dry-run: a table built from a subset "
                             "would drop every item it did not ask about.")
    parser.add_argument("--dry-run", action="store_true",
                        help="report only; do not write the CSV")
    parser.add_argument("--replay", action="store_true",
                        help="re-decide the COMMITTED table under the current "
                             "gates instead of searching again. Every proposal "
                             "this table records is already in the file, so a "
                             "gate that runs after the search can be re-applied "
                             "without asking code-search. Use it after changing "
                             "a gate; use a full run after changing a "
                             "constraint, a template or the threshold.")
    args = parser.parse_args()

    configure_tls(args.ca_bundle, args.insecure)
    if not args.fhir_base:
        sys.exit("  no --fhir-base and ONTOSERVER_URL unset — the validation "
                 "gate needs a terminology server.")

    codes = ig_codes()
    if not codes:
        sys.exit("  no source codes — CodeSystem-mimic-chartevents-d-items.json "
                 "is missing from input/resources/, so this would write an "
                 "empty table over a real one.")
    items_dict = dictionary(codes)
    shapes = observed_shapes()
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
    rows_by_code, asked = {}, {}
    for code, label in items:
        row = blank_row(code, label)
        # Carried for the report and the log, then dropped before the CSV is
        # written — the committed table's columns are CURATED + PROVENANCE.
        row["_category"] = items_dict[code]["category"]
        row["_param_type"] = items_dict[code]["param_type"]
        ok, why_not = searchable(items_dict[code])
        if ok:
            asked[code] = row
        else:
            decline_unasked(row, why_not)
        rows_by_code[code] = row

    # One search per COLLAPSED label, keyed CASE-INSENSITIVELY. The label is the
    # DICTIONARY's with its instance index stripped; `mimic_display` in the
    # committed table stays the IG's exact string, which load_curated requires,
    # and `codesearch_query` records the string actually sent, so the collapse
    # is visible in the CSV.
    #
    # Case-folded because MIMIC spells the same item two ways and the service is
    # not case-stable: `Face to Face Eval (Non-violent)` mapped while
    # `(Non-Violent)` came back unmapped, on one capital letter. Three families
    # are affected (the two `(Non-Violent)` pairs and `CAM-ICU MS Change`), and
    # a difference of casing is not a difference of meaning, so letting the two
    # spellings receive different targets is the same defect the index collapse
    # exists to prevent.
    #
    # The SENT string is the alphabetically first spelling among the members —
    # an arbitrary but deterministic choice, so a re-run cannot silently switch
    # which variant was asked about and churn the diff.
    spellings = {}
    for code in asked:
        label = collapsed(items_dict[code]["label"])
        spellings.setdefault(label.casefold(), set()).add(label)
    queries = {}
    for code in asked:
        key = collapsed(items_dict[code]["label"]).casefold()
        queries.setdefault(sorted(spellings[key])[0], []).append(code)
    ordered = sorted(queries)

    print(f"  {len(items)} IG code(s)"
          + (f" (subset of {len(codes)}, --only)" if args.only else ""))
    print(f"  dictionary: {D_ITEMS_GZ.relative_to(TERM.parents[1])} "
          f"({len(items_dict)} matched)")
    print(f"  pre-filter: {len(asked)} searchable; "
          f"{len(items) - len(asked)} declined unasked "
          f"({', '.join(sorted(DECLINED_CATEGORIES))})")
    # Loaded AFTER the pre-filter and the collapse, so a replay is checked
    # against the population this run would have asked about: a committed table
    # missing a code the dictionary now yields means the two have drifted, and
    # replaying it would silently carry the old file's coverage forward.
    committed = None
    if args.replay:
        if not OUT_CSV.is_file():
            sys.exit(f"  --replay needs {OUT_CSV.name} and it does not exist. "
                     f"Run without --replay to build it once.")
        with open(OUT_CSV, newline="") as fh:
            committed = {r["mimic_code"]: r for r in csv.DictReader(fh)}
        stale = sorted(set(codes) - set(committed))
        if stale:
            sys.exit(f"  --replay: {len(stale)} code(s) in the IG are absent "
                     f"from {OUT_CSV.name} ({', '.join(stale[:5])}"
                     f"{' …' if len(stale) > 5 else ''}). The table predates the "
                     f"source; a full run is the only honest way to add them.")

    print(f"  queries:    {len(asked)} item(s) collapse to {len(ordered)} "
          f"distinct label(s)")
    if args.replay:
        print(f"  mode:       REPLAY — re-deciding {OUT_CSV.name} under the "
              f"current gates; no search unless a gate opens a new pass")
    print(f"  gate:       {args.fhir_base}")
    print(f"  service:    {args.service}")
    print(f"  loinc:      {CONSTRAINT_VCL}")
    print(f"  snomed:     {CONSTRAINT_ECL}")
    print(f"  template:   {TEMPLATE!r} (identity — the bare label)")
    print(f"  threshold:  {CONFIDENCE_THRESHOLD}")
    print(f"  comments:   {len(COMMENT_OVERRIDES)}")
    if shapes:
        observed = sum(1 for c in codes if c in shapes)
        print(f"  scale gate: ON, {observed}/{len(codes)} item(s) have an "
              f"observed shape ({VALUE_SHAPES_CSV.name}); LOINC pass only")
    else:
        print("  scale gate: OFF (no observed shapes — see the warning above)")
    print()

    replayed = replay_calls = 0

    def work(label):
        nonlocal replayed, replay_calls
        if committed is not None:
            # Any member's row: they were fanned from one answer, and the
            # divergence assertion below is what keeps that true.
            answer, calls = replay_query(label, committed[sorted(queries[label])[0]],
                                         args.fhir_base, args.service, args.timeout)
            replayed += 1
            replay_calls += calls
            if not calls and answer["target_code"] == committed[
                    sorted(queries[label])[0]].get("target_code", ""):
                return answer                      # unchanged; not worth a line
        else:
            answer = search_query(label, args.fhir_base, args.service,
                                  args.timeout,
                                  query_shape(queries[label], shapes)
                                  if shapes else None)
        members = sorted(queries[label])
        fanned = f"x{len(members)}" if len(members) > 1 else ""
        system = (answer["target_system"].rsplit("/", 1)[-1]
                  if answer["target_system"] else "—")
        print(f"    {label[:34]:<34} {answer['codesearch_status']:<18} "
              f"{system:<10} {answer['target_code'] or '—':<12} "
              f"{answer['target_display'][:30]:<32} {fanned}", flush=True)
        return answer

    with concurrent.futures.ThreadPoolExecutor(args.workers) as pool:
        answers = dict(zip(ordered, pool.map(work, ordered)))

    if committed is not None:
        print(f"\n  replayed {replayed} quer(ies) from {OUT_CSV.name}; "
              f"{replay_calls} code-search call(s) made (a LOINC answer a gate "
              f"newly rejects opens the SNOMED pass the committed run had no "
              f"reason to run)")

    # Fan each query's one answer back across the itemids sharing its collapsed
    # label. This is what makes `Pressure Ulcer Stage #3` and `#7` disagreeing
    # unrepresentable.
    for label, members in queries.items():
        for code in members:
            rows_by_code[code].update(answers[label])

    # Sorted by mimic_code so a re-run diffs only where an answer changed, not
    # wherever the thread pool happened to finish first.
    rows = sorted(rows_by_code.values(), key=lambda r: r["mimic_code"])

    # A transport failure is not an answer, so a partial run writes nothing.
    failed = [r for r in rows if r["codesearch_status"].startswith("error")
              or r["codesearch_loinc_status"].startswith("error")
              or r["codesearch_snomed_status"].startswith("error")]
    if failed:
        print(f"\n  {len(failed)} of {len(rows)} row(s) hit a code-search "
              f"failure after retries — NOT writing {OUT_CSV.name}.")
        for row in failed[:5]:
            print(f"    {row['mimic_code']} {row['mimic_display'][:26]:<26} "
                  f"{row['codesearch_status'][:70]}")
        if len(failed) > 5:
            print(f"    … and {len(failed) - 5} more")
        sys.exit("  Fix the service and re-run; cached answers make the "
                 "retry cheap.")

    # The invariant the collapse exists to guarantee, asserted rather than
    # assumed. The fan-out above makes divergence structurally impossible, so
    # this can only fire if the grouping and the fan-out ever stop agreeing —
    # and the whole point of the rule is that a reader should not have to trust
    # that they do. Checked on the (system, code) PAIR, because on a
    # mixed-target table two members agreeing on a code while disagreeing on its
    # system would be just as wrong and would not show up on the code alone.
    diverged = {label: sorted({(rows_by_code[c]["target_system"],
                               rows_by_code[c]["target_code"] or "(unmapped)")
                              for c in members})
                for label, members in queries.items()
                if len({(rows_by_code[c]["target_system"],
                         rows_by_code[c]["target_code"]) for c in members}) > 1}
    if diverged:
        for label, targets in sorted(diverged.items()):
            print(f"    {label}: {targets}", file=sys.stderr)
        sys.exit(f"  {len(diverged)} quer(ies) whose itemids ended up on "
                 f"different targets, which the label collapse exists to "
                 f"prevent. NOT writing {OUT_CSV.name}.")

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
        # lib/stats.py reads `constraint_vcl` or `constraint_ecl` into the
        # per-stream statistics and takes the first it finds. This stream has
        # BOTH, so the two are also recorded together under `constraints` where
        # neither is privileged; the flat key exists for the statistics table.
        "constraint_vcl": CONSTRAINT_VCL,
        "constraints": {
            LOINC: {"vcl": CONSTRAINT_VCL, "url": loinc_constraint_url()},
            SNOMED: {"ecl": CONSTRAINT_ECL, "url": snomed_constraint_url()},
        },
        "resolution_rule": ("LOINC first; SNOMED CT only where the LOINC pass "
                            "produced no usable target. The two are never "
                            "compared on confidence. Where BOTH answer "
                            "no-match on the bare label, both are retried once "
                            "with the item's observed value domain appended."),
        "second_pass": {"values_sent": SECOND_PASS_VALUES,
                        "fires_when": "loinc and snomed both no-match",
                        "source": (str(VALUE_DOMAINS_CSV.relative_to(
                            TERM.parents[1]))
                            if VALUE_DOMAINS_CSV.is_file() else None)},
        "template": TEMPLATE,
        "confidence_threshold": CONFIDENCE_THRESHOLD,
        # The scale gate's settings and inputs, so a table's diff can be read
        # against the rule that produced it. `enabled` is false when the
        # valueshapes CSVs were absent, which is the one way this generator can
        # produce a WEAKER table without anything looking wrong.
        "scale_gate": {
            "enabled": bool(shapes),
            "shapes_csv": (str(VALUE_SHAPES_CSV.relative_to(TERM.parents[1]))
                           if VALUE_SHAPES_CSV.is_file() else None),
            "systems_checked": [LOINC],
            "never": sorted(SCALE_TYP_NEVER),
            "compatible": {k: sorted(v)
                           for k, v in sorted(SCALE_COMPATIBLE.items())},
            "numeric_value_fraction": NUMERIC_VALUE_FRACTION,
            # Recorded as an explicit null so a reader of an old log beside a
            # new one can see the carve-out was REMOVED rather than never
            # existing. See THE SCALE RESCUE — BUILT, MEASURED, AND REJECTED.
            "sub_threshold_rescue": None,
            "snomed_not_checked_because": (
                "SNOMED models this as 370132008 |Scale type| but publishes it "
                "on 4 of the 173 concepts this table targets, 0.0% by "
                "occurrence, so the check would abstain on 98% of SNOMED rows "
                "while appearing to have run"),
        },
        # Which mode wrote this file. A replay re-decides committed proposals
        # under the current gates and does NOT re-ask code-search, so a log
        # claiming a full run would overstate what this file rests on — the
        # searches behind it are the earlier run's. See THE REPLAY.
        "run_mode": ("replay" if args.replay else "search"),
        **({"replay": {"queries": replayed, "codesearch_calls": replay_calls,
                       "source": OUT_CSV.name}} if args.replay else {}),
        "intent_gate": {
            "enabled": True,
            # Both, unlike the scale gate: the modifier is a property of the
            # source label and of the target's words, and both terminologies
            # have words for it. See THE INTENT GATE.
            "systems_checked": [LOINC, SNOMED],
            "label_pattern": INTENT_LABEL_RE.pattern,
            "target_pattern": INTENT_TARGET_RE.pattern,
            "rule": ("a label carrying an intent word must reach a target whose "
                     "server-confirmed display states one, or the answer is "
                     "declined `intent-dropped`"),
            "declines_only": ("no replacement target is sought; a rescued row "
                              "would be a hand-picked code no rule produced"),
            "armed": sorted(
                code for code, item in items_dict.items()
                if INTENT_LABEL_RE.search(item["label"].strip())),
        },
        "pre_filter": {
            "dictionary": str(D_ITEMS_GZ.relative_to(TERM.parents[1])),
            "declined_categories": DECLINED_CATEGORIES,
            "declined_unasked": {
                code: rows_by_code[code]["comment"]
                for code in sorted(set(codes) - set(asked))},
        },
        # Which itemids shared a query, so the collapse is auditable without
        # re-deriving it from the dictionary.
        "query_key": ["label with #<n> stripped, case-folded"],
        "shared_queries": {label: sorted(members)
                           for label, members in sorted(queries.items())
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
