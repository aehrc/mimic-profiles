#!/usr/bin/env python3
"""Generate conceptmaps/lab-fluid-snomed.csv — the 12 MIMIC lab specimen names -> SNOMED CT.

The eighth generated table, the first for `Specimen.type`, and the smallest
stream in the repo. It is deliberately the one that opens a brand-new bound
field: 12 codes, one constraint, no family collapse and no dictionary join, so
what it exercises is the field-level machinery rather than anything about
itself.

WHAT THE SOURCE CODES MEAN. `mimic-lab-fluid` holds the 12 values of MIMIC's
`d_labitems.fluid` column — the specimen a hospital laboratory result was
measured on. They reach FHIR as `Specimen.type` on MimicSpecimen, bound
`required` through mimic-specimen-type, and they carry 13,376,689 occurrences,
89.4% of every occurrence of that element. Nine of the 12 are observed in the
warehouse; `Fluid`, `I` and `Q` are not.

THE SOURCE CODES ARE THE LABELS, which is new in this repo. Every stream before
this keyed on an opaque id — ICU itemids, `d_labitems` itemids, the 90xxx
microbiology codes — so lib/curated.py's fatal display check has been comparing
an id's label against the IG's. Here `mimic_code` and `mimic_display` hold the
same string, so that check is degenerate: it still fires if the IG drops a code,
but it cannot catch a relabelling, because a relabelling would be a new code.
Nothing in lib/curated.py needs changing, and the duplicated column in the CSV
is the data rather than a bug.

CONSTRAINT_ECL is `<<123038009 |Specimen|`: 1,844 concepts, all active, 1,842 of
them international core. So the extension gate costs nothing on this hierarchy,
unlike the ICU procedure population where it dropped 7 rows. The constraint cuts
the search space from 714,687 concepts to 1,844 — 99.74% — and that cut is the
entire method.

THE CONSTRAINT IS THE WHOLE METHOD, and this population states the case more
sharply than any before it. Probing 24 specimen labels unconstrained over all of
SNOMED, only 2 of the 24 answers were legal `Specimen.type` codes; the rest were
7 substances, 5 procedures (3 inactive), 3 disorders, 3 body structures, an
organism, a morphologic abnormality, a physical object and a unit of
presentation. On this stream's own labels:

    URINE          78014005  |Urine|          1.00  substance
                   122575003 |Urine specimen| 0.95  <- constrained
    Blood          87612001  |Blood|          1.00  substance
                   119297000 |Blood specimen| 0.95  <- constrained
    STOOL          706697005 |Stool|          1.00  physical object
                   119339001 |Faeces specimen| 0.95 <- constrained
    ASCITES        389026000 |Ascites|        1.00  DISORDER
                   309201001 |Ascitic fluid specimen| 0.85 <- constrained
    Bone Marrow    256888005 |Bone marrow|    0.90  body structure, INACTIVE
                   119359002 |Bone marrow specimen| 0.95 <- constrained

Eleven of the wrong answers score exactly 1.00, against correct constrained
answers at 0.85. Confidence separates nothing here; it is inverted. And two
labels from the sibling `mimic-spec-type-desc` stream should settle the argument
permanently, because the wrong concept and the right concept carry the SAME
DISPLAY STRING: `1382308001 |Swab|` is a unit of presentation and
`257261003 |Swab|` is the specimen; `2778004 |Pleural fluid|` is a substance and
`418564007 |Pleural fluid specimen|` is the specimen. No reviewer reading the
committed CSV would catch either.

TEMPLATE IS THE IDENTITY WRAPPER `{}`, and that is an evidenced choice rather
than a default. The second stream in the repo to send the bare label, after
micro-org, and for the same reason: these labels are already specimen nouns and
need no context supplied. `Laboratory specimen submitted for testing: {}` was
probed against the bare label on 7 rows. It changed no correct answer's code,
shaved confidence on three (`URINE` 0.95 -> 0.90, `Other Body Fluid` 0.90 ->
0.85, `THROAT` 0.90 -> 0.85), and did active harm on the test-name rows of the
sibling stream:

    VARICELLA-ZOSTER CULTURE  bare 621000009105 |Viral isolate specimen| 0.60
                                   -> correctly declined
                           wrapped 472875007   |Vesicle swab|            0.80
                                   -> ACCEPTED, and fabricated
    MRSA SCREEN               bare 445297001 |Swab of internal nose|     0.70
                                   -> correctly declined
                           wrapped 123038009 |Specimen|                  0.60
                                   -> the contentless root of the constraint

Asserting "specimen submitted for testing" primes the searcher to supply a
specimen it has no evidence for — the same failure family as micro-org's
negation regression, where every wrapper tried answered a NEGATED label with the
taxon it excludes. The wrapper's one win was on `BLOOD CULTURE`, and that had to
be fixed by the membership check below rather than by a template: a wrapper that
repairs a membership bug by accident is not a stated rule.

Kept as a named constant rather than deleted so the generation log records this
setting exactly as every other stream's does, and so lib/stats.py reads it with
no special case.

THE GATE CHECKS VALUE-SET MEMBERSHIP, WHICH THE SNOMED GENERATORS BEFORE IT DID
NOT. This is the one piece of new machinery here, and it exists because the
constraint was found to LEAK. Asked for `BLOOD CULTURE` inside `<<123038009`,
code-search matched the INACTIVE concept 145540002 |Blood culture| on an exact
FSN hit, followed a `SAME_AS` historical association out of the requested value
set, and returned the successor 30088009 |Blood culture| at 0.95 — a PROCEDURE,
in the AU extension, and declared as `provenance.inVS: false` in its own
response. Ontoserver agrees it is not a member:

    ValueSet/$validate-code url=…fhir_vs=ecl/<<123038009 code=30088009
      -> result: false

The three SNOMED generators before this one (d_items, datetimeevents, micro_org)
check exists / active / international-core / display and nothing else, because
the constraint was ASSUMED to be enforced by the search. On that row the assumption
was false and every one of those checks would have passed on merit had the
concept been core. The two LOINC generators (outputevents, labevents) already
assert membership via `in_constraint`; this brings the SNOMED path level with
them, and orders it FIRST because membership is the claim the whole method rests
on.

The service-side bug has since been fixed — `BLOOD CULTURE` now answers
446131002 |Blood specimen obtained for blood culture| at 0.85 with no provenance
block at all, and it validates as a member. The check stays anyway. "The service
was asked nicely and currently complies" is not a property a committed table
should rest on, and it is the same move `verify-curated` made when it turned the
extension assumption into an assertion.

NO_CLINICAL_CONTENT declines two codes WITHOUT SEARCHING THEM. `I` and `Q` are
single letters. They are not abbreviations this repo failed to expand — MIMIC's
own dictionary carries nothing more, no `d_labitems` row observed in the
warehouse uses either, and there is no string for a searcher to be right about.
Sending them is not neutral: a one-character query is exactly the shape that
returns something confident and arbitrary, and a specimen invented for `Q` would
be indistinguishable in the committed table from a real answer. They are
declared unmapped with that reason instead, which is the analogue of the
outputevents table's volume pre-filter and the chartevents documentation
pre-filter. Probing confirmed the searcher declines `I` on its own (18
candidates seen, no match), so this rule currently costs nothing — it is here so
the decision is stated rather than dependent on the service continuing to be
sensible about single letters.

`Fluid` is NOT in that list, and the distinction is the point: it is a real if
unspecific specimen noun, SNOMED has 309051001 |Body fluid specimen| for exactly
that, and it maps. Unobserved in the warehouse is not the same claim as
unmappable, so it is searched like every other row.

WHAT TO EXPECT. Higher coverage than any semantic stream so far, on the strength
of the population rather than the method: 10 of the 12 labels are plain specimen
nouns with an exact SNOMED counterpart, and the floor is the 2 single letters,
which are structural. Read that number as what it is — a 12-row stream cannot
say anything about the method, and the field's honest prior is the ~70-75% the
104-row `mimic-spec-type-desc` stream will set, where a quarter of the labels
name a laboratory TEST rather than a specimen.

READ A `no-match` ACCORDINGLY: it means "the service declined it on that run
under that configuration", NOT "SNOMED has no such concept". `codesearch_service`
in the generation log pins the configuration, which is what lets "the answers
moved" be told apart from "the service moved" — see build_micro_org_table.py,
where a design probe and the population run disagreed on two rows because they
ran against different model profiles.

Why it is NOT part of `make mappings`. Same as every generator here: it needs the
network and a model-backed service, and it is the one stage whose output is not a
pure function of this repo. Determinism lives in the split — this runs
occasionally and by hand, its output is committed, and `make mappings` reads the
committed CSV and never a server, so `make mappings && git diff --exit-code`
stays a valid test.

    make lab-fluid-table ARGS=--insecure

Equivalence is not this script's concern. Every mapping a table supplies is
`relatedto`, set by lib/assemble.py when it builds the group; see lib/curated.py
for why a per-row equivalence column went away. This field has no identity group
and no notation rule, so `relatedto` is the ONLY equivalence it emits.

Output columns. The five in CURATED_COLUMNS are what the builder reads;
everything after them is provenance, ignored by the build and present so a reader
can audit any row — what the service proposed, at what confidence, and on what
reasoning — without re-running this script.
"""

