#!/usr/bin/env python3
"""Generate conceptmaps/spec-type-snomed.csv — MIMIC's 104 microbiology specimen
descriptions -> SNOMED CT.

The ninth generated table, the second for `Specimen.type`, and the one that
completes that field: with it the map covers all 116 codes its sourceCanonical
admits. `mimic-spec-type-desc` holds the values of MIMIC's
`microbiologyevents.spec_type_desc` column — what the laboratory recorded as the
material it received. They carry 1,587,214 occurrences, 10.6% of the element,
the other 89.4% being the sibling `mimic-lab-fluid` stream.

INHERITS ITS QUERY SETUP FROM build_lab_fluid_table.py, deliberately and without
re-deriving it: same target system, same CONSTRAINT_ECL, same identity TEMPLATE,
same CONFIDENCE_THRESHOLD. The two streams are the same element, read off two
MIMIC columns, and a setting that differed between them would make the field's
coverage numbers incomparable for no stated reason. What is new here is the
population, so that is what was probed. See the field's issue (#24 in
fhnaumann/master_thesis_pipeline) for the target-system analysis — why SNOMED CT,
and why not the FHIR R4 example binding to HL7 v2 table 0487, LOINC's System-axis
Parts, or OHDSI's Specimen domain.

WHAT WAS PROBED, AND WHY THOSE THINGS. The constraint's job — keeping a
substance, body structure or physical object out of `Specimen.type` — was already
settled on the sibling stream over 24 labels. It cannot, however, catch a
WRONG-BUT-LEGAL SPECIMEN: a concept genuinely inside `<<123038009` that is wrong
about WHICH specimen. Neither can the gate, and neither can confidence. This
population has three label shapes that could produce one, so about 60 labels were
probed across them:

  specimen + test/organism qualifier   `Blood (EBV)`, `THROAT FOR STREP`,
                                       `SWAB, R/O GC`, `Staph aureus swab`
  the blood-culture family             five distinct MIMIC columns whose labels
                                       differ only by a parenthetical
  body site only / junk                `EAR`, `EYE`, `THROAT`, `XXX`

ZERO defects in the first two shapes. All five `Blood (...)` rows returned
119297000 |Blood specimen| at 0.85 — the parenthetical organism was IGNORED, not
followed, which is the failure that was being looked for. The blood-culture family
resolved to FOUR distinct targets rather than collapsing onto one:

    BLOOD CULTURE                          446131002 |Blood specimen obtained
    BLOOD CULTURE - NEONATE                            for blood culture|  0.85
    BLOOD CULTURE (POST-MORTEM)
    BLOOD CULTURE ( MYCO/F LYTIC BOTTLE)   878861003 |Blood specimen in blood
    FLUID RECEIVED IN BLOOD CULTURE BOTTLES            culture bottle|     0.80
    Stem Cell - Blood Culture              57731000052104 |Stem cell specimen|
    BLOOD BAG FLUID                        119304001 |Specimen from blood bag|

The 3->1 collapse of the first three is not a defect: SNOMED files no
neonate-qualified or post-mortem-qualified blood-culture specimen, so three MIMIC
columns legitimately share one target.

The `BLOOD CULTURE` procedure leak that the field's issue reported — code-search
matching the INACTIVE 145540002 on an exact FSN hit, following a `SAME_AS`
association OUT of the requested value set and returning an AU-extension PROCEDURE
at 0.95 while declaring `inVS: false` itself — is GONE. `provenance` was null on
all ~60 probes. The membership check build_lab_fluid_table.py introduced is
inherited here anyway, for the reason it was introduced: "the service was asked
nicely and currently complies" is not a property a committed table should rest on.

NO PRE-FILTER, WHICH IS A FINDING RATHER THAN AN OMISSION. About a fifth of this
population names a laboratory TEST rather than a specimen — `MRSA SCREEN`,
`IMMUNOLOGY`, `CRE Screen` — and `Specimen.type` cannot legally hold a test. The
field's issue proposed declining them unasked, the way build_outputevents_table.py
declines the items that record no volume and build_chartevents_table.py declines
the documentation items. Probing 16 of them shows the rule would be redundant:

    IMMUNOLOGY / Immunology (CMV) / MRSA SCREEN / CRE Screen /
    Cipro Resistant Screen / C, E, & A Screening / Infection Control Yeast /
    Influenza A/B by DFA / RAPID RESPIRATORY VIRAL ANTIGEN TEST /
    Rapid Respiratory Viral Screen & Culture /
    DIRECT ANTIGEN TEST FOR VARICELLA-ZOSTER VIRUS      -> no-match, 0.00
    VIRAL CULTURE                       621000009105    -> 0.75, below threshold
    POSTMORTEM CULTURE                  258484005       -> 0.75, below threshold
    POST-MORTEM VIRAL CULTURE           258484005       -> 0.70, below threshold

13 of 16 decline themselves, and the shape of the failure is worth recording: a
label with NO specimen noun in it returns no candidate AT ALL, not a confident
wrong one. It is the search declining, not the threshold catching. A hand-written
reject list would be duplicating work the constraint already does, and every entry
in it would be a decision a reader has to check.

The two rows that pass are not really failures either. `Swab R/O Yeast Screen` ->
257261003 |Swab| and `SEROLOGY/BLOOD` -> 119297000 |Blood specimen| both take the
specimen noun that IS literally present in the label and drop the test verb, which
is the correct `Specimen.type` for those rows.

For the same reason there is no NO_CLINICAL_CONTENT list here, unlike the sibling
stream. `XXX` and `MICRO PROBLEM PATIENT` both return no-match at 0.00 on their
own. They are junk, but they are long enough to miss cleanly, where `I` and `Q`
are single letters that collide with real short displays — which is exactly why
that rule exists there and is not needed here.

THE THRESHOLD STAYS AT 0.8, and on this population that is measured rather than
inherited. Two rows sit on the boundary pulling in OPPOSITE directions:

    FECAL SWAB          258528007 |Rectal swab|  0.75  <- wrong; a rectal swab is
                                                          not stool. The
                                                          THRESHOLD stops it, not
                                                          the gate.
    Staph aureus swab   257261003 |Swab|         0.80  <- right, and exactly at
                                                          the cut.

So raising the threshold to catch a wrong row would drop a correct one, and
lowering it would admit `FECAL SWAB`. It is doing real work in both directions.

KNOWN DEFECT, and a second row that is one whitespace character away from being
the same defect:

    70024  VIRAL CULTURE: R/O CYTOMEGALOVIRUS
             -> 621000009105 |Viral isolate specimen| at exactly 0.80, gate ok

This is a FABRICATION. The label names the test that was ordered; the material the
culture was run on — swab, lavage, urine — is not recorded anywhere in the row, so
there is no evidence for any specimen. It is nonetheless a legal member of
`<<123038009`, so no constraint reaches it and the gate passes it on merit.

Its sibling `70041 VIRAL CULTURE:R/O HERPES SIMPLEX VIRUS` does NOT leak, and the
reason is worth stating because it is not a semantic one:

    VIRAL CULTURE:R/O HERPES SIMPLEX VIRUS   (no space, as MIMIC spells it)
      -> no-match, 0.00
    VIRAL CULTURE: R/O HERPES SIMPLEX VIRUS  (one space added)
      -> 621000009105 |Viral isolate specimen|, 0.80, ok

Same target, same score as 70024. A single space after the colon is the entire
difference between declining and fabricating, so this population's decline
behaviour on the viral-culture family is partly an artifact of inconsistent source
punctuation rather than a robust boundary. If MIMIC ever normalises whitespace in
these labels, 70041 begins leaking too. Both rows are named here so that is a
known trigger rather than a surprise.

WHY THERE IS NO REJECT LIST FOR IT, having considered one. The mechanism exists —
build_datetimeevents_table.py's WRONG_ACTION and build_micro_org_table.py's
WRONG_TAXON both decline a (source, target) PAIR for exactly this failure class,
and both are validated AFTER the run so that an entry matching no row is fatal.
That last property is what rules it out here: an entry for 70041 could not be
written, because 70041 does not currently leak and the entry would fail the build.
A one-row list that cannot cover the row most likely to leak next is a maintenance
surface bought for nothing. Recorded as a defect instead, in the style of
build_d_items_table.py's `227719 AVA` and build_labevents_table.py's
`50823 Required O2`. A consumer should drop 70024.

ONE SEARCH PER CASE-FOLDED LABEL. 104 codes collapse to 93 distinct labels, so 11
searches are saved — but the saving is not the point, the consistency is:

    7  70040 70067 70068 70069 70070 70084 SWAB  +  90928 Swab
    3  70077 70079 70081 URINE
    2  70073 70076 TISSUE
    2  70035 70051 FLUID,OTHER
    2  70032 70088 Blood (EBV)

MIMIC files the same specimen under several itemids, and two of them receiving
different targets would make one specimen type two after translation. The fan-out
below makes that unrepresentable, and it is then ASSERTED rather than assumed.

Case-FOLDED, following build_chartevents_table.py: casing is not meaning, and
without it `90928 Swab` searches separately from the six `SWAB` codes and could
land somewhere else. The string actually SENT is the alphabetically first spelling
among a family's members — arbitrary but deterministic, so a re-run cannot
silently switch which variant was asked about and churn the diff. It is recorded
per row in `codesearch_query`, which is why that column exists here and not in the
sibling stream, where the sent string was always `mimic_display` exactly.

WHAT TO EXPECT. Higher than the ~74% of codes the field's issue predicted. That
estimate assumed the body-site labels (`EAR`, `EYE`, `THROAT`) and the physical
objects were unmappable; both assumptions were refuted. The body sites map at
0.90-0.95, and the awkward tail maps 10 for 10 — SNOMED files dedicated concepts
for the whole of it:

    CATHETER TIP-IV     119312009 |Catheter tip submitted as specimen|      0.85
    FOREIGN BODY        447103002 |Foreign body submitted as specimen|      0.95
    ARTHROPOD           734338009 |Arthropod material submitted as specimen|0.90
    WORM                704663000 |Parasitic worm specimen|                 0.95
    SCOTCH TAPE PREP    258664003 |Scotch tape slide specimen|              0.90
    Touch Prep/Sections 1380394001 |Tissue impression specimen|             0.85
    Isolate             119303007 |Microbial isolate specimen|              0.85
    HAIR                119326000 |Hair specimen|                           0.97
    NAIL SCRAPINGS      447098004 |Specimen from nail obtained by scraping| 0.85

Do not read the number off this docstring in any case — quote the stream's
entry in output/stream-report.json and its row in
output/mapping-statistics.csv, which are computed from the committed table.

READ A `no-match` ACCORDINGLY: it means "the service declined it on that run under
that configuration", NOT "SNOMED has no such concept". `codesearch_service` in the
generation log pins the configuration, which is what lets "the answers moved" be
told apart from "the service moved".

Why it is NOT part of `make mappings`. Same as every generator here: it needs the
network and a model-backed service, and it is the one stage whose output is not a
pure function of this repo. Determinism lives in the split — this runs
occasionally and by hand, its output is committed, and `make mappings` reads the
committed CSV and never a server, so `make mappings && git diff --exit-code` stays
a valid test.

    make spec-type-table ARGS=--insecure

Equivalence is not this script's concern. Every mapping a table supplies is
`relatedto`, set by lib/assemble.py when it builds the group; see lib/curated.py
for why a per-row equivalence column went away.

Output columns. The five in CURATED_COLUMNS are what the builder reads; everything
after them is provenance, ignored by the build and present so a reader can audit
any row — what the service proposed, at what confidence, on what reasoning, and
what string it was asked — without re-running this script.
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
# all but two international core. Inherited unchanged from the sibling
# mimic-lab-fluid stream: the two streams are the same bound element read off two
# MIMIC columns, and a constraint that differed between them would make the
# field's coverage numbers incomparable for no stated reason.
CONSTRAINT_ECL = "<<123038009"

# The identity wrapper: this stream sends the label as it stands, like the
# sibling stream and like micro-org. These labels are already specimen nouns.
# See the module docstring for the wrapper that was probed against them and
# rejected — it made two test-name rows accept a FABRICATED specimen they had
# correctly declined bare.
TEMPLATE = "{}"

# Below this, code-search's answer is discarded and the item is left unmapped.
# Measured on this population rather than inherited: `FECAL SWAB` at 0.75 is
# WRONG (a rectal swab is not stool) and `Staph aureus swab` at exactly 0.80 is
# RIGHT, so the threshold is doing real work in both directions and moving it
# either way costs something. The distribution is printed at the end of every run
# so this can be revisited with evidence rather than by taste.
CONFIDENCE_THRESHOLD = 0.8

# NO PRE-FILTER HERE, deliberately, and unlike the sibling stream's
# NO_CLINICAL_CONTENT. The ~20 labels that name a laboratory TEST rather than a
# specimen decline themselves — 13 of 16 probed returned no candidate AT ALL —
# and `XXX` / `MICRO PROBLEM PATIENT` return no-match at 0.00 unaided. A rule
# that declines what the search already declines adds decisions a reader has to
# check and catches nothing. See the module docstring for the probe results.

# --------------------------------------------------------------------------- #
# Paths and provenance
# --------------------------------------------------------------------------- #

TERM = Path(__file__).resolve().parents[1]
OUT_CSV = Path(__file__).resolve().parent / "spec-type-snomed.csv"
LOG_JSON = TERM / "output" / "spec-type-generation-log.json"

# What the service proposed on every row, including rows where the proposal was
# then rejected by the threshold or by the gate — so that "this item is unmapped"
# is auditable in the committed diff rather than only in a run that has since
# scrolled away.
#
# `codesearch_query` is present here and absent from the sibling stream, because
# the case-folded family collapse means the string sent is NOT always
# `mimic_display`: `90928 Swab` is asked about as `SWAB`, the alphabetically
# first spelling in its family. A column recording the sent string is what makes
# the collapse visible in the committed CSV rather than only in the log.
#
# `codesearch_status` and `codesearch_confidence` are the two columns
# lib/stats.py reads for the per-stream statistics, so the vocabulary stays the
# one the other tables use.
#
# The build ignores all of them: lib.curated.load_table reads CURATED_COLUMNS and
# discards the rest.
PROVENANCE_COLUMNS = ["codesearch_query", "codesearch_target",
                      "codesearch_display", "codesearch_confidence",
                      "codesearch_status", "codesearch_reasoning"]

# Recorded per row in the log only. `path` (cached / fast / agentic) says how
# this run fetched an answer, not anything about the answer, so it would flip to
# "cached" on the next run and show up as a wall of changed rows in a diff where
# no mapping moved.
LOG_ONLY_COLUMNS = ["path"]

# --------------------------------------------------------------------------- #
# Sources
# --------------------------------------------------------------------------- #


def ig_codes():
    """(code, display) for the 104 specimen descriptions, read from the IG itself.

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

    ASSERTED RATHER THAN ASSUMED, inherited from build_lab_fluid_table.py. It was
    introduced there because the constraint was found to LEAK: on `BLOOD CULTURE`
    code-search matched an INACTIVE concept on an exact FSN hit, followed a
    `SAME_AS` historical association OUT of the requested value set, and returned
    an AU-extension PROCEDURE at 0.95 while declaring `provenance.inVS: false` in
    its own response.

    That bug is fixed service-side — `BLOOD CULTURE` now answers
    446131002 |Blood specimen obtained for blood culture| at 0.85, and
    `provenance` was null on all ~60 probes behind this stream. The check stays,
    because "the service was asked nicely and currently complies" is not a
    property a committed table should rest on.

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

    What it CANNOT catch is a concept that passes every check and is still the
    wrong specimen — see the 70024 defect in the module docstring. That failure
    class is why this population was probed the way it was, and the probes found
    exactly one instance in ~60 labels.

    The display returned is the server's preferred term, not whatever string the
    service carried next to the code. That is what keeps verify-curated's fourth
    check — display must be a real designation of the concept — green by
    construction.
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
# Empty on the first run: which rows need one is a question about what the service
# actually returned over the whole population, so the entries are written after
# reading the generated table, not guessed before it exists. The known candidate
# is 70024 -> 621000009105, the fabricated |Viral isolate specimen| described in
# the module docstring; it is deliberately NOT pre-written, because a run that
# scored it differently would then fail on an entry nobody had re-read.
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


