#!/usr/bin/env python3
"""Generate conceptmaps/micro-test-loinc.csv — the 176 microbiology tests -> LOINC.

The fourth generated table, and the third to target LOINC. It follows
build_outputevents_table.py in shape — network generation is a separate explicit
target, the build stays offline and byte-reproducible — and differs from it in
one structural way no earlier stream needed: it searches TWO DISJOINT SPACES per
item rather than one, and requires exactly one of them to answer. See TWO PASSES
below, which is the whole argument of this script.

WHAT THE SOURCE CODES MEAN. mimic-microbiology-test holds 176 test names from
MIMIC's `microbiologyevents.test_name`, bound to Observation.code on
MimicObservationMicroTest. Note that the test name is all the code carries: the
SPECIMEN is a separate column (`spec_type_desc`) and reaches FHIR as
Observation.specimen, so a target that pins a specimen the label never names is
over-assertion — the `Hemoglobin, Blood -> …by Oximetry` family. Some labels do
name their specimen (`URINE CULTURE`, `FECAL CULTURE`) and some deliberately do
not (`GRAM STAIN`, `ACID FAST SMEAR`); LOINC has the specimen-neutral
`… in Specimen` variants for exactly the second kind, and the template below is
what makes the service reach for them.

The population is NOT one thing, and that is what shapes this script. Reading
all 176 labels there are three groups:

    ~143  microbiology proper — cultures, stains, antigen and antibody
          serology, NAAT and viral load. LOINC files every one of these in
          CLASS = MICRO, including the molecular ones (`25836-8` HIV viral
          load, `61367-9` C. difficile DNA are both MICRO, not MOLPATH).

     ~28  CYTOGENETICS — `CHROMOSOME ANALYSIS-BONE MARROW`, `INTERPHASE FISH
          ANALYSIS, 25-99 CELLS`, `MOLECULAR CYTOGENETICS-DNA Probe`, the
          `TISSUE CULTURE-<specimen>` cell cultures. BIDMC's cytogenetics lab
          shares the microbiology results table, so these are microbiology
          tests only by filing cabinet. LOINC files them in MOLPATH,
          MOLPATH.MUT and PANEL.HL7.CYTOGEN — nowhere near MICRO.

      ~5  administrative and workflow slots with no observable counterpart in
          any terminology: `90193 voided`, `90166 Problem`, `90230 Stool Hold
          Request`, `90272 TISSUE`, `90167 ISOLATE FOR MIC`. These are the
          `Care Plans` case of the parent issue, and they are expected to
          decline rather than to be filtered out — see NO PRE-FILTER.

TWO PASSES, and why this is not one wider constraint. Every item is searched
twice, against two constraints that cannot overlap (`MOLPATH.*` cannot match
`MICRO`):

    micro  (http://loinc.org)(CLASS=MICRO,STATUS=ACTIVE)                14,173
    cyto   (http://loinc.org)(CLASS/"MOLPATH.*|PANEL.HL7.CYTOGEN",…)     2,579

and the resolution rule is EXACTLY ONE PASS MAY ANSWER. One does -> that is the
mapping. Both do -> `conflict`, and the item is declared unmapped with both
proposals recorded. Neither does -> unmapped, as usual. Nothing anywhere keys on
an individual label; both passes run for all 171 queries.

The obvious alternative is one constraint spanning both class sets, and it was
probed first. It is worse, measurably, on the same template. Merged, the
`TISSUE CULTURE-*` family comes back as BACTERIOLOGY:

    TISSUE CULTURE-AMNIOTIC FLUID   596-7 |Bacteria identified in Amniotic fluid
                                           by Culture|                     0.85
    TISSUE CULTURE-FLUID            636-1 |… by Sterile body fluid culture| 0.85
    TISSUE CULTURE-TISSUE          43408-4 |Bacteria identified in Tissue|  0.85
    Tissue Culture-Bone Marrow     60258-1 |… in Bone marrow by Culture|    0.80

Every one of those is a cell culture grown in order to karyotype it — they sit
beside `CHROMOSOME ANALYSIS-<the same specimen>` in the same table, and MIMIC
has separate unambiguous bacteriology labels for those specimens (`90268 FLUID
CULTURE`, `90205 Fluid Culture in Bottles`). So the merged constraint makes the
data say a prenatal karyotype culture was a bacterial culture: valid, active,
in-constraint LOINC codes, above the threshold, past the gate, and wrong about
the patient. That is the OHDSI qualifier failure and the `227719 AVA` failure,
and nothing downstream can catch it.

Split into two passes, all four decline in BOTH spaces and the rows are declared
unmapped instead. The cause is retrieval, not reasoning: in the merged pool the
shortlist for `TISSUE CULTURE-AMNIOTIC FLUID` holds bacterial cultures AND
chromosome panels and the model takes the nearest string, while in the pure
micro pool it declines and in the pure cytogenetics pool nothing codes a culture
STEP (LOINC codes the karyotype analysis, not the culture that precedes it). The
split costs two searches per item and buys four wrong rows removed.

It does not cost coverage either. The `conflict` branch fired on NONE of the 39
labels probed: the cytogenetics space never answered a microbiology label
(`URINE CULTURE`, `GRAM STAIN`, `C. difficile PCR` all no-match there) and the
micro space never answered a chromosome or FISH label. What pass `cyto`
recovers, which a `CLASS=MICRO`-only constraint would have declined outright:

    CHROMOSOME ANALYSIS-BLOOD          62348-8 |Chromosome analysis panel -
                                                Blood by G-banded|          0.85
    CHROMOSOME ANALYSIS-BONE MARROW    81861-7 |Karyotype in Bone marrow|    0.85
    CHROMOSOME ANALYSIS-AMNIOTIC FLUID 62351-2 |Chromosome analysis panel -
                                                Amniotic fluid by G-banded| 0.85
    INTERPHASE FISH ANALYSIS, 25-99 …  62345-4 |Chromosome analysis.interphase
                                                panel - Blood by FISH|      0.85
    Additional Cells and Karyotype     29770-5 |Karyotype [Identifier] in
                                                Blood or Tissue Nominal|    0.85

`FOCUSED ANALYSIS` proposes `103736-5 |Erythrocytosis focused multigene
analysis|` at 0.75 in that space and is correctly dropped at the threshold — a
specific gene panel for a generic label is the hazard the cytogenetics space
brings, and the threshold is what handles it.

The cytogenetics constraint has to span all of `MOLPATH.*` and not just
`CLASS=MOLPATH`, because the targets are scattered: `35129-6 |Karyotype|` and
`93356-4` are MOLPATH, `81861-7 |Karyotype in Bone marrow|` is MOLPATH.MUT, and
`62348-8`/`62345-4` are PANEL.HL7.CYTOGEN.

WHY THE CONSTRAINT AND NOT THE CONFIDENCE, for the third LOINC stream running.
Asked against `http://loinc.org/vs` instead, with the same template, this
population answers with LOINC PARTS at exactly the confidences a real answer
scores:

    AEROBIC BOTTLE             LP6103-8 |Aerobic culture|                   0.85
    GRAM STAIN                 LP6301-8 |Gram stain|   (the METHOD Part!)   0.85
    CHROMOSOME ANALYSIS-BLOOD  LP445939-4 |Chromosome analysis | Blood |
                                           Molecular pathology|             0.85
    Problem                    LP267930-8 |Specimen collection problem|     0.80

None is a legal Observation.code; all four clear the 0.8 threshold; the junk
label `Problem` scores as high as anything. `$validate-code` confirms all four
sit outside both constraints while the good targets sit inside, so the
constraints PREVENT these rather than rejecting them after the fact. This is the
`Foley Catheter` lesson of build_d_items_table.py and the `Stool`/`Lumbar` Part
lesson of build_outputevents_table.py, repeating a third time.

Verified end to end before this script was written, the check both LOINC
generators document: asked for `Sodium [Moles/volume] in Serum or Plasma` and
`Systolic blood pressure`, BOTH constraints return NO MATCH — so neither is
being silently dropped, which is the failure that would make every check here
pass while measuring nothing.

TEMPLATE. Load-bearing, and one sentence serves both passes. Three were run over
the labels that discriminate between them:

    bare                                     loses URINE CULTURE, AEROBIC
                                             BOTTLE, HCV VIRAL LOAD outright
    "Microbiology laboratory test recorded
     on a clinical specimen: {}"             URINE CULTURE -> a [#/volume]
                                             colony count; no answer at all for
                                             AEROBIC BOTTLE or HCV VIRAL LOAD
    "Clinical microbiology test name
     recorded in the hospital microbiology
     results table: {}"                      <- kept

The kept sentence dominates the second outright — over 14 bare-noun
culture/stain labels the two agree on 12, the kept one additionally answers
`CHLAMYDIA CULTURE`, and the one label the other wins (`FUNGAL CULTURE` ->
`97946-8 |Fungal colony [Color] in Isolate by Culture|` at 0.75) is below the
threshold and is not what the label means anyway. What it buys elsewhere is the
SCALE of the answer: naming the source as a test NAME rather than a measurement
moves `URINE CULTURE` off `100906-7 |Bacteria [#/volume] in Urine by Culture|`
and onto `630-4 |Bacteria identified in Urine by Culture|`, which is what a
culture result actually is. It also reaches two labels nothing else does:
`AEROBIC BOTTLE` -> `90426-8 |Microorganism preliminary growth [Presence] in
Blood by Aerobic culture bottle|`, a label that names only the container, and
`HCV VIRAL LOAD` -> `20416-4`.

It says "microbiology" while being sent to the cytogenetics space too, which
looks wrong and is not: the sentence states where the label came from — MIMIC's
microbiology results table, true of all 176 — and the constraint, not the
wording, is what routes. A neutrally-worded variant ("Laboratory test name
recorded in …") was probed and is measurably worse: it loses
`CMV IgG ANTIBODY` and re-introduces bacterial answers for `TISSUE` and two
tissue cultures, while the kept sentence answers the cytogenetics labels
correctly in the cytogenetics space regardless.

NO PRE-FILTER, unlike build_outputevents_table.py. That script can decline the 5
items that record no volume without searching them, because MIMIC's ICU
`d_items` dictionary states each item's `param_type` and `unitname`. There is no
counterpart here: MIMIC ships no dictionary for microbiology test names, the IG
CodeSystem's code + display IS the entire source, and the demo release's
`microbiologyevents` covers only a fraction of the 176 — too thin to support a
rule. So the administrative labels are searched like everything else and
declined by the constraints, which they demonstrably are: `voided`, `Problem`,
`TISSUE`, `ISOLATE FOR MIC` and `Stool Hold Request` are no-match in both
spaces. A source-label regex declining the `TISSUE CULTURE-*` family was drafted
and then dropped, because the two-pass split already declines them — leaving the
source side rule-free, which is the better place to be.

THE GATE is build_outputevents_table.py's, applied per pass against that pass's
own constraint: membership asserted with $validate-code rather than assumed from
the service having been asked nicely, which subsumes STATUS = ACTIVE because
both constraints carry it, and the target display replaced with the server's own
LONG_COMMON_NAME so verify-curated's display check passes by construction. LOINC
needs no `active` or `international core module` check: both SNOMED analogues are
expressible on the LOINC side, and LOINC has no national extensions.

There is deliberately NO third check of the kind micro-susc's
`<substance> [Susceptibility]` shape and outputevents' TOTAL_CODES are. One was
looked for. No single display shape is right across cultures (Nominal), antigen
and antibody tests (Ordinal) and viral loads (Quantitative), and the one
evidenced hazard — a cytogenetic cell culture answered with a bacterial culture
— cannot be written as a property of the TARGET, because
`43408-4 |Bacteria identified in Tissue by Culture|` is a perfectly good target
that is merely wrong for this source. A reject list naming it would be curating
against rows already seen to come back wrong, which is exactly what
COMMENT_OVERRIDES is forbidden from doing. The two-pass split handles it
structurally instead.

EQUIVALENCE is not this script's concern. Every mapping a table supplies is
`relatedto`, set by lib/assemble.py when it builds the group.

THIS TABLE IS WIDER than the other three, at 20 columns: the resolved answer
plus, for every row, what EACH pass proposed and what became of it. That is the
price of the two-pass rule — "this item is unmapped" is only auditable from the
CSV alone if both spaces' proposals are in it, and `conflict` is unreadable
otherwise. lib/curated.py reads the five it needs and discards the rest.

Why it is NOT part of `make mappings`: same as the three generators before it. It
needs the network and an LLM-backed service, and it WRITES a build input.
Determinism lives in the split — this runs by hand, its output is committed, and
`make mappings` reads the committed CSV and never a server.

    make micro-test-table ARGS=--insecure

Usage:
  uv run scripts/terminology-mapping/conceptmaps/build_micro_test_table.py
  uv run .../build_micro_test_table.py --only 90039,90075 --insecure
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

# The two search spaces, disjoint by construction: a CLASS matching `MOLPATH.*`
# cannot also be `MICRO`. Both carry STATUS = ACTIVE, so the membership gate
# subsumes the retirement check. See TWO PASSES in the module docstring for why
# this is two passes and not one wider constraint — the short version is that
# merged, the cytogenetic cell cultures come back as bacteriology.
#
# The order matters only for tie-breaking a declined row's reported status, and
# for the order the run prints in.
PASSES = (
    ("micro", '(http://loinc.org)(CLASS=MICRO,STATUS=ACTIVE)'),
    ("cyto", '(http://loinc.org)(CLASS/"MOLPATH.*|PANEL.HL7.CYTOGEN",STATUS=ACTIVE)'),
)
CONSTRAINTS = dict(PASSES)

# One sentence, identical for every query and for BOTH passes. Chosen over two
# alternatives by running all three over the labels that discriminate between
# them — see the module docstring, including why a sentence saying
# "microbiology" is the right one to send to the cytogenetics space.
TEMPLATE = ("Clinical microbiology test name recorded in the hospital "
            "microbiology results table: {}")

# Below this, a pass's answer is discarded. Matches the three generators before
# it. It is doing real work in the cytogenetics space, where `FOCUSED ANALYSIS`
# proposes a specific multigene panel at 0.75. The distribution is printed per
# pass at the end of every run so it can be moved with evidence rather than by
# taste.
CONFIDENCE_THRESHOLD = 0.8

# Which decline a row reports when NEITHER pass produced a usable answer and the
# two passes failed differently. Most actionable first: a gate rejection means
# the service was confident and a stated check removed the answer, so it names
# something to go and look at; `no-match` is the absence of any signal at all.
# Ties break on PASSES order. Both passes' own statuses are kept per row
# regardless, so this only decides which word the summary and the statistics see.
DECLINE_PRECEDENCE = ("out-of-constraint", "absent", "below-threshold",
                      "no-match")

# --------------------------------------------------------------------------- #
# Paths and provenance
# --------------------------------------------------------------------------- #

TERM = Path(__file__).resolve().parents[1]
OUT_CSV = Path(__file__).resolve().parent / "micro-test-loinc.csv"
LOG_JSON = TERM / "output" / "micro-test-generation-log.json"

# This table targets LOINC, so it says so in its own header rather than
# borrowing the SNOMED naming. lib.curated.load_table normalises both to
# `target_code` / `target_display` for the build.
TARGET_COLUMNS = ("loinc_code", "loinc_display")
CURATED = curated_columns(TARGET_COLUMNS)

# The resolved answer: which pass supplied it, what it was, and what became of
# it. `codesearch_status` and `codesearch_confidence` are the two columns
# lib/stats.py reads for the per-stream statistics, so they carry the RESOLVED
# values and the vocabulary stays the one the other three tables use — plus
# `conflict`, which only this stream can produce.
RESOLVED_COLUMNS = ["codesearch_query", "codesearch_pass", "codesearch_target",
                    "codesearch_display", "codesearch_confidence",
                    "codesearch_status", "codesearch_reasoning"]

# What EACH pass proposed, on every row, including the rows where the proposal
# was then rejected by the threshold, by the gate, or by the exactly-one rule.
# Without these `conflict` is an unreadable word in a CSV and a declined row
# cannot be audited without re-running the generator — see THIS TABLE IS WIDER.
PER_PASS_COLUMNS = [f"{name}_{field}"
                    for name, _ in PASSES
                    for field in ("target", "display", "confidence", "status")]

PROVENANCE_COLUMNS = RESOLVED_COLUMNS + PER_PASS_COLUMNS

# Recorded per row in the log only. `path` (cached / fast / agentic) says how
# this run fetched an answer, not anything about the answer, so it would show up
# as a wall of changed rows in a diff where no mapping moved. The losing pass's
# reasoning is long, and the log is where a reader goes once the CSV has told
# them which row to care about.
LOG_ONLY_COLUMNS = [f"{name}_{field}"
                    for name, _ in PASSES
                    for field in ("reasoning", "path")]

# --------------------------------------------------------------------------- #
# Sources
# --------------------------------------------------------------------------- #


def ig_codes():
    """(code, display) for the 176 tests, read from the IG itself.

    Routed through the observation builder's own SOURCES declaration for the
    reason the three generators before it give: lib.curated.load_table rejects a
    row whose display differs from the IG's by so much as a character, so the
    generator and the build must read displays through the same function or the
    table this writes can fail the build that reads it.

    Note the source names the CodeSystem, not the bound ValueSet:
    ValueSet-mimic-microbiology-test.json is a bare compose with no enumerated
    concepts, so the CodeSystem is the only enumeration there is.
    """
    from conceptmaps.build_observation_cm_vs import SOURCES

    source = next(s for s in SOURCES if s.get("table") == OUT_CSV)
    return dict(source_concepts(source))


def constraint_url(vcl):
    """A constraint as a resolvable implicit-ValueSet canonical."""
    return "http://fhir.org/VCL?v1=" + urllib.parse.quote(vcl, safe="")


def service_info(service):
    """code-search's self-reported configuration, or None if it won't say."""
    try:
        with urllib.request.urlopen(
                f"{service.rstrip('/')}/api/v1/info", timeout=30,
                context=fhirclient.SSL_CONTEXT) as response:
            return json.load(response)
    except Exception:                                 # noqa: BLE001
        return None


def find_code(service, text, vcl, timeout, attempts=4):
    """code-search's best match for `text`, constrained to `vcl`.

    Retries transport failures, for the reason the generators before it give: a
    dropped connection is not an answer, and a run that quietly mixes 'no match'
    with 'the service was not running' produces a table that understates
    coverage and reads exactly like a real result. Exhausted retries raise, and
    main() refuses to write the CSV.
    """
    body = json.dumps({
        "text": text,
        "url": constraint_url(vcl),
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


def in_constraint(fhir_base, vcl, code):
    """True if `code` is a member of `vcl`, per the server.

    Asserted rather than assumed. code-search was asked to honour the constraint
    and demonstrably does — both constraints return NO MATCH for
    `Sodium [Moles/volume] in Serum or Plasma` — but 'the service was asked
    nicely' is not a property a committed table should rest on. Checked against
    the pass's OWN constraint, which is what keeps the two-pass rule meaningful:
    an answer accepted for the micro pass has to be a micro-space member.
    """
    query = urllib.parse.urlencode({
        "url": constraint_url(vcl), "system": LOINC, "code": code})
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


def gate(fhir_base, vcl, code):
    """('ok', display) if `code` is usable for this pass, else (reason, None).

    Used as a filter rather than an assertion: a target that fails here is
    treated exactly as an absent one and the pass counts as not having answered.
    """
    if not in_constraint(fhir_base, vcl, code):
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
# CONFIDENCE_THRESHOLD, the gate and the exactly-one-pass rule, and the table
# stops being 'what the service returned, gated'.
#
# Empty because no row of this table has been reviewed yet: the first run of this
# script is the dry run whose output decides which rows need a note. Two
# candidates are already known from the probes. `HCV VIRAL LOAD` proposes
# `20416-4 |… RNA [#/volume] (viral load) …|`, one of a dozen variants differing
# only in unit ([Units/volume], [Log #/volume], [log units/volume]) where MIMIC's
# label names no unit at all. And `AEROBIC BOTTLE` is three itemids
# (90092/90258/90260) mapping to one blood-culture-bottle code, so a consumer
# aggregating by Observation.code merges what MIMIC recorded separately.
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


def search_pass(name, vcl, query, fhir_base, service, timeout):
    """One code-search call for one query in one space, its answer gated.

    Returns a dict describing what this space said, whatever became of it. The
    proposal is kept even when rejected, because a row that reports `conflict`
    or `below-threshold` is only auditable if the CSV says what was proposed and
    where.
    """
    answer = {"pass": name, "target": "", "display": "", "confidence": "",
              "status": "", "reasoning": "", "path": "", "score": 0.0,
              "gated_display": ""}
    try:
        result = find_code(service, TEMPLATE.format(query), vcl, timeout)
    except Exception as exc:                          # noqa: BLE001
        answer["status"] = f"error: {str(exc)[:80]}"
        return answer

    answer["path"] = result.get("path", "")
    matches = result.get("matches") or []
    if not matches:
        answer["status"] = "no-match"
        return answer

    match = matches[0]
    score = float(match.get("confidence") or 0.0)
    answer.update(score=score, confidence=f"{score:.2f}",
                  target=match["code"], display=match.get("display", ""),
                  reasoning=(match.get("reasoning") or "").strip())
    if score < CONFIDENCE_THRESHOLD:
        answer["status"] = "below-threshold"
        return answer

    status, display = gate(fhir_base, vcl, match["code"])
    answer["status"] = status
    if status == "ok":
        answer["gated_display"] = display
    return answer


def resolve(query, answers):
    """The resolved fields for one query, from what both passes said.

    THE rule of this script: exactly one pass may answer. One did -> that is the
    mapping. Both did -> `conflict`, and the item is declared unmapped rather
    than routed by guesswork, because nothing in the data says which space the
    label belongs to and picking one would be the per-item judgement this whole
    pipeline exists to keep out.
    """
    resolved = {c: "" for c in RESOLVED_COLUMNS
                + ["loinc_code", "loinc_display", "comment"]}
    resolved["codesearch_query"] = query

    accepted = [name for name, _ in PASSES if answers[name]["status"] == "ok"]

    if len(accepted) == 1:
        answer = answers[accepted[0]]
        resolved.update(
            codesearch_pass=answer["pass"],
            codesearch_target=answer["target"],
            codesearch_display=answer["display"],
            codesearch_confidence=answer["confidence"],
            codesearch_status="ok",
            codesearch_reasoning=answer["reasoning"],
            loinc_code=answer["target"],
            loinc_display=answer["gated_display"])
        return resolved

    if len(accepted) > 1:
        status = "conflict"
        # The first accepted pass in PASSES order, so the resolved columns name
        # something concrete; both proposals are in the per-pass columns and in
        # the comment either way.
        reported = answers[accepted[0]]
    else:
        status = next((s for s in DECLINE_PRECEDENCE
                       if any(answers[n]["status"] == s for n, _ in PASSES)),
                      "no-match")
        reported = next((answers[n] for n, _ in PASSES
                         if answers[n]["status"] == status), answers[PASSES[0][0]])

    resolved.update(codesearch_pass="",
                    codesearch_target=reported["target"],
                    codesearch_display=reported["display"],
                    codesearch_confidence=reported["confidence"],
                    codesearch_status=status,
                    codesearch_reasoning=reported["reasoning"],
                    comment=declined_comment(query, answers, status))
    return resolved


def pass_summary(name, answer):
    """One clause saying what one space said and what became of it."""
    proposal = f"{answer['target']} |{answer['display']}| at {answer['confidence']}"
    return {
        "ok": f"{name} proposed {proposal}",
        "no-match": f"{name} returned no match",
        "below-threshold": f"{name} proposed {proposal}",
        "out-of-constraint": (f"{name} proposed {proposal}, which is not a "
                              f"member of {CONSTRAINTS[name]}"),
        "absent": f"{name} proposed {proposal}, which is not a known code",
    }.get(answer["status"], f"{name}: {answer['status']}")


def declined_comment(query, answers, status):
    """Why a row carries no target. load_table requires one, and rightly: an
    empty target is a claim that the source could not answer, and a claim has to
    say what it rests on.

    Both spaces are named on every declined row, because with two passes "no
    target" is only a complete statement if it says what each of them said.
    Phrased against the query rather than the item label, since that is the
    string the service was actually given — they differ wherever two itemids
    share a label.
    """
    # When neither space proposed anything, "micro returned no match; cyto
    # returned no match" only repeats the lead. What a reader needs instead is
    # WITHIN WHAT, which is the phrasing build_d_items_table.py uses.
    if status == "no-match":
        spaces = " or ".join(vcl for _, vcl in PASSES)
        return (f"code-search returned no match for {query!r} within either "
                f"search space: {spaces}.")

    detail = "; ".join(pass_summary(name, answers[name]) for name, _ in PASSES)
    lead = {
        "conflict": (
            f"Both search spaces answered for {query!r} and exactly one may, so "
            f"nothing in the data says which this test belongs to: "),
        "below-threshold": (
            f"No answer above the {CONFIDENCE_THRESHOLD} threshold for "
            f"{query!r}: "),
        "out-of-constraint": (
            f"No answer that passed the membership gate for {query!r}: "),
        "absent": (
            f"No answer that passed the membership gate for {query!r}: "),
        "no-match": (
            f"code-search returned no match for {query!r} in either search "
            f"space: "),
    }.get(status, f"No target for {query!r}: ")
    return lead + detail + "."


# --------------------------------------------------------------------------- #
# Reporting
# --------------------------------------------------------------------------- #


def report(rows, queries):
    """What the run found. Printed so it can be pasted into a write-up."""
    mapped = [r for r in rows if r["loinc_code"]]
    print(f"\n  {len(rows)} item(s) over {len(queries)} quer(ies): "
          f"{len(mapped)} mapped, {len(rows) - len(mapped)} declared unmapped")

    statuses = {}
    for row in rows:
        statuses[row["codesearch_status"]] = \
            statuses.get(row["codesearch_status"], 0) + 1
    print("\n  resolved status")
    for status, count in sorted(statuses.items()):
        print(f"    {status:<18} {count:>4}")

    # Per pass, counted per QUERY rather than per item: counting a label shared
    # by three itemids three times would overstate how many independent answers
    # the run actually got.
    for name, _ in PASSES:
        by_query, scored = {}, []
        for row in rows:
            by_query[row["codesearch_query"]] = row
        for row in by_query.values():
            if row[f"{name}_confidence"]:
                scored.append(float(row[f"{name}_confidence"]))
        counts = {}
        for row in by_query.values():
            counts[row[f"{name}_status"]] = counts.get(row[f"{name}_status"], 0) + 1
        print(f"\n  pass {name!r}: {len(by_query)} quer(ies)")
        for status, count in sorted(counts.items()):
            print(f"    {status:<18} {count:>4}")
        if scored:
            scored.sort()
            print(f"    confidence, {len(scored)} answered")
            buckets = [(1.0, 1.01), (0.9, 1.0), (0.8, 0.9), (0.7, 0.8),
                       (0.0, 0.7)]
            for low, high in buckets:
                hits = [s for s in scored if low <= s < high]
                label = f"{low:.2f}" if high > 1.0 else f"{low:.2f}–{high:.2f}"
                print(f"      {label:<12} {len(hits):>4}  {'#' * len(hits)}")
            print(f"      threshold {CONFIDENCE_THRESHOLD}: "
                  f"{sum(1 for s in scored if s >= CONFIDENCE_THRESHOLD)} kept, "
                  f"{sum(1 for s in scored if s < CONFIDENCE_THRESHOLD)} dropped")

    # The rule of this script firing. Zero was observed over 39 probed labels,
    # so anything here is worth reading before the table is committed.
    conflicts = [r for r in rows if r["codesearch_status"] == "conflict"]
    if conflicts:
        print(f"\n  {len(conflicts)} row(s) where BOTH spaces answered — "
              f"declared unmapped:")
        for row in conflicts:
            print(f"    {row['mimic_code']} {row['mimic_display'][:30]:<32} "
                  f"micro {row['micro_target']:<10} "
                  f"cyto {row['cyto_target']:<10}")

    # How many distinct targets the mapped rows share. A generic target is not
    # wrong, but several tests landing on one code means a consumer aggregating
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
                print(f"    {code:<10} {display[:40]:<42} {len(group):>2}  "
                      f"{labels[:66]}")

    commented = [r for r in rows if r["loinc_code"] and r["comment"]]
    if commented:
        print(f"\n  {len(commented)} mapped row(s) carrying a reviewed comment")
        for row in commented:
            print(f"    {row['mimic_code']} {row['mimic_display'][:26]:<26} "
                  f"-> {row['loinc_code']:<10} {row['loinc_display'][:40]}")

    unmapped = [r for r in rows if not r["loinc_code"]]
    if unmapped:
        print(f"\n  {len(unmapped)} unmapped, declared:")
        for row in unmapped:
            print(f"    {row['mimic_code']} {row['mimic_display'][:32]:<34} "
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
    if not codes:
        sys.exit("  no source codes — CodeSystem-mimic-microbiology-test.json "
                 "is missing from input/resources/, so this would write an "
                 "empty table over a real one.")
    items = sorted(codes.items())
    if args.only:
        wanted = {c.strip() for c in args.only.split(",") if c.strip()}
        unknown = wanted - set(codes)
        if unknown:
            sys.exit(f"  --only names code(s) not in the IG: {sorted(unknown)}")
        items = [i for i in items if i[0] in wanted]
        args.dry_run = True

    rows_by_code = {code: blank_row(code, label) for code, label in items}

    # One search per DISTINCT LABEL, not per itemid, and the answer fanned back
    # across the itemids that share it. Three labels are shared —
    # `AEROBIC BOTTLE` (90092/90258/90260), `ANAEROBIC BOTTLE`
    # (90093/90117/90261) and `VIRAL CULTURE: R/O CYTOMEGALOVIRUS`
    # (90142/90255) — so 176 items become 171 queries.
    #
    # A correctness rule, not an optimisation, and the same argument
    # build_outputevents_table.py makes for its `#N` families: nothing
    # distinguishes those itemids but the itemid, so a map where they disagree is
    # wrong however plausible each row looks alone. Searching the label makes the
    # disagreement unrepresentable rather than merely unlikely.
    #
    # Grouped on the EXACT display, with no normalisation. `mimic_display` in the
    # committed table is the IG's exact label — load_curated requires that — and
    # `codesearch_query` records what was sent, so the grouping is visible in the
    # CSV. Known limit: `90150 MOLECULAR CYTOGENETICS - DNA PROBE` and
    # `90155 MOLECULAR CYTOGENETICS-DNA Probe` stay two queries, because case and
    # whitespace folding does not join them and folding hyphen spacing too would
    # be a rule written for exactly one pair.
    queries = {}
    for code, label in items:
        queries.setdefault(label, []).append(code)
    ordered = sorted(queries)

    print(f"  {len(items)} IG code(s)"
          + (f" (subset of {len(codes)}, --only)" if args.only else ""))
    print(f"  queries:    {len(items)} item(s) collapse to {len(ordered)} "
          f"distinct label(s)")
    print(f"  gate:       {args.fhir_base}")
    print(f"  service:    {args.service}")
    for name, vcl in PASSES:
        print(f"  pass {name:<6} {vcl}")
    print(f"  template:   {TEMPLATE}")
    print(f"  threshold:  {CONFIDENCE_THRESHOLD}")
    print(f"  rule:       exactly one pass may answer; both -> conflict, "
          f"declared unmapped")
    print(f"  comments:   {len(COMMENT_OVERRIDES)}\n")

    # Both passes for one query are one unit of work, so a query's two calls run
    # back to back and the printed line is complete when it appears.
    def work(query):
        answers = {name: search_pass(name, vcl, query, args.fhir_base,
                                     args.service, args.timeout)
                   for name, vcl in PASSES}
        resolved = resolve(query, answers)
        members = queries[query]
        fanned = f"x{len(members)}" if len(members) > 1 else ""
        print(f"    {query[:34]:<34} "
              + " ".join(f"{name}={answers[name]['status'][:16]:<16}"
                         for name, _ in PASSES)
              + f" -> {resolved['codesearch_status']:<14} "
                f"{resolved['loinc_code'] or '—':<10} "
                f"{resolved['loinc_display'][:30]:<32} {fanned}", flush=True)
        return query, answers, resolved

    with concurrent.futures.ThreadPoolExecutor(args.workers) as pool:
        results = list(pool.map(work, ordered))

    for query, answers, resolved in results:
        for code in queries[query]:
            row = rows_by_code[code]
            row.update(resolved)
            for name, _ in PASSES:
                answer = answers[name]
                row[f"{name}_target"] = answer["target"]
                row[f"{name}_display"] = answer["display"]
                row[f"{name}_confidence"] = answer["confidence"]
                row[f"{name}_status"] = answer["status"]
                row[f"{name}_reasoning"] = answer["reasoning"]
                row[f"{name}_path"] = answer["path"]

    # Sorted by mimic_code so a re-run diffs only where an answer changed, not
    # wherever the thread pool happened to finish first.
    rows = sorted(rows_by_code.values(), key=lambda r: r["mimic_code"])

    # A transport failure is not an answer, so a partial run writes nothing. A
    # pass that errored is not the same as a pass that declined, and treating it
    # as one would silently understate coverage while reading like a real result.
    failed = [r for r in rows
              if any(r[f"{name}_status"].startswith("error")
                     for name, _ in PASSES)]
    if failed:
        print(f"\n  {len(failed)} of {len(rows)} row(s) had a code-search call "
              f"fail after retries — NOT writing {OUT_CSV.name}.")
        for row in failed[:5]:
            errors = "; ".join(row[f"{name}_status"] for name, _ in PASSES
                               if row[f"{name}_status"].startswith("error"))
            print(f"    {row['mimic_code']} {row['mimic_display'][:26]:<26} "
                  f"{errors[:70]}")
        if len(failed) > 5:
            print(f"    … and {len(failed) - 5} more")
        sys.exit("  Fix the service and re-run; cached answers make the "
                 "retry cheap.")

    # The invariant the label grouping exists to guarantee, asserted rather than
    # assumed. The fan-out above makes divergence structurally impossible, so
    # this can only fire if the grouping and the fan-out ever stop agreeing —
    # and the whole point of the rule is that a reader should not have to trust
    # that they do.
    diverged = {q: sorted({rows_by_code[c]["loinc_code"] or "(unmapped)"
                           for c in members})
                for q, members in queries.items()
                if len({rows_by_code[c]["loinc_code"] for c in members}) > 1}
    if diverged:
        for query, targets in sorted(diverged.items()):
            print(f"    {query}: {targets}", file=sys.stderr)
        sys.exit(f"  {len(diverged)} label(s) whose itemids ended up on "
                 f"different targets, which the label grouping exists to "
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
        # A LIST, where the three earlier logs carry a string: this stream has
        # two constraints and flattening them would hide that. lib/stats.py
        # copies it into the report's `codesearch.constraint` unchanged, and
        # mapping-statistics.csv does not carry the constraint text at all, so
        # nothing downstream has to be taught about the shape.
        "constraint_vcl": [vcl for _, vcl in PASSES],
        "passes": [{"name": name, "constraint_vcl": vcl,
                    "constraint_url": constraint_url(vcl)}
                   for name, vcl in PASSES],
        "template": TEMPLATE,
        "confidence_threshold": CONFIDENCE_THRESHOLD,
        "decline_precedence": list(DECLINE_PRECEDENCE),
        # Which itemids shared a query, so the grouping is auditable without
        # re-deriving it from the labels.
        "shared_labels": {query: sorted(members)
                          for query, members in sorted(queries.items())
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