import argparse
import concurrent.futures
import csv
# NOT `import http.client`: the fhirclient import below binds the name `http` to
# a function, so `HTTPException` in find_code's except clause would raise
# AttributeError instead of retrying — silently defeating the retry loop on
# exactly the transport failures it exists to absorb.
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
# The module, not `from ... import SSL_CONTEXT`: configure_tls() REBINDS that
# global, so a name bound at import time would still be the pre-configuration
# context and --ca-bundle would be silently ignored.
from common import fhirclient  # noqa: E402
from conceptmaps.lib.canonical import SNOMED  # noqa: E402
from conceptmaps.lib.curated import CURATED_COLUMNS  # noqa: E402
from conceptmaps.lib.igsource import source_concepts  # noqa: E402
from verify.verify_curated_snomed import INTL_MODULE, lookup  # noqa: E402

# --------------------------------------------------------------------------- #
# The stated rules
# --------------------------------------------------------------------------- #

# The SNOMED specimen hierarchy, and nothing else. 1,844 concepts, all active,
# all but two international core. See the module docstring for the eleven
# unconstrained answers that score 1.00 while being substances, disorders and
# physical objects, and for the two labels where the wrong concept and the right
# concept carry the same display string.
CONSTRAINT_ECL = "<<123038009"

# The identity wrapper: this stream sends the label as it stands. Second in the
# repo to do so, after micro-org, because these labels are already specimen
# nouns. A `Laboratory specimen submitted for testing: {}` wrapper was probed
# against it on 7 rows: it changed no correct answer's code, cost confidence on
# three, and made two test-name rows in the sibling stream accept a FABRICATED
# specimen they had correctly declined bare. See TEMPLATE in the module
# docstring.
TEMPLATE = "{}"