def search_label(label, fhir_base, service, timeout):
    """One search for one case-folded label family: asked once, answer gated.

    Returns only the answer fields, so main() can fan the SAME dict across every
    itemid sharing the label. Identity fields (`mimic_code`, `mimic_display`) are
    deliberately absent — they belong to the row, not to the query.

    The proposal is recorded whether or not it survives: a family rejected at
    CONFIDENCE_THRESHOLD or at the gate keeps its `codesearch_target` and
    `codesearch_reasoning`, so the committed table shows what was considered and
    on what ground it was declined, rather than only that nothing was found.
    """
    answer = {c: "" for c in ["snomed_code", "snomed_display", "comment"]
              + PROVENANCE_COLUMNS + LOG_ONLY_COLUMNS}
    answer["codesearch_query"] = TEMPLATE.format(label)

    confidence = 0.0
    try:
        result = find_code(service, TEMPLATE.format(label), timeout)
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
                    answer.update(snomed_code=match["code"],
                                  snomed_display=display)
                    return answer

    answer["comment"] = declined_comment(answer, confidence)
    return answer


def declined_comment(answer, confidence):
    """Why a row carries no target.

    load_table requires one, and rightly: an empty target is a claim that the
    source could not answer, and a claim has to say what it rests on.
    """
    proposal = (f"{answer['codesearch_target']} "
                f"|{answer['codesearch_display']}| at {confidence:.2f}")
    return {
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
    }.get(answer["codesearch_status"],
          f"code-search: {answer['codesearch_status']}.")


