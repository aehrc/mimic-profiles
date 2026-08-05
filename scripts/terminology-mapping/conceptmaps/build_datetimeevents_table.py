#!/usr/bin/env python3
"""Generate conceptmaps/datetimeevents-snomed.csv — the 188 ICU date/time items -> SNOMED CT.

The fourth generated table, and the FIRST to target SNOMED CT since the
`procedureevents` one — so it is the first stream to put a second target system
into the Observation.code map, which until now was LOINC throughout.

WHAT THE SOURCE CODES MEAN. mimic-datetimeevents-d-items holds 188 itemids from
MIMIC's ICU `d_items` dictionary, bound to Observation.code on
MimicObservationDatetimeevents, and `Observation.value[x]` on that profile is a
**dateTime**. So the code has to name the thing whose date is being recorded, and
the label names it obliquely: `224288 Arterial line Insertion Date` is an
arterial catheterisation whose date was written down, not a concept called
"insertion date". The dictionary confirms the population is homogeneous in
exactly one respect — `param_type` is `Date and time` for all 188 — and
heterogeneous in every other:

    Access Lines - Invasive          109      device x maintenance action
    Skin - Impairment                 31      three '#N' families
    Access Lines - Peripheral         21      gauge/RIC x maintenance action
    ADT + Adm History/FHPA             9      admission, discharge, birth, LMP
    documentation notes               11      OT, Pastoral, Research, Family Mtg,
                                              Care Plans — note metadata
    GI/GU, Hemodynamics, General,      7      Foley/GU dates, device calibration
    Labs

130 of the 188 are ONE DEVICE CROSSED WITH ONE OF FIVE ACTIONS — Insertion Date
(33), Dressing Change (41), Cap Change (24), Tubing Change (21), Change over Wire
Date (17). The arterial line alone appears five times. That structure, not the
individual labels, is what this generator had to be designed against.

CONSTRAINT_ECL. procedure ∪ clinical finding ∪ event ∪ **temporal observable**.
The first three are the `procedureevents` constraint and are here for the same
reason: unconstrained, code-search answers a device label with the device
(`Foley Catheter` -> `73368009 |Foley catheter (physical object)|` at confidence
1.0), and confidence does not separate that from a good answer — the worst
answers score highest.

The fourth term is what makes this an Observation.code stream rather than a
Procedure.code one. The value is a date, and SNOMED models the administrative
dates as observable entities, which no procedure/finding/event constraint can
reach: under the first three terms alone `Date of Birth`, `Discharge Date/Time`,
`Last menses` and `Pregnancy due date` are all NO MATCH, and probing confirmed
this is structural rather than a template defect — those hierarchies simply hold
no such concept, only distractors like `No date of birth given` and
`Able to remember own date of birth`, which the searcher correctly declined.

WHY `<<364713004 |Temporal observable|` AND NOT `<<363787002 |Observable entity|`.
127 concepts against 11,142, and the difference is load-bearing rather than
tidiness. Both rescue the same rows, but the full Observable entity hierarchy
answered `Last dialysis` with `861000124109 |Interdialytic time|` — an INTERVAL,
not a date, so the row would make the data say something false. `<<364713004`
excludes that concept structurally instead of relying on the model to avoid it,
and under it `Last dialysis` comes back `108241001 |Dialysis procedure|`, which
is the right answer shape for a template that asks for the event a date was
recorded against. The wider hierarchy also cost a control row
(`Arterial line Cap Change` regressed to NO MATCH under it), consistent with a
5.7% larger candidate pool diluting the non-date rows.

TEMPLATE. `ICU flowsheet date/time recorded for the following event: {}`, one
sentence, identical for all 188. It states a fact about the source table — this
is a flowsheet column whose value is a timestamp — rather than a judgement about
any item, and it names the date as the VALUE so the trailing "Date" in most
labels is not read as part of the concept. Four were run over the labels that
discriminate between them:

    bare label                                    'Pressure ulcer #1- Dressing
                                                   change' -> 1163217004
                                                   |Pressure injury stage I|
    "…column recording the date and time of: {}"   'Arterial line Cap Change' ->
                                                   1230246000 |Replacement of
                                                   DRESSING of insertion site…|
    "…procedure event recorded on placement or     asserts a fact that is false
     performance of: {}"                           for this table
    "…date/time recorded for the following         <- kept
     event: {}"

Each rejection is a different failure. The BARE label makes the instance index
`#1` read as a clinical STAGE, at 0.85 — a confidently wrong answer that any
wrapper suppresses. The first wrapper answers a CAP change with a DRESSING
replacement, which is worse than vague: it asserts an action that did not happen,
and it collides with the sibling item `224287 Arterial Line Dressing Change`, so
two distinct source items would land on one code. The `procedureevents` sentence
is rejected on the house rule rather than on its answers — it was actually the
best on one row — because "placement or performance" is simply untrue of a table
holding removals, identification dates, cap changes, date of birth and last
menstrual period. Its cost is visible and bounded: the pressure-ulcer dressing
family drops from `225144007 |Application of dressing to pressure injury|` to the
broader `182532000 |Dressing of ulcer|`.

A ROUTED PAIR OF CONSTRAINTS WAS TESTED AND REJECTED. Because the maintenance
actions risk being answered with the device's INSERTION procedure — which would
make the data say a line was placed when a cap was changed — a second constraint
subtracting the 1,601 insertion-method procedures
(`… MINUS (<<71388002 : 260686004 |Method| = <<257867005 |Insertion - action|)`)
was built and routed by a regex on the label's action. It is not here because it
earns nothing: under the kept template the three `Change over Wire` rows it was
meant to rescue resolve identically WITHOUT it (all three ->
`416504003 |Vascular line exchange over wire|` at 0.85, same single NO MATCH on
IABP), and the insertion-for-a-maintenance-label answer it was built to prevent
does not occur at all — 0 of 12 probed maintenance labels returned an insertion
procedure. One constraint, routed nowhere, gives byte-identical results with less
machinery. The subtraction only looked necessary because it was first measured
under the rejected template above, where it was compensating for that template's
cap-change-to-dressing error.

DEVICE_CARE_CODES is the one check the constraint cannot make, and the analogue
of the outputevents table's TOTAL_CODES. `422744007 |Arterial catheter care|` is a
true statement about a dressing change, a cap change, a tubing change AND a wire
exchange on an arterial line, so it is not a wrong answer about any single row —
it is a wrong answer about the TABLE. Not hypothetical: under the kept template
`224284 Arterial line Cap Change` and `224290 Arterial line Tubing Change` both
come back `422744007` at 0.85 and 0.80, two distinct flowsheet columns collapsing
onto one code with the action axis gone. Rejected as targets for that reason and
the items left unmapped with the proposal recorded.

IT IS CHECKED BEFORE THE THRESHOLD, not after, and the ordering is load-bearing
for what the committed table SAYS about itself. Under the earlier order, 12 of
the 24 cap- and tubing-change items came back with a device-care concept scored
just under the gate and were written down as `below-threshold` — which reads as
"close", and invites exactly the question of whether a looser gate would take
them. It would not: their proposal is declined here at any threshold. The
statistics lib/stats.py derives are only as honest as the status column they
count, so a row has to carry the reason that actually decided it.

Note what this list is NOT. It can only DECLINE a row; it cannot pin a target.
That is the same boundary COMMENT_OVERRIDES observes, and for the same reason: the
moment a hand-written list can choose a code, the table stops being "what the
service returned, gated" and becomes a way to hand-write mappings around
CONFIDENCE_THRESHOLD and the gate. Every entry is validated against the server at
startup, because a mistyped SCTID in a reject list rejects nothing and does so
silently — the same failure that had `225390008` in a draft constraint on the
belief that it meant "Care" when it means `Triage`.

WRONG_ACTION is the second reject list, and it exists because being wrong about
the ACTION is the one failure a constraint over hierarchies cannot catch: the
device is right, the concept is real, specific and in the constraint, and only
the verb is wrong. The full run produced exactly one.
`225332 Tunneled (Hickman) Tubing Change` was answered at 0.85 with
`439355003 |Replacement of tunnelled centrally inserted central venous catheter|`
on the reasoning "Hickman is a tunneled central venous catheter; change =
replacement" — which drops the word the label turns on. Changing the tubing does
not replace the catheter, so the mapping asserts an invasive procedure that did
not happen. Replacing the catheter is what the sibling column
`225328 Tunneled (Hickman) Change over Wire Date` records, and that row takes the
generic `416504003 |Vascular line exchange over wire|` shared with eight other
devices — so the precise concept sits on the wrong one of the two. It cleared the
threshold, the constraint and the server gate, so nothing else in this generator
was going to stop it, which is the argument against reading 0.85 as a correctness
signal made concretely rather than in the abstract.

It is keyed on the (query, code) PAIR and not on the code, which is what
separates it from DEVICE_CARE_CODES rather than making it a longer version of
that list. A device-care concept is generic — true of every action on the line,
so never the answer for any of them, so rejectable outright. `439355003` is the
opposite: a precise concept, and the one a future run could legitimately return
for `225328`. Rejecting the code outright would foreclose that. Same boundary as
the other two lists, though: it declines, it cannot pin. It cannot supply
`225199003 |Changing intravenous infusion line|`, which is what this row should
have and what the Tubing Change retrieval failure below says the service never
returns.

WHAT SNOMED DOES NOT CONTAIN, which is most of this stream's coverage gap. 45 of
the 188 items are unrepresentable, verified against the server rather than
inferred from a low score:

  * Cap Change (24). There is no concept for changing a catheter cap, hub,
    connector or stopcock. Filters for `injection cap`, `catheter cap`,
    `catheter hub`, `stopcock`, `luer`, `needleless` and `bung` over the
    constraint all return zero, as does `cap` within
    `<<384728007 |Replacement of device|`. NO MATCH is the honest outcome for all
    24, and the only concepts in the neighbourhood are the device-care ones
    DEVICE_CARE_CODES exists to reject.
  * Tubing Change (21). Here the concept DOES exist —
    `225199003 |Changing intravenous infusion line|`, under
    `387760006 |Infusion care|` — and it IS a member of this constraint, confirmed
    by expansion. code-search returned it ZERO times across every probe,
    including for the bare strings `Tubing Change` and `IV Tubing Change`. That is
    a retrieval failure in the service, not a coverage gap in SNOMED, and it is
    recorded here rather than worked around: the fix is in the service or in a
    stated setting, not in a hand-written row.

So the coverage to expect from this stream is around 40%, BELOW the 64% the ICU
`procedureevents` population scored and far below the ICD populations' 99.5%.
That is the result, not a number to tune towards: a quarter of the population has
no target in the target terminology before any question of search quality
arises, and the acronym population (`AVA`, `RIC`, `IO`, `EKOS`) fails the way the
`procedureevents` write-up already documents. Loosening the threshold or dropping
a constraint term to raise it would buy device-care and physical-object answers.

CONFIDENCE CARRIES SOME SIGNAL, AND NOT THE KIND THAT WOULD LET THE GATE MOVE.
The design probes all came back at 0.80 or 0.85, which is what an earlier
revision of this docstring recorded; the full run does not. It spreads 0.60 (8),
0.70 (26), 0.72 (1), 0.75 (13), 0.80 (30), 0.85 (73), so the near-threshold band
is real and the obvious question — 0.8 down to 0.7 buys 40 items — was asked
against the table and answered NO. Reading those 40:

  * 12 are declined by DEVICE_CARE_CODES regardless of the threshold, and now say
    so (see above). The band is 28 rows, not 40.
  * 10 are `Pressure Ulcer #N- Date Indentified` -> `298059007 |Date of onset|`.
    Date identified is not date of onset — that is the distinction
    present-on-admission reporting for hospital-acquired pressure injury turns
    on, and one family answer propagates it to all ten rows at once.
  * 5 more assert an action that did not happen, the same failure the rejected
    TEMPLATE was rejected for: two Tubing Change items -> `103713001 |Replacement
    of catheter|`, `229739 22 Gauge Cap Change` -> `225199003 |Changing
    intravenous infusion line|` (the concept the Tubing Change items should have
    and never get), and `227541 SvO2 Calibrated` -> `250551006 |Venous oxygen
    saturation measurement|`, which turns a device-calibration timestamp into a
    measurement.
  * 2 are device-maintenance concepts of exactly the DEVICE_CARE_CODES kind that
    the list simply did not name; they are named now.
  * 8 are `Date of event` / `Date of procedure` on documentation-note items —
    consistent with what is already accepted at 0.80, and worth nothing.
  * 3 are right, and are the cost of leaving the gate where it is: the CCO PAC,
    PA Catheter and Dialysis Catheter `Change over Wire Date` items score
    0.70–0.75 for `416504003 |Vascular line exchange over wire|`, which is
    already the accepted target of nine sibling items at 0.80. They stay
    unmapped. Buying them costs 17 wrong rows at a flat 0.7, and buying them
    alone would mean a rule written to admit three known answers — the same
    objection that keeps `Last menses` unmapped.

So the threshold is not what is carrying the accuracy, and it is also not what
is holding the coverage down; the constraint and the template are doing the
first and SNOMED's coverage is doing the second. The distribution is printed at
the end of every run, so this can be revisited with evidence.

NO PRE-FILTER, unlike the outputevents table. That generator declines 5 items
unasked because the dictionary proves they record no volume, and it earns that
with evidence — one of them otherwise gets a perfectly good volume code. The
analogous candidate here is the 11 documentation-note items (`Date signed`,
`Date - Therapist`, `PC Date`, `FM Date/Time`, the `Stroke NCP` slots) plus the
two device-calibration items, and the stated basis for declining them unasked
does not exist: all 13 return NO MATCH unaided, with zero confident-wrong
answers, even though real traps were available in the constraint
(`27662000 |Calibration of urethra|` and `9474002 |Endoscopy and calibration|`
are both members, and 974 referral concepts are). A rule keyed on the
dictionary's `category` column would therefore buy no additional declines while
suppressing `229651 Stroke NCP - Water Swallow Date`, the one item in that group
with a plausible future target. The dictionary is not read by this generator at
all, so this stream adds no input to input-manifest.json.

FAMILY_INDEX is the outputevents table's rule, reused verbatim rather than
reinvented, and this population is where it pays most: 31 of the 188 items are
three `#N` families. It is load-bearing for correctness and not merely for cost.
Searched per item, `227790 Impaired Skin  - Dressing Change #1` comes back
`18949003 |Change of dressing|` (a PROCEDURE) and `227798 … #9` comes back
`7919002 |Impaired skin integrity|` (a CLINICAL FINDING) — opposite semantic
axes, 0.85 confidence apiece, and nothing downstream would flag it. Collapsing
makes that disagreement unrepresentable rather than merely unlikely.

What collapsing does NOT buy is correctness: that family's collapsed stem answers
with the finding, which is the wrong axis for a dressing-change label, so it is a
row to read rather than a row that is now right. `229883 Pressure ulcer #1- Date
Indentified_OLD_1` deliberately keeps its own family — the `_OLD_1` suffix marks a
separate, deprecated MIMIC column, and inventing a second regex to fold it in
would be a rule with no evidence behind it.

Two settings were deliberately NOT taken, both because they would smuggle
hand-picked targets in through a setting that is supposed to be a stated rule:

  * `Last menses` and `Pregnancy due date` stay unmapped. `21840007 |Date of last
    menstrual period|` and `161714006 |Estimated date of delivery|` are real and
    exact, but they hang off `364313002 |Measure of menstruation|` and
    `364324000 |Measure of pregnancy|` rather than `<<364713004`, so reaching them
    means adding two hierarchies chosen BECAUSE the two wanted answers were found
    in them. That is 43 concepts, so the cost is not the objection; naming a
    search space to contain one known answer is.
  * `225322 Dialysis Catheter Insertion Date` stays unmapped although
    `736919006 |Haemodialysis catheterisation|` is in the constraint and is the
    right concept. Under the kept template the row is NO MATCH — the earlier
    wrong-SITE answer `1172563000 |Insertion of peritoneal dialysis catheter|`
    that a draft template produced is gone, which is the improvement that
    matters. Writing the correct code in by hand is exactly what
    COMMENT_OVERRIDES is forbidden from doing.

THE GATE is build_d_items_table.py's, the SNOMED one: the target must exist, be
ACTIVE, and be in the SNOMED international core module rather than a national
extension, and its display is replaced with the server's own preferred term so
verify_curated_snomed.py's display check passes by construction. A target that
fails is treated exactly as an absent one.

EQUIVALENCE is not this script's concern. Every mapping a table supplies is
`relatedto`, set by lib/assemble.py when it builds the group. That is doing real
work here: `1230246000 |Replacement of dressing of insertion site of vascular
catheter|` answers dressing changes on the arterial line, the dialysis catheter
and others, so several source items legitimately share one target, and no
direction between a MIMIC flowsheet column and a SNOMED concept is asserted.

Why it is NOT part of `make mappings`: same as the three generators before it. It
needs the network and an LLM-backed service, and it WRITES a build input.
Determinism lives in the split — this runs by hand, its output is committed, and
`make mappings` reads the committed CSV and never a server, so
`make mappings && git diff --exit-code` stays a valid test.

    make datetimeevents-table ARGS=--insecure

Usage:
  uv run scripts/terminology-mapping/conceptmaps/build_datetimeevents_table.py
  uv run .../build_datetimeevents_table.py --only 224288,224284 --insecure
"""