# Below this, code-search's answer is discarded and the item is left unmapped.
# Matches every generator here. The accuracy rests on CONSTRAINT_ECL, not on
# this number, and on this population that is not a general claim but a measured
# inversion: the WRONG unconstrained answers score 1.00 and several correct
# constrained ones score 0.85, so no threshold can separate them and the
# constraint is the only thing that does. The distribution is printed at the end
# of every run so this can be moved with evidence rather than by taste.
CONFIDENCE_THRESHOLD = 0.8

# Codes declined WITHOUT being searched, because they carry no searchable text.
#
# Not an abbreviation this repo failed to expand: MIMIC's own dictionary carries
# nothing more for either, and neither is observed in the warehouse. A
# one-character query is the shape most likely to come back confident and
# arbitrary, and a specimen invented for `Q` would be indistinguishable in the
# committed table from a real answer.
#
# `Fluid` is deliberately NOT here. It is unobserved in the warehouse too, but it
# is a real if unspecific specimen noun and SNOMED has 309051001 |Body fluid
# specimen| for exactly it — unobserved is not the same claim as unmappable.
#
# Checked against the IG at startup by validate_no_clinical_content(): a rule
# naming a code the IG has dropped declines nothing, and does so silently.
NO_CLINICAL_CONTENT = {
    "I": "a single letter with no clinical content and no expansion in MIMIC's "
         "own dictionary",
    "Q": "a single letter with no clinical content and no expansion in MIMIC's "
         "own dictionary",
}