# --------------------------------------------------------------------------- #
# Reporting
# --------------------------------------------------------------------------- #


def report(rows, queries):
    """What the run found. Printed so it can be pasted into a write-up."""
    mapped = [r for r in rows if r["snomed_code"]]
    print(f"\n  {len(rows)} item(s) over {len(queries)} quer(ies): "
          f"{len(mapped)} mapped, {len(rows) - len(mapped)} declared unmapped")

    statuses = {}
    for row in rows:
        statuses[row["codesearch_status"]] = \
            statuses.get(row["codesearch_status"], 0) + 1
    print("\n  code-search answer status (per item, after fan-out)")
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

    # Two source labels sharing a target is expected here and is not automatically
    # wrong — SNOMED files no neonate- or post-mortem-qualified blood-culture
    # specimen, so those MIMIC columns legitimately share one. It does make two
    # MIMIC specimen types indistinguishable after translation, so it is printed
    # rather than left to be found. Rows sharing a target because they shared a
    # QUERY are the collapse working and are not news; this lists targets reached
    # by DIFFERENT queries.
    shared = {}
    for row in mapped:
        shared.setdefault((row["snomed_code"], row["snomed_display"]),
                          set()).add(row["codesearch_query"])
    crowded = sorted(((len(v), k, v) for k, v in shared.items()), reverse=True)
    print(f"\n  {len(shared)} distinct target(s) for {len(mapped)} mapped item(s)")
    for count, (code, display), sent in crowded:
        if count > 1:
            print(f"    {count:>3} queries -> {code:<16} {display[:34]:<34} "
                  f"{'; '.join(sorted(sent))[:60]}")

    commented = [r for r in rows if r["snomed_code"] and r["comment"]]
    if commented:
        print(f"\n  {len(commented)} mapped row(s) carrying a reviewed comment")
        for row in commented:
            print(f"    {row['mimic_code']:<8} {row['mimic_display'][:26]:<26} "
                  f"-> {row['snomed_code']:<16} {row['snomed_display'][:34]}")

    unmapped = [r for r in rows if not r["snomed_code"]]
    print(f"\n  {len(unmapped)} unmapped, declared:")
    for row in unmapped:
        print(f"    {row['mimic_code']:<8} {row['mimic_display'][:34]:<34} "
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

    rows_by_code = {}
    for code, label in items:
        row = {c: "" for c in CURATED_COLUMNS + PROVENANCE_COLUMNS
               + LOG_ONLY_COLUMNS}
        row["mimic_code"] = code
        # The IG's exact string, which load_curated requires. NOT the collapsed
        # spelling that gets sent — that lands in `codesearch_query`.
        row["mimic_display"] = label
        rows_by_code[code] = row

    # One search per CASE-FOLDED label. MIMIC files the same specimen under
    # several itemids (7 x SWAB, 3 x URINE), and two of them receiving different
    # targets would make one specimen type two after translation.
    #
    # Case-folded following build_chartevents_table.py: casing is not meaning,
    # and without it `90928 Swab` searches separately from the six `SWAB` codes.
    # The string SENT is the alphabetically first spelling among the members —
    # arbitrary but deterministic, so a re-run cannot silently switch which
    # variant was asked about and churn the diff.
    spellings = {}
    for code, label in items:
        spellings.setdefault(label.casefold(), set()).add(label)
    queries = {}
    for code, label in items:
        queries.setdefault(sorted(spellings[label.casefold()])[0], []).append(code)
    ordered = sorted(queries)

    print(f"  {len(items)} IG code(s)"
          + (f" (subset of {len(codes)}, --only)" if args.only else ""))
    print(f"  queries:    {len(items)} item(s) collapse to {len(ordered)} "
          f"case-folded label(s)")
    print(f"  gate:       {args.fhir_base}")
    print(f"  service:    {args.service}")
    print(f"  ECL:        {CONSTRAINT_ECL}")
    print(f"  template:   {TEMPLATE}  (the identity wrapper — the label as it "
          f"stands)")
    print(f"  threshold:  {CONFIDENCE_THRESHOLD}")
    print(f"  pre-filter: none — the test-name labels decline themselves; see "
          f"the module docstring")
    print(f"  comments:   {len(COMMENT_OVERRIDES)}\n")

    def work(label):
        answer = search_label(label, args.fhir_base, args.service, args.timeout)
        members = sorted(queries[label])
        fanned = f"x{len(members)}" if len(members) > 1 else ""
        print(f"    {label[:34]:<34} {answer['codesearch_status']:<18} "
              f"{answer['snomed_code'] or '—':<16} "
              f"{answer['snomed_display'][:32]:<34} {fanned}", flush=True)
        return answer

    with concurrent.futures.ThreadPoolExecutor(args.workers) as pool:
        answers = dict(zip(ordered, pool.map(work, ordered)))

    # Fan each query's one answer back across the itemids sharing its case-folded
    # label. This is what makes `70069 SWAB` and `90928 Swab` disagreeing
    # unrepresentable.
    for label, members in queries.items():
        for code in members:
            rows_by_code[code].update(answers[label])

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
        sys.exit("  Fix the service and re-run; cached answers make the retry "
                 "cheap.")

    # The invariant the collapse exists to guarantee, asserted rather than
    # assumed. The fan-out above makes divergence structurally impossible, so
    # this can only fire if the grouping and the fan-out ever stop agreeing — and
    # the whole point of the rule is that a reader should not have to trust that
    # they do.
    diverged = {label: sorted({rows_by_code[c]["snomed_code"] or "(unmapped)"
                               for c in members})
                for label, members in queries.items()
                if len({rows_by_code[c]["snomed_code"] for c in members}) > 1}
    if diverged:
        for label, targets in sorted(diverged.items()):
            print(f"    {label}: {targets}", file=sys.stderr)
        sys.exit(f"  {len(diverged)} quer(ies) whose itemids ended up on "
                 f"different targets, which the case-folded label collapse "
                 f"exists to prevent. NOT writing {OUT_CSV.name}.")

    # After the failure gate, so a run where the service dropped out reports the
    # transport failure rather than a wall of comments that could not match
    # because their targets never arrived.
    apply_comments(rows)
    report(rows, ordered)

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
        # Which itemids shared a query, so the collapse is auditable without
        # re-deriving it from the IG.
        "query_key": ["casefolded_display"],
        "shared_queries": {label: sorted(members)
                           for label, members in sorted(queries.items())
                           if len(members) > 1},
        # Every hand decision that touched this table, so the log records the
        # curation as well as the run. There is no pre-filter here, which is
        # itself a decision — recorded as an empty dict rather than omitted, so
        # a reader can tell "no rule" from "this generator has no such concept".
        "no_clinical_content": {},
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