import argparse
import concurrent.futures
import csv
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
from conceptmaps.lib.canonical import SNOMED  # noqa: E402
from conceptmaps.lib.curated import CURATED_COLUMNS  # noqa: E402
from conceptmaps.lib.igsource import source_concepts  # noqa: E402
from verify.verify_curated_snomed import INTL_MODULE, lookup  # noqa: E402

# --------------------------------------------------------------------------- #
# The stated rules
# --------------------------------------------------------------------------- #

# procedure ∪ clinical finding ∪ event ∪ temporal observable. See the module
# docstring for why the fourth term is here, why it is `<<364713004` and not
# `<<363787002 |Observable entity|`, and why there is no second routed constraint
# subtracting the insertion-method procedures.
CONSTRAINT_ECL = ("(<<71388002 OR <<404684003 OR <<272379006 "
                  "OR <<364713004)")

# One sentence, identical for all 188 items. Chosen over three alternatives by
# running all four over the labels that discriminate between them — see TEMPLATE
# in the module docstring, including why the bare label loses and why the
# procedureevents sentence is rejected on the house rule rather than on its
# answers.
TEMPLATE = "ICU flowsheet date/time recorded for the following event: {}"

# Below this, code-search's answer is discarded and the item is left unmapped.
# Matches the three generators before it, and checked AFTER both reject lists —
# see search_family, and the module docstring on why that ordering is what makes
# the status column mean anything.
#
# Kept at 0.8 on evidence rather than by inheritance: the module docstring reads
# all 40 rows in the 0.70–0.80 band and finds 17 clinically wrong, 8 vacuous, 12
# already declined on meaning, and 3 right. The accuracy rests on CONSTRAINT_ECL
# and TEMPLATE, not here. The distribution is printed at the end of every run so
# this can be moved with evidence rather than by taste.
CONFIDENCE_THRESHOLD = 0.8