# --------------------------------------------------------------------------- #
# Paths and provenance
# --------------------------------------------------------------------------- #

TERM = Path(__file__).resolve().parents[1]
OUT_CSV = Path(__file__).resolve().parent / "lab-fluid-snomed.csv"
LOG_JSON = TERM / "output" / "lab-fluid-generation-log.json"

# What the service proposed on every row, including rows where the proposal was
# then rejected by the threshold or by the gate — so that "this item is unmapped"
# is auditable in the committed diff rather than only in a run that has since
# scrolled away.
#
# No `codesearch_query` column, as in the micro-org table: with the identity
# TEMPLATE and no family collapse, the string sent to the service is
# `mimic_display` exactly, so a column holding it would carry no information.
#
# `codesearch_status` and `codesearch_confidence` are the two columns
# lib/stats.py reads for the per-stream statistics, so the vocabulary stays the
# one the other tables use — plus `not-in-constraint`, which is new here, and
# `no-content`, which only this stream can produce.
#
# The build ignores all of them: lib.curated.load_table reads CURATED_COLUMNS and
# discards the rest.
PROVENANCE_COLUMNS = ["codesearch_target", "codesearch_display",
                      "codesearch_confidence", "codesearch_status",
                      "codesearch_reasoning"]

# Recorded per row in the log only. `path` (cached / fast / agentic) says how
# this run fetched an answer, not anything about the answer, so it would flip to
# "cached" on the next run and show up as a wall of changed rows in a diff where
# no mapping moved.
LOG_ONLY_COLUMNS = ["path"]

# --------------------------------------------------------------------------- #
# Sources
# --------------------------------------------------------------------------- #


def ig_codes():
    """(code, display) for the 12 lab fluids, read from the IG itself.

    Routed through the specimen builder's own SOURCES declaration for the reason
    every generator here gives: lib.curated.load_table rejects a row whose
    display differs from the IG's by so much as a character, so the generator and
    the build must read displays through the same function and the same
    declaration, or this script writes a table that fails the build that reads
    it.

    Note the source names the CodeSystem, not the bound ValueSet:
    ValueSet-mimic-specimen-type.json is a bare compose unioning two CodeSystems
    with no enumerated concepts of its own, so the CodeSystem is the only
    enumeration there is.
    """
    from conceptmaps.build_specimen_cm_vs import SOURCES

    source = next(s for s in SOURCES if s.get("table") == OUT_CSV)
    return dict(source_concepts(source))


