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
        constraint. Two categories do not, and are pre-filtered — see BOTH
        PRE-SEARCH DECLINES.

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

THE LOINC CONSTRAINT IS THE UNION OF CLASSTYPE 1 AND 2, and that is a change of
mind recorded here because the reasoning matters. Probing on one code-search
deployment, `Heart rate Alarm - High` came back as a UNION-ONLY answer — both
narrow class passes declined it and the union proposed `19946-3 |Maximum heart
rate setting Apnea Monitor Alarm|`, a code that is itself CLASSTYPE=2 and was
therefore inside the clinical pass all along. That is the merged-constraint
failure build_micro_test_table.py documents, and it argued for two disjoint
passes with an exactly-one-may-answer rule.

It did not reproduce on the deployment that generates this table. There, the
clinical pass finds `19946-3` directly, the laboratory pass finds `718-7`
directly, and the union returns exactly what the correct narrow pass returns —
inventing nothing and suppressing nothing, stable over three runs. With no
measured harm from merging, the split would be complexity without a correctness
argument, so this stream uses ONE union pass. The first full run's unmapped CSV
is a far better sample than any probe for revisiting that, and it is where a
merge pathology would show up across all 2,341 queries rather than two.

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

BOTH PRE-SEARCH DECLINES are read off the dictionary's `category` column and
applied to every item identically — the build_labevents_table.py pattern, where
an item the dictionary disqualifies is declined WITHOUT being searched because a
search it should not have been sent would be answered confidently anyway.

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

Both are uniform properties of a dictionary column, not lists of labels seen to
come back wrong — which is the distinction build_micro_test_table.py draws when
it declines to write a reject list, and the reason those two categories are
pre-filtered while the other ~360 note, restraint and workflow items are
searched normally and expected to decline on the constraint.

ONE QUERY PER COLLAPSED LABEL, 2,811 searchable items collapsing to 2,172
searches. 629 of the 2,982 labels carry an instance index (`Impaired Skin Site
#1` … `#10`, `Angio Site # 2`), and stripping `#\s*\d+` leaves 94 families. This
is a correctness rule and not an optimisation, the same one
build_micro_test_table.py and build_labevents_table.py make: nothing
distinguishes `Pressure Ulcer Stage #3` from `#7` but the index, so a map where
they receive different targets is wrong however plausible each row looks alone.
The fan-out makes divergence unrepresentable and main() asserts it anyway.

The collapsed label is also the whole query key, which was measured rather than
assumed: keying on (collapsed label, category) yields the identical 2,341
distinct keys over the full population, i.e. no collapsed label spans two
categories, so category can add nothing to the key. That matters because the
template sends the label alone — a key finer than the text sent would issue two
identical searches and invite them to disagree.

THE GATE is per system, because the two terminologies fail differently. LOINC:
membership asserted with $validate-code against the constraint rather than
assumed from the service having been asked nicely, and the display replaced with
the server's own LONG_COMMON_NAME. SNOMED: the three checks
verify_curated_snomed.py enforces — exists, is active, is in the international
core module rather than a national extension — plus the server's preferred term
as the display. LOINC needs no active or extension check: STATUS=ACTIVE is
carried by the constraint itself and LOINC has no national extensions.

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