# Generic device care and maintenance. Each of these is a TRUE statement about a
# dressing change, a cap change, a tubing change and a wire exchange alike, so a
# row mapped here does not merely lose precision — it makes four distinct
# flowsheet columns indistinguishable, which is a wrong answer about the table
# rather than about any row. Rejected as targets for that reason, with the
# proposal recorded; see DEVICE_CARE_CODES in the module docstring.
#
# This list can only DECLINE a row. It cannot pin a target, which is the same
# boundary COMMENT_OVERRIDES observes and for the same reason.
#
# Displays are the server's preferred terms and are checked at startup by
# validate_reject_lists(): a mistyped SCTID here would reject nothing, silently.
DEVICE_CARE_CODES = {
    "422744007": "Arterial catheter care",
    "392020005": "Peripherally inserted central catheter care",
    "449107008": "Care of central venous catheter",
    "449584006": "Care of tunnelled central venous catheter",
    "385757000": "Venous catheter care",
    "423877008": "Peripheral catheter care",
    "423687009": "Peripheral intravenous catheter care",
    "422463007": "Pulmonary artery catheter care",
    "427614007": "Atrial catheter care",
    "704118000": "Epidural catheter care",
    "1284922006": "Haemodialysis catheter care",
    "737944006": "Care of urinary catheter",
    "445191009": "Care of suprapubic urinary catheter",
    "226005007": "Care of central line",
    "386482009": "Umbilical line tube care",
    "133909001": "Maintenance of device",
    "370771002": "Maintenance of invasive device",
    "386493006": "Venous access device maintenance",
    "406168002": "Dialysis access maintenance",
    "225356004": "Care of equipment and devices",
    "309637002": "Care of equipment by device",
    "708010003": "Intraosseous access care management",
    # Device-specific maintenance, added after reading the generated table. These
    # two are the same failure as the catheter-care entries above and were missed
    # only because the list was built from the catheter families: `34475007` is
    # equally true of `225335 IABP Cap Change`, `225340 IABP Tubing Change`,
    # `225336 IABP Change over Wire Date` and `225338 IABP Insertion Date`, and it
    # was proposed for the first two; `21151009` likewise for the ICP line.
    # Naming the device does not make the concept specific to an action.
    "34475007": "Intraaortic balloon pump maintenance",
    "21151009": "Intracranial pressure monitor maintenance",
}