def constraint_url():
    """The implicit SNOMED ValueSet for CONSTRAINT_ECL.

    One function, used for BOTH the code-search query and the membership check,
    so the space that was searched and the space membership is asserted against
    cannot drift apart.
    """
    return (f"{SNOMED}?fhir_vs=ecl/"
            f"{urllib.parse.quote(CONSTRAINT_ECL, safe='')}")


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
    difference matters more than it looks: 'the service said no match' and 'the
    service was not running' both end up as an unmapped row, and only one of them
    is a finding. A run that quietly mixes the two produces a table that
    understates coverage and reads exactly like a real result. Exhausted retries
    raise, and main() refuses to write the CSV.
    """
    body = json.dumps({
        "text": text,
        "url": constraint_url(),
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


def in_constraint(fhir_base, code):
    """True if `code` is a member of CONSTRAINT_ECL, per the server.

    ASSERTED RATHER THAN ASSUMED, and the first SNOMED generator here to do so.
    The three before it check exists / active / international-core / display and
    take membership on trust, because code-search was asked to honour the
    constraint. On `BLOOD CULTURE` that trust was misplaced: the service matched
    an INACTIVE concept on an exact FSN hit, followed a `SAME_AS` historical
    association OUT of the requested value set, and returned a procedure at 0.95
    while declaring `provenance.inVS: false` in its own response. The bug is
    fixed service-side; this check is what makes the property true by
    construction rather than by the service's current behaviour.

    Ordered FIRST in gate() because it is the claim the whole method rests on: a
    concept outside the constraint is not a weaker answer, it is the wrong KIND
    of thing — a substance, a body structure, a procedure — and reporting such a
    row as `retired` or `no-display` would name a symptom instead of the cause.
    """
    query = urllib.parse.urlencode({
        "url": constraint_url(), "system": SNOMED, "code": code})
    status, body = http(
        "GET", f"{fhir_base.rstrip('/')}/ValueSet/$validate-code?{query}")
    if status != 200 or not body:
        return False
    return any(p["name"] == "result" and p.get("valueBoolean")
               for p in body.get("parameter", []))


def gate(fhir_base, code):
    """('ok', display) if `code` is usable, else (reason, None).

    verify_curated_snomed.py's checks used as a filter rather than an assertion —
    a target that fails here is treated exactly as an absent one, and the item is
    left unmapped with the rejected proposal recorded. A confidence score says
    nothing about whether a concept is retired, belongs to a national extension,
    or is even inside the space that was searched, and none of the three is
    visible by reading a CSV.

    The display returned is the server's preferred term, not whatever string the
    service carried next to the code. That is what keeps verify-curated's fourth
    check — display must be a real designation of the concept — green by
    construction. Note it will not always match the display quoted in the field's
    issue: this server's preferred term for 309051001 is `Body fluid`, while the
    issue records the FSN-shaped `Body fluid specimen`. Both are designations of
    the same concept.
    """
    if not in_constraint(fhir_base, code):
        return "not-in-constraint", None
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


def validate_no_clinical_content(codes):
    """Every NO_CLINICAL_CONTENT entry names a code the IG still has. Fatal.

    A pre-filter fails SILENTLY when it is wrong: a code the IG has dropped or
    renamed simply never matches, the item it was meant to decline goes to the
    service instead, and nothing says so. Checked against the FULL IG enumeration
    rather than an `--only` subset, so a probe run cannot mask a stale entry.
    """
    stale = sorted(set(NO_CLINICAL_CONTENT) - set(codes))
    if stale:
        for code in stale:
            print(f"    NO_CLINICAL_CONTENT {code!r}: the IG no longer has this "
                  f"code", file=sys.stderr)
        sys.exit(f"  {len(stale)} pre-filter entr(ies) match no IG code. A rule "
                 f"that declines nothing declines nothing silently, and the row "
                 f"it was about would ship unreviewed. Fix the entries and "
                 f"re-run.")


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
# Keyed on the PAIR and not on the code alone, because each note is written about
# one specific target concept. If a re-run moves the target, the note no longer
# describes what it was written about, and apply_comments exits rather than
# carrying it silently onto a different concept. An entry that matches no row is
# fatal, not a no-op.
#
# Comments only: this mechanism deliberately cannot pin a snomed_code. The moment
# it can, it becomes a way to hand-write mappings around CONFIDENCE_THRESHOLD and
# the gate, and the table stops being 'what the service returned, gated'.
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
                     f"{now}. The note was written about {target}, so it cannot "
                     f"be carried over. Re-read the row, then update or delete "
                     f"the entry.")
        if not comment:
            sys.exit(f"  comment {code} -> {target} is empty — delete the entry "
                     f"rather than leaving it blank.")
        row["comment"] = comment


# --------------------------------------------------------------------------- #
# Row construction
# --------------------------------------------------------------------------- #


def build_row(item, fhir_base, service, timeout):
    """One CSV row: the service asked once, its answer gated.

    The proposal is recorded whether or not it survives — a row rejected at
    CONFIDENCE_THRESHOLD or at the gate keeps its `codesearch_target` and
    `codesearch_reasoning`, so the committed table shows what was considered and
    on what ground it was declined, rather than only that nothing was found.
    """
    code, label = item
    row = {c: "" for c in CURATED_COLUMNS + PROVENANCE_COLUMNS
           + LOG_ONLY_COLUMNS}
    row["mimic_code"] = code
    row["mimic_display"] = label

    # BEFORE the service, not after: there is no text here for an answer to be
    # right about, so an answer is not evidence and asking for one only creates
    # something that has to be argued away. The proposal columns stay empty,
    # which is the honest record of a row that was never asked.
    if code in NO_CLINICAL_CONTENT:
        row["codesearch_status"] = "no-content"
        row["comment"] = declined_comment(row, 0.0)
        return row

    confidence = 0.0
    try:
        result = find_code(service, TEMPLATE.format(label), timeout)
    except Exception as exc:                          # noqa: BLE001
        row["codesearch_status"] = f"error: {str(exc)[:80]}"
        result = None
    if result is not None:
        row["path"] = result.get("path", "")
        matches = result.get("matches") or []
        if not matches:
            row["codesearch_status"] = "no-match"
        else:
            match = matches[0]
            confidence = float(match.get("confidence") or 0.0)
            row["codesearch_confidence"] = f"{confidence:.2f}"
            row["codesearch_reasoning"] = (match.get("reasoning") or "").strip()
            row["codesearch_target"] = match["code"]
            row["codesearch_display"] = match.get("display", "")
            if confidence < CONFIDENCE_THRESHOLD:
                row["codesearch_status"] = "below-threshold"
            else:
                status, display = gate(fhir_base, match["code"])
                row["codesearch_status"] = status
                if status == "ok":
                    row.update(snomed_code=match["code"],
                               snomed_display=display)
                    return row

    row["comment"] = declined_comment(row, confidence)
    return row


def declined_comment(row, confidence):
    """Why a row carries no target.

    load_table requires one, and rightly: an empty target is a claim that the
    source could not answer, and a claim has to say what it rests on.
    """
    proposal = (f"{row['codesearch_target']} "
                f"|{row['codesearch_display']}| at {confidence:.2f}")
    return {
        "no-content": (f"{row['mimic_code']} is "
                       f"{NO_CLINICAL_CONTENT.get(row['mimic_code'], '')}, so "
                       f"it was not sent to code-search: there is no text for "
                       f"an answer to be right about."),
        "no-match": (f"code-search returned no match within "
                     f"{CONSTRAINT_ECL}."),
        "below-threshold": (f"code-search proposed {proposal}, below the "
                            f"{CONFIDENCE_THRESHOLD} threshold."),
        "not-in-constraint": (f"code-search proposed {proposal} but the server "
                              f"does not place that concept in "
                              f"{CONSTRAINT_ECL}, so it is not a specimen."),
        "retired": (f"code-search proposed {proposal} but that concept is "
                    f"retired."),
        "extension": (f"code-search proposed {proposal} but that concept is not "
                      f"in the SNOMED international core."),
        "absent": f"code-search proposed {proposal} but that code is not known.",
        "no-display": (f"code-search proposed {proposal} but it has no usable "
                       f"display."),
    }.get(row["codesearch_status"], f"code-search: {row['codesearch_status']}.")


# --------------------------------------------------------------------------- #
# Reporting
# --------------------------------------------------------------------------- #


def report(rows):
    """What the run found. Printed so it can be pasted into a write-up."""
    mapped = [r for r in rows if r["snomed_code"]]
    print(f"\n  {len(rows)} item(s): {len(mapped)} mapped, "
          f"{len(rows) - len(mapped)} declared unmapped")

    statuses = {}
    for row in rows:
        statuses[row["codesearch_status"]] = \
            statuses.get(row["codesearch_status"], 0) + 1
    print("\n  code-search answer status")
    for status, count in sorted(statuses.items()):
        print(f"    {status:<18} {count:>4}")

    scored = sorted(float(r["codesearch_confidence"]) for r in rows
                    if r["codesearch_confidence"])
    if scored:
        print(f"\n  code-search confidence, {len(scored)} answered")
        buckets = [(1.0, 1.01), (0.9, 1.0), (0.8, 0.9), (0.7, 0.8), (0.0, 0.7)]
        for low, high in buckets:
            hits = [s for s in scored if low <= s < high]
            label = f"{low:.2f}" if high > 1.0 else f"{low:.2f}–{high:.2f}"
            print(f"    {label:<12} {len(hits):>4}")
        print(f"    threshold {CONFIDENCE_THRESHOLD}: "
              f"{sum(1 for s in scored if s >= CONFIDENCE_THRESHOLD)} kept, "
              f"{sum(1 for s in scored if s < CONFIDENCE_THRESHOLD)} dropped")

    # Two source labels sharing a target is a real possibility here — `Fluid` and
    # `Other Body Fluid` are both unspecific — and it is not automatically wrong,
    # but it makes two MIMIC specimen types indistinguishable after translation,
    # so it is printed rather than left to be found.
    shared = {}
    for row in mapped:
        shared.setdefault((row["snomed_code"], row["snomed_display"]),
                          []).append(row["mimic_code"])
    crowded = sorted(((len(v), k, v) for k, v in shared.items()), reverse=True)
    print(f"\n  {len(shared)} distinct target(s) for {len(mapped)} mapped item(s)")
    for count, (code, display), members in crowded:
        if count > 1:
            print(f"    {count:>3} items -> {code:<12} {display[:40]:<40} "
                  f"{', '.join(sorted(members))}")

    commented = [r for r in rows if r["snomed_code"] and r["comment"]]
    if commented:
        print(f"\n  {len(commented)} mapped row(s) carrying a reviewed comment")
        for row in commented:
            print(f"    {row['mimic_code'][:26]:<26} -> "
                  f"{row['snomed_code']:<11} {row['snomed_display'][:40]}")

    unmapped = [r for r in rows if not r["snomed_code"]]
    print(f"\n  {len(unmapped)} unmapped, declared:")
    for row in unmapped:
        print(f"    {row['mimic_code'][:30]:<30} {row['codesearch_status']}")


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
                             "probing a handful of items. Implies --dry-run: a "
                             "table built from a subset would drop every item "
                             "it did not ask about.")
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

    print(f"  {len(items)} IG code(s)"
          + (f" (subset of {len(codes)}, --only)" if args.only else ""))
    print(f"  gate:       {args.fhir_base}")
    print(f"  service:    {args.service}")
    print(f"  ECL:        {CONSTRAINT_ECL}")
    print(f"  template:   {TEMPLATE}  (the identity wrapper — the label as it "
          f"stands)")
    print(f"  threshold:  {CONFIDENCE_THRESHOLD}")
    print(f"  pre-filter: {len(NO_CLINICAL_CONTENT)} code(s) not searched: "
          f"{', '.join(sorted(NO_CLINICAL_CONTENT))}")
    print(f"  comments:   {len(COMMENT_OVERRIDES)}\n")

    # Before any search: a pre-filter naming a code the IG has dropped declines
    # nothing, and says nothing about it.
    validate_no_clinical_content(codes)

    def work(item):
        row = build_row(item, args.fhir_base, args.service, args.timeout)
        print(f"    {row['mimic_code'][:26]:<26} "
              f"{row['codesearch_status']:<18} {row['snomed_code'] or '—':<12} "
              f"{row['snomed_display'][:40]}", flush=True)
        return row

    with concurrent.futures.ThreadPoolExecutor(args.workers) as pool:
        rows = list(pool.map(work, items))

    # Sorted by mimic_code so a re-run diffs only where an answer changed, not
    # wherever the thread pool happened to finish first.
    rows.sort(key=lambda r: r["mimic_code"])

    # A transport failure is not an answer. Writing a table whose gaps are half
    # findings and half a service that stopped answering would ship something
    # that reads like a result and is not one, so a partial run writes nothing.
    failed = [r for r in rows if r["codesearch_status"].startswith("error")]
    if failed:
        print(f"\n  {len(failed)} of {len(rows)} code-search call(s) failed "
              f"after retries — NOT writing {OUT_CSV.name}.")
        for row in failed:
            print(f"    {row['mimic_code'][:26]:<26} "
                  f"{row['codesearch_status'][:70]}")
        sys.exit("  Fix the service and re-run; cached answers make the retry "
                 "cheap.")

    # After the failure gate, so a run where the service dropped out reports the
    # transport failure rather than a wall of comments that could not match
    # because their targets never arrived.
    apply_comments(rows)
    report(rows)

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
        # Every hand decision that touched this table, so the log records the
        # curation as well as the run. The rest is whatever the service said,
        # gated.
        "no_clinical_content": dict(sorted(NO_CLINICAL_CONTENT.items())),
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