# LOINC's Laboratory AND Clinical class types, active codes only — 85,008 of
# LOINC's 247,255 (60,009 + 24,999, which the server's $expand confirms sum
# exactly, so neither class is silently dropped by the regex form).
#
# BOTH classes, because this population spans both: `category = Labs` is 160
# bedside analytes whose targets are CLASSTYPE=1 only, and the vital signs and
# assessments are CLASSTYPE=2. See THE LOINC CONSTRAINT IS THE UNION in the
# module docstring for the two-disjoint-passes alternative that was probed, and
# why the merge failure it rested on does not reproduce on this deployment.
CONSTRAINT_VCL = '(http://loinc.org)(CLASSTYPE/"1|2",STATUS=ACTIVE)'

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
}

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
    "codesearch_target", "codesearch_display", "codesearch_confidence",
    "codesearch_status", "codesearch_reasoning",
    "codesearch_loinc_status", "codesearch_loinc_target",
    "codesearch_loinc_display", "codesearch_loinc_confidence",
    "codesearch_snomed_status", "codesearch_snomed_target",
    "codesearch_snomed_display", "codesearch_snomed_confidence",
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
                 f"the pre-filter reads — without it the 133 Care Plans and 38 "
                 f"Alarms items would be searched, and both were measured "
                 f"answering above threshold and wrongly. Download MIMIC-IV "
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

    One decline, read off the dictionary's `category` and applied to every item
    identically. See BOTH PRE-SEARCH DECLINES in the module docstring.
    """
    why_not = DECLINED_CATEGORIES.get(item["category"])
    if why_not:
        return False, why_not
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


def one_pass(service, fhir_base, text, system, timeout):
    """Run one system's search and gate it. Returns a dict describing the pass.

    `code` and `display` are set only when the pass produced a usable target;
    `status` says what happened either way, and `target`/`confidence` keep the
    proposal even where it was then rejected.
    """
    result = {"status": "", "target": "", "display": "", "confidence": "",
              "reasoning": "", "path": "", "code": "", "preferred": ""}
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
    if confidence < CONFIDENCE_THRESHOLD:
        result["status"] = "below-threshold"
        return result

    status, display = gate(fhir_base, system, match["code"])
    result["status"] = status
    if status == "ok":
        result["code"] = match["code"]
        result["preferred"] = display
    return result


def search_query(label, fhir_base, service, timeout):
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

    loinc = one_pass(service, fhir_base, text, LOINC, timeout)
    _record(answer, "loinc", loinc)
    if loinc["code"]:
        _decide(answer, LOINC, loinc)
        return answer

    snomed = one_pass(service, fhir_base, text, SNOMED, timeout)
    _record(answer, "snomed", snomed)
    if snomed["code"]:
        _decide(answer, SNOMED, snomed)
        return answer

    # Neither pass produced a target. The DECISIVE block mirrors the LOINC pass,
    # because that is the one every item is asked in and the one whose rejection
    # a reader meets first; the SNOMED pass is recorded in its own block and
    # named in the comment. A transport failure in either is surfaced as the
    # decisive status so main() can refuse to write the file.
    failed = next((p for p in (loinc, snomed)
                   if p["status"].startswith("error")), None)
    _decide(answer, LOINC, failed or loinc)
    answer["comment"] = declined_comment(text, loinc, snomed)
    return answer


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

    # One search per COLLAPSED label. The label is the DICTIONARY's with its
    # instance index stripped; `mimic_display` in the committed table stays the
    # IG's exact string, which load_curated requires, and `codesearch_query`
    # records the string actually sent, so the collapse is visible in the CSV.
    queries = {}
    for code in asked:
        queries.setdefault(collapsed(items_dict[code]["label"]), []).append(code)
    ordered = sorted(queries)

    print(f"  {len(items)} IG code(s)"
          + (f" (subset of {len(codes)}, --only)" if args.only else ""))
    print(f"  dictionary: {D_ITEMS_GZ.relative_to(TERM.parents[1])} "
          f"({len(items_dict)} matched)")
    print(f"  pre-filter: {len(asked)} searchable; "
          f"{len(items) - len(asked)} declined unasked "
          f"({', '.join(sorted(DECLINED_CATEGORIES))})")
    print(f"  queries:    {len(asked)} item(s) collapse to {len(ordered)} "
          f"distinct label(s)")
    print(f"  gate:       {args.fhir_base}")
    print(f"  service:    {args.service}")
    print(f"  loinc:      {CONSTRAINT_VCL}")
    print(f"  snomed:     {CONSTRAINT_ECL}")
    print(f"  template:   {TEMPLATE!r} (identity — the bare label)")
    print(f"  threshold:  {CONFIDENCE_THRESHOLD}")
    print(f"  comments:   {len(COMMENT_OVERRIDES)}\n")

    def work(label):
        answer = search_query(label, args.fhir_base, args.service, args.timeout)
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
                            "compared on confidence."),
        "template": TEMPLATE,
        "confidence_threshold": CONFIDENCE_THRESHOLD,
        "pre_filter": {
            "dictionary": str(D_ITEMS_GZ.relative_to(TERM.parents[1])),
            "declined_categories": DECLINED_CATEGORIES,
            "declined_unasked": {
                code: rows_by_code[code]["comment"]
                for code in sorted(set(codes) - set(asked))},
        },
        # Which itemids shared a query, so the collapse is auditable without
        # re-deriving it from the dictionary.
        "query_key": ["label with #<n> stripped"],
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