# One family's proposal declined because the concept names a DIFFERENT ACTION on
# the right device — not a vaguer action, a different one.
#
# Deliberately a different mechanism from DEVICE_CARE_CODES, because it is a
# different failure. That list rejects a code everywhere, unconditionally,
# because the concept is GENERIC: `Arterial catheter care` is true of every
# action on the line, so it is never the answer for any single one of them.
# `439355003 |Replacement of tunnelled centrally inserted central venous
# catheter|` is the opposite — a precise concept, and the right target for
# `225331 Tunneled (Hickman) Change over Wire Date`. What is wrong is the
# PAIRING. Asked about `Tunneled (Hickman) Tubing Change`, code-search answered
# it at 0.85 reasoning "Hickman is a tunneled central venous catheter; change =
# replacement", which drops the word the label turns on. Changing the tubing does
# not replace the catheter, so the mapping asserts an invasive procedure that did
# not happen — the same class of error as the cap-change-to-dressing answer that
# cost a candidate TEMPLATE its place, and it survived here because it scored
# 0.85. Putting the code in DEVICE_CARE_CODES would take the wire-change row down
# with it.
#
# Note what this can and cannot do, the same boundary the two lists above
# observe: it DECLINES a pair. It cannot pin `225199003 |Changing intravenous
# infusion line|`, which is the concept this row should have and which the module
# docstring records the service never returning for any of the 21 Tubing Change
# items. That is a retrieval failure to fix in the service or in a stated
# setting; writing the answer in by hand here is exactly what COMMENT_OVERRIDES
# is forbidden from doing.
#
# Keyed on the family QUERY rather than the itemid, because the query is what
# search_family is given and because a judgement that is right about a label is
# right about every member of that label's family.
#
# Displays are the server's preferred terms and are checked at startup by
# validate_reject_lists(), and the queries are checked against the IG's own
# labels by validate_wrong_action_queries() — an entry naming a label that no
# longer exists declines nothing, silently.
WRONG_ACTION = {
    ("Tunneled (Hickman) Tubing Change", "439355003"): (
        "Replacement of tunnelled centrally inserted central venous catheter",
        "changing the tubing does not replace the catheter — replacing it is "
        "what the sibling column 225328 Tunneled (Hickman) Change over Wire "
        "Date records"),
}

