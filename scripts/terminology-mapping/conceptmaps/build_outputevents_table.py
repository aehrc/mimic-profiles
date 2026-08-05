#!/usr/bin/env python3
"""Generate conceptmaps/outputevents-loinc.csv — the 77 ICU output items -> LOINC.

The third generated table, and the second to target LOINC. It follows
build_micro_susc_table.py in shape — network generation is a separate explicit
target, the build stays offline and byte-reproducible — and differs from it in
the places a stream is allowed to differ: the constraint, the template, the gate,
and one thing neither earlier stream needed, a pre-filter (see PRE-FILTER below).

WHAT THE SOURCE CODES MEAN. mimic-outputevents-d-items holds 77 itemids from
MIMIC's ICU `d_items` dictionary, bound to Observation.code on
MimicObservationOutputevents. Every one of them is a VOLUME OF FLUID OUT VIA ONE
ROUTE, and the label names the route's device or site rather than the
observation: `226559 Foley`, `226599 Jackson Pratt #1`, `226603 T Tube`,
`226610 Lumbar`, `226626 OR EBL`. That is the same failure shape as the
procedureevents labels — the observation is implicit and the device is explicit —
so no rule can derive these and the mapping is data.

CONSTRAINT_VCL. LOINC's intake/output OUT class is the counterpart of ABXBACT for
this stream, and the narrowing is steep:

    CLASS matching IO_OUT.*                       175 codes
      + STATUS = ACTIVE                           170   (drops 5 `Deprecated
                                                         Fluid output.wound
                                                         drain: VRat: …`)
      + PROPERTY = Vol                              34

`PROPERTY = Vol` is the filter that carries this stream, and it works by matching
the source axis to the target axis: 73 of the 77 items record `mL` in the
dictionary, so admitting only volume codes rejects, in one move, the 91 `VRat`
timed-rate variants (`Fluid output chest tube 24 hour`), `Output.stool [Mass]`
in grams, the `[Appearance]` nominal codes, the `[#]` counts and
`Fluid output wound drain identifier [Identifier]`. Those are the
`Hemoglobin, Blood -> …by Oximetry` inflation family the parent issue predicted,
and they are exactly what a CLASSTYPE/STATUS filter cannot catch: every one of
them is a valid, active, in-class LOINC code that asserts a timing, a property or
a scale MIMIC does not record here.

Note CLASS is declared STRING on Velonto, not code-typed, so the in-set form
(`CLASS^{"IO_OUT.MOLEC","IO_OUT.ATOM"}`) is rejected with a CompilerException and
the regex form is required. Both spell the same 34 codes.

At 34 codes the constraint is under code-search's `small_valueset_threshold`
(50), so the service puts the whole enumerated set in front of the model rather
than retrieving a sample of it.

Verified end to end before this script was written, the check
build_micro_susc_table.py documents: asked for `Sodium [Moles/volume] in Serum or
Plasma` and `Hemoglobin [Mass/volume] in Blood` under this constraint,
code-search returns NO MATCH for both, so the constraint is genuinely applied
rather than silently dropped — the failure that would have made every check here
pass while measuring nothing.

Why the constraint and not the confidence: asked against `http://loinc.org/vs`
instead, `Stool` returns the Part `LP7604-4 |Stool|` at confidence 1.0, `Lumbar`
the answer-list code `LA22230-9 |Lumbar|` at 1.0, `Foley` the device
`LA25775-0 |Foley catheter|` at 0.95, `Chest Tube #1` the Part
`LP7139-1 |Chest tube|`, and `Jackson Pratt #1` the report code
`11533-7 |Surgical drains|`. None is a legal Observation.code, THE WORST OF THEM
SCORE HIGHEST, and only the constraint separates them. This is the
`Foley Catheter` lesson of build_d_items_table.py repeating on the LOINC side.

TEMPLATE. Load-bearing here, unlike micro-susc where CLASS=ABXBACT supplied all
the context: under this constraint the bare labels `Foley`, `Lumbar`, `T Tube`
and `Red Rubber` all return NO MATCH, because the label names a device and leaves
the measurement implicit. But a template that over-specifies the route harms rows
that are not route-shaped. Four were run over the discriminating labels:

    bare                                            Foley/Lumbar/T Tube: no match
    "…from the drain, tube or collection route: {}"  breaks OR EBL -> misc
    "ICU flowsheet output volume recorded for: {}"   <- kept
    "Volume of fluid output measured in …: {}"       breaks OR EBL, Red Rubber

The two rejected templates push rows onto `9257-7 |Fluid output total Measured|`,
which is actively wrong rather than merely vague — see TOTAL_CODES. The kept
sentence never did, and it states a fact about the source table (an ICU flowsheet
column recording an output volume) rather than a judgement about any item.

PRE-FILTER — the one piece of machinery neither earlier generator has. The
dictionary says what each item actually records, and 5 of the 77 do not record a
volume at all:

    224458  Drain Output_ingr                 param_type Ingredient
    226586  Stool Estimate                    param_type Text
    226713  Incontinent/voids (estimate)      param_type Text
    227487  GU Irrigant Type                  param_type Text
    228103  Stool containment device placed   param_type Date and time

Those are declined WITHOUT being sent to code-search, which is the treatment the
parent issue prescribes for the labitems that have no searchable text. It earns
its place with evidence rather than tidiness: `228103 Stool containment device
placed` records a TIMESTAMP of a device placement, and the kept template gets it
`9217-1 |Output.stool [Volume]|` at 0.85 — an answer that passes the threshold
AND the gate, because the target is a perfectly good volume code and only the
source is wrong. Nothing downstream of the search could catch that.

Two of the five are recoverable by moving a stated setting rather than for want
of an answer: `Stool Estimate` and `Incontinent/voids (estimate)` are real output
observations recorded ordinally, and LOINC has `81668-6 |Incontinent voids [#]|`
— excluded by PROPERTY = Vol. Widening the constraint to admit `Num` would reach
them, at the cost of readmitting the count and mass variants to every other row.

The dictionary is MIMIC-IV demo 2.2, openly downloadable with no PhysioNet
credentialing, and it ships the ICU dictionary whole rather than subset. All 77
IG codes resolve in it and no label differs, so the join doubles as a
version-consistency check and both halves of it are fatal: a missing itemid or a
drifted label means the IG and the dictionary describe different releases, and
the item whose label moved is precisely the one whose mapping a human should read
again. A missing dictionary is fatal too — running without the pre-filter would
send the datetime item to the service and produce the confident wrong answer
above.

THE GATE is build_micro_susc_table.py's: membership of the constraint asserted
with $validate-code against the VCL URL rather than assumed from the service
having been asked nicely, which subsumes STATUS = ACTIVE because the constraint
carries that filter, and the target display replaced with the server's own
LONG_COMMON_NAME so verify-curated's display check passes by construction. LOINC
needs no `active` or `international core module` check: both SNOMED analogues are
expressible on the LOINC side, and LOINC has no national extensions.

TOTAL_CODES is the one check the constraint cannot make, and the analogue of
micro-susc's `<substance> [Susceptibility]` shape check. `9256-9` and `9257-7`
|Fluid output total| mean every route summed. A MIMIC outputevents row is always
ONE route, so a row mapped there does not merely lose precision — it makes any
aggregation over Observation.code double-count, once in the route and once in the
total. It is not hypothetical: `226633 Pre-Admission` comes back `9257-7` at 0.85
under the kept template.

WHY LOINC ALONE, with no SNOMED fallback. The parent issue proposed "LOINC
volume, SNOMED fallback". Probed under `<<363787002 |Observable entity|` with the
same template, the fallback rescues NOTHING the LOINC constraint declines:
`Mediastinal`, `GU Irrigant Type`, `GU Irrigant Volume In` and `Stool containment
device placed` are all NO MATCH there too, and so is `Chest Tube #1`, which LOINC
answers at 0.95. The single label SNOMED does answer, `Foley`, it answers less
precisely (`364202003 |Measure of urine output|` at 0.85, against LOINC's
`9187-6 |Urine output|` at 0.92). Against zero coverage gained, a mixed-target
table would need per-row `target_system` columns and the lib/ machinery to read
them, which does not exist — assemble.build_groups resolves one target system per
source. So this table is single-target and says so in its own header.

EQUIVALENCE is not this script's concern. Every mapping a table supplies is
`relatedto`, set by lib/assemble.py when it builds the group.

Why it is NOT part of `make mappings`: same as the two generators before it. It
needs the network and an LLM-backed service, and it WRITES a build input.
Determinism lives in the split — this runs by hand, its output is committed, and
`make mappings` reads the committed CSV and never a server.

    make outputevents-table ARGS=--insecure

Usage:
  uv run scripts/terminology-mapping/conceptmaps/build_outputevents_table.py
  uv run .../build_outputevents_table.py --only 226559,226610 --insecure
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

# LOINC's intake/output OUT classes, active codes, volume property only. See the
# module docstring for the three counts and why PROPERTY is the one that carries
# this stream. LP6893-4 is the `Vol` property Part; the axes are spelled as Part
# codes rather than short names because that is what the CodeSystem stores.
#
# The regex form is not a stylistic choice: CLASS is declared STRING on Velonto,
# so the in-set form is rejected outright.
CONSTRAINT_VCL = '(http://loinc.org)(CLASS/"IO_OUT.*",STATUS=ACTIVE,PROPERTY=LP6893-4)'

# One sentence, identical for all items that are asked about. Chosen over three
# alternatives by running all four over the labels that discriminate between
# them — see the module docstring.
TEMPLATE = "ICU flowsheet output volume recorded for: {}"

# Below this, code-search's answer is discarded and the item is left unmapped.
# Matches the two generators before it. Every observed answer landed between
# 0.85 and 0.95, so nothing in this population sits near the boundary; the
# distribution is printed at the end of every run so it can be moved with
# evidence rather than by taste.
CONFIDENCE_THRESHOLD = 0.8

# `Fluid output total` sums every route. A MIMIC outputevents row is one route,
# so mapping one here would make any aggregation over Observation.code count the
# same millilitres twice. Rejected as a target for that reason, and the item left
# unmapped with the proposal recorded — see the module docstring.
TOTAL_CODES = {
    "9256-9": "Fluid output total Estimated",
    "9257-7": "Fluid output total Measured",
}

# An item is asked about only if the dictionary says it records a volume in
# millilitres, which is what PROPERTY = Vol asserts on the target side. The 5
# items that fail are declined without being searched — the module docstring
# names them and says why the rule is evidenced rather than tidy.
SEARCHABLE_PARAM_TYPE = "Numeric"
SEARCHABLE_UNIT = "mL"

# An instance index on an ICU flowsheet column. `Chest Tube #1` … `#4` are four
# physical drains recorded in four columns of one chart, not four different
# observations, so the family is searched ONCE on the stripped label and the
# answer is fanned back across its members. 77 items collapse to 62 families.
#
# This is a correctness fix, not an optimisation, and it was added after a first
# run shipped without it. Asked per item, two families came back internally
# inconsistent — `Pigtail #1` on `9129-8 |Fluid output chest tube|` and `#2` on
# `9161-1 |Fluid output miscellaneous Measured|`, and `Sump #1` on
# `9203-1 |Fluid output wound drain|` while `#2` got no match at all. Nothing
# distinguishes those columns but the index, so a map where they disagree is
# wrong however plausible each row looks alone. Searching the family makes the
# disagreement unrepresentable rather than merely unlikely.
#
# It is a regex applied to every label identically, so it is a stated rule and
# not a per-item judgement. `mimic_display` in the committed table is still the
# IG's exact label — load_curated requires that — and `codesearch_query` records
# what was actually sent, so the collapse is visible in the CSV.
FAMILY_INDEX = re.compile(r"\s*#\d+")

# --------------------------------------------------------------------------- #
# Paths and provenance
# --------------------------------------------------------------------------- #

TERM = Path(__file__).resolve().parents[1]
OUT_CSV = Path(__file__).resolve().parent / "outputevents-loinc.csv"
LOG_JSON = TERM / "output" / "outputevents-generation-log.json"

# MIMIC-IV demo 2.2, the openly downloadable release that ships the ICU
# dictionary whole. Read for the pre-filter only: the mapping itself never
# depends on it, and the build never reads it at all.
D_ITEMS_GZ = TERM / "sources" / "mimic-iv-demo" / "2.2" / "icu" / "d_items.csv.gz"

# This table targets LOINC, so it says so in its own header rather than
# borrowing the SNOMED naming. lib.curated.load_table normalises both to
# `target_code` / `target_display` for the build.
TARGET_COLUMNS = ("loinc_code", "loinc_display")
CURATED = curated_columns(TARGET_COLUMNS)

# What the service proposed on every row it was asked about, including the rows
# where the proposal was then rejected by the threshold, the constraint or
# TOTAL_CODES — so that "this item is unmapped" is auditable in the committed
# diff. The pre-filtered rows carry these blank, which is what distinguishes
# "asked and declined" from "never asked, and the comment says why".
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
    """(code, display) for the 77 items, read from the IG's own ValueSet.

    Routed through the observation builder's own SOURCES declaration for the
    reason the two generators before it give: lib.curated.load_table rejects a
    row whose display differs from the IG's by so much as a character, so the
    generator and the build must read displays through the same function or the
    table this writes can fail the build that reads it.
    """
    from conceptmaps.build_observation_cm_vs import SOURCES

    source = next(s for s in SOURCES if s.get("table") == OUT_CSV)
    return dict(source_concepts(source))


def dictionary(expected):
    """itemid -> d_items row, checked against the IG enumeration.

    Both halves of the join are fatal. A missing itemid or a drifted label means
    the IG and the dictionary describe different MIMIC releases, and the item
    whose label moved is precisely the one whose mapping a human should read
    again — the same check, for the same reason, that load_table makes on the
    committed table.
    """
    if not D_ITEMS_GZ.is_file():
        sys.exit(f"  {D_ITEMS_GZ} not found. It carries the param_type and "
                 f"unitname the pre-filter reads, and running without it would "
                 f"send the items that record no volume to code-search — which "
                 f"answers them confidently and wrongly. Download MIMIC-IV demo "
                 f"2.2 (no credentialing needed):\n"
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


def records_a_volume(item):
    """(True, '') if this item should be asked about, else (False, reason)."""
    if item["param_type"] != SEARCHABLE_PARAM_TYPE:
        return False, (f"param_type is {item['param_type']!r}, not "
                       f"{SEARCHABLE_PARAM_TYPE!r}")
    if item["unitname"] != SEARCHABLE_UNIT:
        return False, (f"unitname is {item['unitname']!r}, not "
                       f"{SEARCHABLE_UNIT!r}")
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

    Retries transport failures, for the reason the two generators before it
    give: a dropped connection is not an answer, and a run that quietly mixes
    'no match' with 'the service was not running' produces a table that
    understates coverage and reads exactly like a real result. Exhausted retries
    raise, and main() refuses to write the CSV.
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
    and demonstrably does, but 'the service was asked nicely' is not a property a
    committed table should rest on. It subsumes STATUS = ACTIVE, and the
    PROPERTY = Vol filter with it, because the constraint carries both.
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
    """
    if not in_constraint(fhir_base, code):
        return "out-of-constraint", None
    if code in TOTAL_CODES:
        return "total", None
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
# returned, gated'.
#
# Empty because no row of this table has been reviewed yet: the first run of this
# script is the dry run whose output decides which rows need a note. Several
# candidates are already known from the probes — `226584 Ileoconduit` proposing a
# gastrointestinal ostomy where an ileal conduit is a URINARY diversion, and the
# several distinct drains (`Tap`, `Sump`, `Pigtail`, `Red Rubber`, `Davol`) that
# collapse onto `9161-1 |Fluid output miscellaneous Measured|` and will therefore
# merge under any aggregation by Observation.code.
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