# The instance-index rule, reused verbatim from build_outputevents_table.py
# rather than reinvented: 31 of the 188 items are three '#N' families, and
# searched per item one of those families splits across the procedure/finding
# boundary at identical confidence. See FAMILY_INDEX in the module docstring.
#
# A regex applied to every label identically, so it is a stated rule and not a
# per-item judgement. `mimic_display` in the committed table is still the IG's
# exact label — load_curated requires that — and `codesearch_query` records what
# was actually sent, so the collapse is visible in the CSV.
FAMILY_INDEX = re.compile(r"\s*#\d+")

# --------------------------------------------------------------------------- #
# Paths and provenance
# --------------------------------------------------------------------------- #

TERM = Path(__file__).resolve().parents[1]
OUT_CSV = Path(__file__).resolve().parent / "datetimeevents-snomed.csv"
LOG_JSON = TERM / "output" / "datetimeevents-generation-log.json"

# What the service proposed on every row, including the rows where the proposal
# was then rejected by the threshold, by the gate or by DEVICE_CARE_CODES — so
# that "this item is unmapped" is auditable in the committed diff rather than
# only in a run that has since scrolled away.
#
# `codesearch_query` is what makes the family collapse visible: it holds the
# stem that was actually sent, which for 31 of these rows is not the row's own
# label.
#
# `codesearch_status` and `codesearch_confidence` are the two columns lib/stats.py
# reads for the per-stream statistics, so the vocabulary stays the one the other
# tables use — plus `device-care`, which only this stream can produce.
#
# The build ignores all of them: lib.curated.load_table reads CURATED_COLUMNS and
# discards the rest.
PROVENANCE_COLUMNS = ["codesearch_query", "codesearch_target",
                      "codesearch_display", "codesearch_confidence",
                      "codesearch_status", "codesearch_reasoning"]

# Recorded per row in the log only. `path` (cached / fast / agentic) says how this
# run fetched an answer, not anything about the answer, so it would flip to
# "cached" on the next run and show up as a wall of changed rows in a diff where
# no mapping moved.
LOG_ONLY_COLUMNS = ["path"]

# --------------------------------------------------------------------------- #
# Sources
# --------------------------------------------------------------------------- #


def ig_codes():
    """(code, display) for the 188 items, read from the IG's own ValueSet.

    Routed through the observation builder's own SOURCES declaration for the
    reason the three generators before it give: lib.curated.load_table rejects a
    row whose display differs from the IG's by so much as a character, so the
    generator and the build must read displays through the same function, and
    through the same declaration, or the table this writes can fail the build
    that reads it.
    """
    from conceptmaps.build_observation_cm_vs import SOURCES

    source = next(s for s in SOURCES if s.get("table") == OUT_CSV)
    return dict(source_concepts(source))


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
    """code-search's best match for `text`, constrained to CONSTRAINT_ECL.

    Retries transport failures. A dropped connection is not an answer, and the
    difference matters more here than it looks: 'the service said no match' and
    'the service was not running' both end up as an unmapped row, and only one of
    them is a finding. A run that quietly mixes the two produces a table that
    understates coverage and reads exactly like a real result. Exhausted retries
    raise, and main() refuses to write the CSV.
    """
    url = (f"{SNOMED}?fhir_vs=ecl/"
           f"{urllib.parse.quote(CONSTRAINT_ECL, safe='')}")
    body = json.dumps({
        "text": text,
        "url": url,
        "system": SNOMED,
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


def gate(fhir_base, code):
    """('ok', display) if `code` is usable, else (reason, None).

    The same three checks verify_curated_snomed.py enforces, but used as a filter
    rather than an assertion: a target that fails here is treated exactly as an
    absent one, and the item is left unmapped with the rejected proposal
    recorded. A confidence score says nothing about whether a concept is retired
    or belongs to a national extension, which is invisible by reading the CSV and
    would otherwise survive the build.

    The display returned is the server's preferred term, not whatever string the
    service carried next to the code. That is what keeps verify-curated's fourth
    check (display must be a real designation of the concept) green by
    construction.
    """
    result = lookup(fhir_base, code)
    if result is None:
        return "absent", None
    active, module, names = result
    if not active:
        return "retired", None
    if module != INTL_MODULE:
        return "extension", None
    display = preferred_display(fhir_base, code)
    if not display or display not in names:
        return "no-display", None
    return "ok", display


def preferred_display(fhir_base, code):
    """The concept's preferred term on this server."""
    query = urllib.parse.urlencode({"system": SNOMED, "code": code})
    status, body = http(
        "GET", f"{fhir_base.rstrip('/')}/CodeSystem/$lookup?{query}")
    if status != 200 or not body:
        return None
    for parameter in body.get("parameter", []):
        if parameter["name"] == "display":
            return parameter["valueString"]
    return None


def validate_reject_lists(fhir_base):
    """Every code a reject list names is real, active, and called what it says.

    A reject list fails SILENTLY when it is wrong: a mistyped or misremembered
    SCTID simply never matches, the answer it was meant to decline sails through,
    and nothing says so. That is not hypothetical — a draft constraint for this
    stream carried `225390008` in the belief that it meant "Care", when it means
    `Triage`. So the lists are checked rather than trusted, and a bad entry is
    fatal before any search runs.

    Both lists go through here because both fail the same way. They differ in
    what they are keyed on, not in what a wrong entry costs.
    """
    entries = [(f"DEVICE_CARE_CODES {code} |{display}|", code, display)
               for code, display in DEVICE_CARE_CODES.items()]
    entries += [(f"WRONG_ACTION {query!r} -> {code} |{display}|", code, display)
                for (query, code), (display, _why) in WRONG_ACTION.items()]

    problems = []
    for named, code, expected in sorted(entries):
        result = lookup(fhir_base, code)
        if result is None:
            problems.append(f"    {named}: not known to the server")
            continue
        active, _module, names = result
        if not active:
            problems.append(f"    {named}: retired")
        elif expected not in names:
            problems.append(f"    {named}: server does not call this "
                            f"{expected!r} — it is {sorted(names)[:3]}")
    if problems:
        print("\n  A reject list does not describe this server:", file=sys.stderr)
        for problem in problems:
            print(problem, file=sys.stderr)
        sys.exit("  A reject list that names the wrong concept rejects nothing "
                 "and does so silently. Fix the entries and re-run.")


def validate_wrong_action_queries(labels):
    """Every WRONG_ACTION key names a family query this population produces.

    The other half of the same silent failure: the code can be perfect and the
    entry still decline nothing, because the label it was written about was
    renamed in the IG or because the '#N' collapse means the string sent to the
    service is not the string in the dictionary. Checked against every IG label,
    not the `--only` subset, so a probe run cannot mask it.
    """
    queries = {family_label(label) for label in labels}
    unknown = sorted({q for q, _code in WRONG_ACTION if q not in queries})
    if unknown:
        for query in unknown:
            print(f"    WRONG_ACTION {query!r} matches no family query",
                  file=sys.stderr)
        sys.exit("  An entry that matches no query declines nothing. Re-read "
                 "the row it was written about, then update or delete it.")


# --------------------------------------------------------------------------- #
# Reviewed comments
# --------------------------------------------------------------------------- #


# Prose notes on individual mappings, keyed on (mimic_code, snomed_code).
#
# NOT equivalence. Every mapping this table supplies is `relatedto`, fixed by
# lib/assemble.py, and nothing here can change it. What an entry adds is a
# sentence in ConceptMap.target.comment for a row where the code pair alone would
# mislead a reader.
#
# Keyed on the PAIR and not on the itemid alone, because each note is written
# about one specific target concept. If a re-run moves the target, the note no
# longer describes what it was written about, and apply_comments exits rather
# than carrying it silently onto a different concept. An entry that matches no
# row is fatal, not a no-op.
#
# Comments only: this mechanism deliberately cannot pin a snomed_code. See the
# module docstring on `225322 Dialysis Catheter Insertion Date`, which is exactly
# the row it would be tempting to fix from here.
#
# Empty on the first run: which rows need one is a question about what the
# service actually returned over the whole population, so the entries are written
# after reading the generated table, not guessed before it exists.
COMMENT_OVERRIDES = {}


def apply_comments(rows):
    """Attach the reviewed comments to their rows. Fatal on drift."""
    by_pair = {(r["mimic_code"], r["snomed_code"]): r
               for r in rows if r["snomed_code"]}
    for (code, target), comment in sorted(COMMENT_OVERRIDES.items()):
        row = by_pair.get((code, target))
        if row is None:
            current = next((r for r in rows if r["mimic_code"] == code), None)
            now = ("is no longer in the IG" if current is None else
                   f"now targets {current['snomed_code'] or '(unmapped)'}")
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


def family_label(display):
    """The label with its instance index removed — the unit of search.

    `Impaired Skin  - Dressing Change #1` and `… #9` differ only by an index, so
    they are one question, asked once. See FAMILY_INDEX.
    """
    return FAMILY_INDEX.sub("", display).strip()


def blank_row(code, label):
    row = {c: "" for c in CURATED_COLUMNS + PROVENANCE_COLUMNS
           + LOG_ONLY_COLUMNS}
    row["mimic_code"] = code
    row["mimic_display"] = label
    return row


def search_family(query, fhir_base, service, timeout):
    """One code-search call for one family, its answer gated.

    Returns the fields to copy onto every member of the family, so that members
    differing only by instance index cannot end up on different targets. The
    proposal is recorded whether or not it survives — a family rejected at
    CONFIDENCE_THRESHOLD, at the gate or by DEVICE_CARE_CODES keeps its
    `codesearch_target` and `codesearch_reasoning`, so the committed table shows
    what was considered and on what ground it was declined.
    """
    answer = {c: "" for c in PROVENANCE_COLUMNS + LOG_ONLY_COLUMNS
              + ["snomed_code", "snomed_display", "comment"]}
    answer["codesearch_query"] = query

    confidence = 0.0
    try:
        result = find_code(service, TEMPLATE.format(query), timeout)
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
            # MEANING FIRST, then the score, then the server. The two reject
            # lists come before CONFIDENCE_THRESHOLD because what disqualifies
            # their targets is what the concept MEANS — a fact that no score can
            # change and no server check can see. They come before the gate for
            # the narrower reason that these concepts are real, active and
            # international, so the gate would pass them.
            #
            # The order is not cosmetic; it is what makes the table's own account
            # of its gaps true. Under the previous order — threshold first — 12
            # cap- and tubing-change items whose only proposal was a device-care
            # concept were recorded as `below-threshold`, which reads as "close,
            # and a looser threshold would take it". It would not: those 12 are
            # declined here at any threshold. Reading the near-threshold
            # statistics off the old table therefore overstated what lowering the
            # gate would buy by 12 of 40 rows.
            if match["code"] in DEVICE_CARE_CODES:
                answer["codesearch_status"] = "device-care"
            elif (query, match["code"]) in WRONG_ACTION:
                answer["codesearch_status"] = "wrong-action"
            elif confidence < CONFIDENCE_THRESHOLD:
                answer["codesearch_status"] = "below-threshold"
            else:
                status, display = gate(fhir_base, match["code"])
                answer["codesearch_status"] = status
                if status == "ok":
                    answer.update(snomed_code=match["code"],
                                  snomed_display=display)
                    return answer

    answer["comment"] = declined_comment(answer, confidence)
    return answer


def declined_comment(answer, confidence):
    """Why a row carries no target. load_table requires one, and rightly: an
    empty target is a claim that the source could not answer, and a claim has to
    say what it rests on.

    Phrased against the family query rather than the item label, because that is
    the string the service was actually given.
    """
    asked = answer["codesearch_query"]
    proposal = (f"{answer['codesearch_target']} "
                f"|{answer['codesearch_display']}| at {confidence:.2f}")
    return {
        "no-match": (f"code-search returned no match for {asked!r} within "
                     f"{CONSTRAINT_ECL}."),
        "below-threshold": (f"code-search proposed {proposal} for {asked!r}, "
                            f"below the {CONFIDENCE_THRESHOLD} threshold."),
        "device-care": (f"code-search proposed {proposal} for {asked!r}, a "
                        f"generic device-care concept. It is equally true of "
                        f"this item's insertion, dressing, cap, tubing and wire "
                        f"changes, so mapping it here would make those distinct "
                        f"flowsheet columns indistinguishable."),
        "wrong-action": (f"code-search proposed {proposal} for {asked!r}, but "
                         f"{WRONG_ACTION.get((asked, answer['codesearch_target']), ('', ''))[1]}. "
                         f"The concept is right about the device and wrong about "
                         f"the action, so the mapping would assert something "
                         f"this column does not record."),
        "retired": (f"code-search proposed {proposal} but that concept is "
                    f"retired."),
        "extension": (f"code-search proposed {proposal} but that concept is not "
                      f"in the SNOMED international core."),
        "absent": f"code-search proposed {proposal} but that code is not known.",
        "no-display": (f"code-search proposed {proposal} but it has no usable "
                       f"display."),
    }.get(answer["codesearch_status"], f"code-search: {answer['codesearch_status']}.")


# --------------------------------------------------------------------------- #
# Reporting
# --------------------------------------------------------------------------- #


def report(rows, families):
    """What the run found. Printed so it can be pasted into a write-up."""
    mapped = [r for r in rows if r["snomed_code"]]
    print(f"\n  {len(rows)} item(s) in {len(families)} famil(ies): "
          f"{len(mapped)} mapped, {len(rows) - len(mapped)} declared unmapped")

    statuses = {}
    for row in rows:
        statuses[row["codesearch_status"]] = \
            statuses.get(row["codesearch_status"], 0) + 1
    print("\n  code-search answer status")
    for status, count in sorted(statuses.items()):
        print(f"    {status:<16} {count:>4}")

    scored = sorted(float(r["codesearch_confidence"]) for r in rows
                    if r["codesearch_confidence"])
    if scored:
        print(f"\n  code-search confidence, {len(scored)} answered")
        buckets = [(1.0, 1.01), (0.9, 1.0), (0.8, 0.9), (0.7, 0.8), (0.0, 0.7)]
        for low, high in buckets:
            hits = [s for s in scored if low <= s < high]
            label = f"{low:.2f}" if high > 1.0 else f"{low:.2f}–{high:.2f}"
            print(f"    {label:<12} {len(hits):>4}  {'#' * len(hits)}")
        print(f"    threshold {CONFIDENCE_THRESHOLD}: "
              f"{sum(1 for s in scored if s >= CONFIDENCE_THRESHOLD)} kept, "
              f"{sum(1 for s in scored if s < CONFIDENCE_THRESHOLD)} dropped")

    # How many source items share a target. This population is expected to
    # concentrate — one dressing-replacement concept legitimately answers the
    # dressing changes of several devices — and a target answering an implausible
    # number of items is the shape of a bad answer, so it is printed rather than
    # left to be discovered.
    shared = {}
    for row in mapped:
        shared.setdefault((row["snomed_code"], row["snomed_display"]),
                          []).append(row["mimic_code"])
    crowded = sorted(((len(v), k) for k, v in shared.items()), reverse=True)
    print(f"\n  {len(shared)} distinct target(s) for {len(mapped)} mapped item(s)")
    for count, (code, display) in crowded[:8]:
        if count > 1:
            print(f"    {count:>3} items -> {code:<12} {display[:48]}")

    commented = [r for r in rows if r["snomed_code"] and r["comment"]]
    if commented:
        print(f"\n  {len(commented)} mapped row(s) carrying a reviewed comment")
        for row in commented:
            print(f"    {row['mimic_code']} {row['mimic_display'][:34]:<34} "
                  f"-> {row['snomed_code']:<11} {row['snomed_display'][:44]}")

    unmapped = [r for r in rows if not r["snomed_code"]]
    print(f"\n  {len(unmapped)} unmapped, declared:")
    for row in unmapped:
        print(f"    {row['mimic_code']} {row['mimic_display'][:40]:<40} "
              f"{row['codesearch_status']}")


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #


def main():
    parser = argparse.ArgumentParser(description=__doc__)
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
    args = parser.parse_args()

    configure_tls(args.ca_bundle, args.insecure)
    if not args.fhir_base:
        sys.exit("  no --fhir-base and ONTOSERVER_URL unset — the validation "
                 "gate needs a terminology server.")

    codes = ig_codes()
    items = sorted(codes.items())
    if args.only:
        wanted = {c.strip() for c in args.only.split(",") if c.strip()}
        unknown = wanted - set(codes)
        if unknown:
            sys.exit(f"  --only names code(s) not in the IG: {sorted(unknown)}")
        items = [i for i in items if i[0] in wanted]
        args.dry_run = True

    rows_by_code = {code: blank_row(code, label) for code, label in items}

    # One search per family, not per item. Sorted so the run order — and so the
    # order errors are reported in — is the same on every invocation.
    families = {}
    for code, label in items:
        families.setdefault(family_label(label), []).append(code)
    queries = sorted(families)

    print(f"  {len(items)} IG code(s)"
          + (f" (subset of {len(codes)}, --only)" if args.only else ""))
    print(f"  families:   {len(items)} item(s) collapse to {len(queries)} "
          f"search(es) on the '#N' index")
    print(f"  gate:       {args.fhir_base}")
    print(f"  service:    {args.service}")
    print(f"  ECL:        {CONSTRAINT_ECL}")
    print(f"  template:   {TEMPLATE}")
    print(f"  threshold:  {CONFIDENCE_THRESHOLD}")
    print(f"  rejects:    {len(DEVICE_CARE_CODES)} device-care concept(s), "
          f"{len(WRONG_ACTION)} wrong-action pair(s)")
    print(f"  comments:   {len(COMMENT_OVERRIDES)}\n")

    # Before any search: a reject list that names the wrong concept — or the
    # wrong label — rejects nothing and says nothing about it. Queries are
    # checked against every IG label rather than `items`, so an `--only` probe
    # cannot mask a stale entry.
    validate_reject_lists(args.fhir_base)
    validate_wrong_action_queries(codes.values())

    def work(query):
        answer = search_family(query, args.fhir_base, args.service, args.timeout)
        print(f"    {query[:44]:<44} {answer['codesearch_status']:<16} "
              f"{answer['snomed_code'] or '—':<12} "
              f"{answer['snomed_display'][:36]}", flush=True)
        return answer

    with concurrent.futures.ThreadPoolExecutor(args.workers) as pool:
        answers = dict(zip(queries, pool.map(work, queries)))

    # Fan each family's one answer back across its members. This is what makes
    # `Impaired Skin - Dressing Change #1` and `#9` disagreeing unrepresentable.
    for query, members in families.items():
        for code in members:
            rows_by_code[code].update(answers[query])

    # Sorted by mimic_code so a re-run diffs only where an answer changed, not
    # wherever the thread pool happened to finish first.
    rows = sorted(rows_by_code.values(), key=lambda r: r["mimic_code"])

    # A transport failure is not an answer. Writing a table whose gaps are half
    # findings and half a service that stopped answering would ship something
    # that reads like a result and is not one, so a partial run writes nothing.
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

    # The invariant FAMILY_INDEX exists to guarantee, asserted rather than
    # assumed. The fan-out above makes divergence structurally impossible, so
    # this can only fire if the grouping and the fan-out ever stop agreeing —
    # and the whole point of the rule is that a reader should not have to trust
    # that they do.
    diverged = {q: sorted({rows_by_code[c]["snomed_code"] or "(unmapped)"
                           for c in members})
                for q, members in families.items()
                if len({rows_by_code[c]["snomed_code"] for c in members}) > 1}
    if diverged:
        for query, targets in sorted(diverged.items()):
            print(f"    {query}: {targets}", file=sys.stderr)
        sys.exit(f"  {len(diverged)} famil(ies) whose members ended up on "
                 f"different targets, which the family collapse exists to "
                 f"prevent. NOT writing {OUT_CSV.name}.")

    # After the failure gate, so that a run where the service dropped out
    # reports the transport failure rather than a wall of comments that could
    # not match because their targets never arrived.
    apply_comments(rows)
    report(rows, families)

    if args.dry_run:
        print("\n  --dry-run: nothing written")
        return

    columns = CURATED_COLUMNS + PROVENANCE_COLUMNS
    with open(OUT_CSV, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns)
        writer.writeheader()
        writer.writerows({c: row[c] for c in columns} for row in rows)
    print(f"\n  wrote {OUT_CSV.relative_to(TERM.parents[1])}")

    LOG_JSON.parent.mkdir(parents=True, exist_ok=True)
    LOG_JSON.write_text(json.dumps({
        "constraint_ecl": CONSTRAINT_ECL,
        "template": TEMPLATE,
        "confidence_threshold": CONFIDENCE_THRESHOLD,
        # The stated rules that are not the three above, so the log records the
        # whole setup rather than most of it.
        "device_care_codes": DEVICE_CARE_CODES,
        "wrong_action": {f"{query}->{code}": {"display": display, "why": why}
                         for (query, code), (display, why)
                         in sorted(WRONG_ACTION.items())},
        "family_index_pattern": FAMILY_INDEX.pattern,
        "families": {query: sorted(members)
                     for query, members in sorted(families.items())},
        # Every hand decision that touched this table. The rest is whatever the
        # service said, gated.
        "comment_overrides": {f"{code}->{target}": comment
                              for (code, target), comment
                              in sorted(COMMENT_OVERRIDES.items())},
        "fhir_base": args.fhir_base,
        # The service's own configuration at the end of the run. Recorded
        # because a `cached` path means the answer was produced by whatever model
        # was configured when it was first asked, which is not necessarily this
        # one — so this pins the run, not every row.
        "codesearch_service": service_info(args.service),
        "rows": rows,
    }, indent=2) + "\n")
    print(f"  wrote {LOG_JSON.relative_to(TERM.parents[1])}")


if __name__ == "__main__":
    main()