def family_label(display):
    """The label with its instance index stripped — the string actually searched.

    `Chest Tube #1` .. `#4` become one `Chest Tube`. See FAMILY_INDEX for why the
    family and not the item is the unit of search.
    """
    return FAMILY_INDEX.sub("", display).strip()


def blank_row(code, label):
    row = {c: "" for c in CURATED + PROVENANCE_COLUMNS + LOG_ONLY_COLUMNS}
    row["mimic_code"] = code
    row["mimic_display"] = label
    return row


def decline_unasked(row, why_not):
    """A row the pre-filter declined. The codesearch_* columns stay blank, which
    is what distinguishes "asked and declined" from "never asked"."""
    row["codesearch_status"] = "not-a-volume"
    row["comment"] = (
        f"Not sent to code-search: MIMIC's d_items dictionary records no volume "
        f"for this item ({why_not}), so no member of {CONSTRAINT_VCL} — every "
        f"one of which is a volume — can be its target.")
    return row


def search_family(query, fhir_base, service, timeout):
    """One code-search call for one family, its answer gated.

    Returns the fields to copy onto every member of the family, so that members
    differing only by instance index cannot end up on different targets. The
    proposal is recorded whether or not it survives — a family rejected at
    CONFIDENCE_THRESHOLD, at the constraint or by TOTAL_CODES keeps its
    `codesearch_target` and `codesearch_reasoning`, so the committed table shows
    what was considered and on what ground it was declined.
    """
    answer = {c: "" for c in PROVENANCE_COLUMNS + LOG_ONLY_COLUMNS
              + ["loinc_code", "loinc_display", "comment"]}
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
                     f"{CONSTRAINT_VCL}."),
        "below-threshold": (f"code-search proposed {proposal} for {asked!r}, "
                            f"below the {CONFIDENCE_THRESHOLD} threshold."),
        "out-of-constraint": (f"code-search proposed {proposal} but that code "
                              f"is not a member of {CONSTRAINT_VCL}."),
        "absent": f"code-search proposed {proposal} but that code is not known.",
        "total": (f"code-search proposed {proposal}, which sums fluid output "
                  f"over every route. This item records one route, so mapping "
                  f"it there would make any total over Observation.code count "
                  f"the same volume twice."),
    }.get(answer["codesearch_status"],
          f"code-search: {answer['codesearch_status']}.")


# --------------------------------------------------------------------------- #
# Reporting
# --------------------------------------------------------------------------- #


def report(rows):
    """What the run found. Printed so it can be pasted into a write-up."""
    mapped = [r for r in rows if r["loinc_code"]]
    asked = [r for r in rows if r["codesearch_status"] != "not-a-volume"]
    print(f"\n  {len(rows)} item(s): {len(mapped)} mapped, "
          f"{len(rows) - len(mapped)} declared unmapped "
          f"({len(rows) - len(asked)} of them never asked — see pre-filter)")

    statuses = {}
    for row in rows:
        statuses[row["codesearch_status"]] = \
            statuses.get(row["codesearch_status"], 0) + 1
    print("\n  answer status")
    for status, count in sorted(statuses.items()):
        print(f"    {status:<18} {count:>4}")

    # One confidence per FAMILY, not per item: counting a 4-member family four
    # times would overstate how many independent answers the run actually got.
    by_query = {}
    for row in rows:
        if row["codesearch_confidence"]:
            by_query[row["codesearch_query"]] = \
                float(row["codesearch_confidence"])
    scored = sorted(by_query.values())
    if scored:
        print(f"\n  code-search confidence, {len(scored)} famil(ies) answered")
        buckets = [(1.0, 1.01), (0.9, 1.0), (0.8, 0.9), (0.7, 0.8), (0.0, 0.7)]
        for low, high in buckets:
            hits = [s for s in scored if low <= s < high]
            label = f"{low:.2f}" if high > 1.0 else f"{low:.2f}–{high:.2f}"
            print(f"    {label:<12} {len(hits):>4}  {'#' * len(hits)}")
        print(f"    threshold {CONFIDENCE_THRESHOLD}: "
              f"{sum(1 for s in scored if s >= CONFIDENCE_THRESHOLD)} kept, "
              f"{sum(1 for s in scored if s < CONFIDENCE_THRESHOLD)} dropped")

    # How many distinct targets the mapped rows share. A generic target is not
    # wrong, but several routes landing on one code means a consumer aggregating
    # by Observation.code merges them, so it is worth seeing at a glance.
    if mapped:
        shared = {}
        for row in mapped:
            shared.setdefault((row["loinc_code"], row["loinc_display"]),
                              []).append(row)
        print(f"\n  {len(mapped)} mapped row(s) over {len(shared)} distinct "
              f"target(s)")
        for (code, display), group in sorted(
                shared.items(), key=lambda kv: (-len(kv[1]), kv[0][0])):
            if len(group) > 1:
                labels = ", ".join(r["mimic_display"] for r in group)
                print(f"    {code:<10} {display[:44]:<46} {len(group):>2}  "
                      f"{labels[:70]}")

    commented = [r for r in rows if r["loinc_code"] and r["comment"]]
    if commented:
        print(f"\n  {len(commented)} mapped row(s) carrying a reviewed comment")
        for row in commented:
            print(f"    {row['mimic_code']} {row['mimic_display'][:26]:<26} "
                  f"-> {row['loinc_code']:<10} {row['loinc_display'][:44]}")

    unmapped = [r for r in rows if not r["loinc_code"]]
    if unmapped:
        print(f"\n  {len(unmapped)} unmapped, declared:")
        for row in unmapped:
            print(f"    {row['mimic_code']} {row['mimic_display'][:30]:<32} "
                  f"{row['codesearch_status']}")


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
    args = parser.parse_args()

    configure_tls(args.ca_bundle, args.insecure)
    if not args.fhir_base:
        sys.exit("  no --fhir-base and ONTOSERVER_URL unset — the validation "
                 "gate needs a terminology server.")

    codes = ig_codes()
    d_items = dictionary(codes)
    items = sorted(codes.items())
    if args.only:
        wanted = {c.strip() for c in args.only.split(",") if c.strip()}
        unknown = wanted - set(codes)
        if unknown:
            sys.exit(f"  --only names code(s) not in the IG: {sorted(unknown)}")
        items = [i for i in items if i[0] in wanted]
        args.dry_run = True

    # The pre-filter runs first, so an item that records no volume is declined
    # without joining a family and cannot drag a search along with it.
    rows_by_code, searchable = {}, {}
    for code, label in items:
        row = blank_row(code, label)
        ok, why_not = records_a_volume(d_items[code])
        if ok:
            searchable[code] = row
        else:
            decline_unasked(row, why_not)
        rows_by_code[code] = row

    # One search per family, not per item. Sorted so the run order — and so the
    # order errors are reported in — is the same on every invocation.
    families = {}
    for code, row in searchable.items():
        families.setdefault(family_label(row["mimic_display"]), []).append(code)
    queries = sorted(families)

    print(f"  {len(items)} IG code(s)"
          + (f" (subset of {len(codes)}, --only)" if args.only else ""))
    print(f"  dictionary: {D_ITEMS_GZ.relative_to(TERM.parents[1])} "
          f"({len(d_items)} matched, 0 label drift)")
    print(f"  pre-filter: {len(searchable)} record "
          f"{SEARCHABLE_PARAM_TYPE}/{SEARCHABLE_UNIT} and will be asked; "
          f"{len(items) - len(searchable)} declined unasked")
    print(f"  families:   {len(searchable)} item(s) collapse to {len(queries)} "
          f"search(es) on the '#N' index")
    print(f"  gate:       {args.fhir_base}")
    print(f"  service:    {args.service}")
    print(f"  constraint: {CONSTRAINT_VCL}")
    print(f"  template:   {TEMPLATE}")
    print(f"  threshold:  {CONFIDENCE_THRESHOLD}")
    print(f"  total-codes rejected: {', '.join(sorted(TOTAL_CODES))}")
    print(f"  comments:   {len(COMMENT_OVERRIDES)}\n")

    def work(query):
        answer = search_family(query, args.fhir_base, args.service,
                               args.timeout)
        members = sorted(families[query])
        fanned = ""
        if len(members) > 1:
            labels = ", ".join(rows_by_code[c]["mimic_display"] for c in members)
            fanned = f"x{len(members)} {labels[:40]}"
        print(f"    {query[:30]:<30} {answer['codesearch_status']:<18} "
              f"{answer['loinc_code'] or '—':<10} "
              f"{answer['loinc_display'][:34]:<36} {fanned}", flush=True)
        return answer

    with concurrent.futures.ThreadPoolExecutor(args.workers) as pool:
        answers = dict(zip(queries, pool.map(work, queries)))

    # Fan each family's one answer back across its members. This is what makes
    # `Pigtail #1` and `Pigtail #2` disagreeing unrepresentable.
    for query, members in families.items():
        for code in members:
            rows_by_code[code].update(answers[query])

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

    # The invariant FAMILY_INDEX exists to guarantee, asserted rather than
    # assumed. The fan-out above makes divergence structurally impossible, so
    # this can only fire if the grouping and the fan-out ever stop agreeing —
    # and the whole point of the rule is that a reader should not have to trust
    # that they do.
    diverged = {q: sorted({rows_by_code[c]["loinc_code"] or "(unmapped)"
                           for c in members})
                for q, members in families.items()
                if len({rows_by_code[c]["loinc_code"] for c in members}) > 1}
    if diverged:
        for query, targets in sorted(diverged.items()):
            print(f"    {query}: {targets}", file=sys.stderr)
        sys.exit(f"  {len(diverged)} famil(ies) whose members ended up on "
                 f"different targets, which the family collapse exists to "
                 f"prevent. NOT writing {OUT_CSV.name}.")

    apply_comments(rows)
    report(rows)

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
        "total_codes_rejected": TOTAL_CODES,
        "pre_filter": {"param_type": SEARCHABLE_PARAM_TYPE,
                       "unitname": SEARCHABLE_UNIT,
                       "dictionary": str(D_ITEMS_GZ.relative_to(TERM.parents[1])),
                       "declined_unasked": sorted(
                           set(codes) - set(searchable))},
        # Which items shared a search, so the collapse is auditable without
        # re-deriving the regex.
        "family_index": FAMILY_INDEX.pattern,
        "families": {query: sorted(members)
                     for query, members in sorted(families.items())
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
