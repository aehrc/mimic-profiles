#!/usr/bin/env python3
"""Generate conceptmaps/formulary-drug-standard.csv — MIMIC pharmacy formulary
codes -> RxNorm and SNOMED CT.

Stream 4 of MedicationAdministration.medication[x] (issue #27), and the one that
decides the field's headline number: 2,188 observed codes carrying 26,312,387
occurrences, 71.6% of the element. It follows build_medication_name_table.py in
shape — a deterministic term join first, code-search only for what the join
cannot reach, the build offline and byte-reproducible — and differs from it in
exactly two places, both evidenced by probe rounds recorded in #27: the
CONFIDENCE THRESHOLD, and a normalisation layer for pharmacy label noise that
the drug-name population simply did not have.

    make formulary-drug-table ARGS=--insecure

SAME CONSTRAINT AS THE DRUG-NAME STREAM, deliberately and to the character:

    (rxnorm)(TTY=IN;TTY=PIN;TTY=MIN;TTY=BN;TTY=SCD;TTY=GPCK;TTY=BPCK)

That is not laziness about a new population; it is what lets this generator
JOIN AGAINST THE COMMITTED TERM INDEX rather than pull its own. The index is
keyed to that constraint, lib/termindex.load_index asserts the two agree, and
the alternative — a second index under a second constraint — would mean two
committed files describing RxNorm, refreshed at different times, with nothing
comparing them.

TTY=SBD WAS RE-TESTED HERE AND STAYS OUT, which #27 required rather than
assumed: #25's A/B ran over bare ingredient labels, and these labels DO state
brand, strength, form and packaging, so the asymmetry that justified dropping
SBD there could have inverted. Over 40 labels / 7.2M occurrences it partly did —
on labels that literally name a brand, SBD is more faithful, and that is
1,142,937 occurrences against 268,008 of surviving invention, the opposite ratio
to #25. Three things still decide it against:

  * A plain swap LOSES mapped mass, 5.89M -> 5.56M, by a mechanism #25 never
    saw: SBD depresses confidence on generic-only labels by splitting the
    candidate pool. `Senna 8.6 mg Tablet` 0.85 -> 0.80, `Azithromycin 500 mg /
    250 mL 5% Dextrose` 0.85 -> 0.80, four rows crossing the gate downward with
    an UNCHANGED code.
  * A's losses stay omissions and B's gains include a commission. `Tylenol
    8 Hour` -> `acetaminophen 650 MG 8HR ER Oral Tablet` is a true
    generalisation; `Prilosec OTC` -> `PriLOSEC OTC 20 MG DR Oral Tablet` at
    0.95 asserts a strength and a dose form the label never stated, and clears
    the gate.
  * The probe over-sampled brand-stating labels on purpose, so it understates
    the confidence tax and overstates the brand recovery.

If brand fidelity is wanted later it belongs in a narrow post-hoc rung — accept
the SCD, then look for an SBD child whose brand token appears verbatim in the
label — not in a wider search space that taxes every generic row. Deferred.

THRESHOLD 0.80, AND THIS IS THE ONE SETTING THAT DIVERGES FROM #25. That stream
uses 0.85, decided by `Senna`: a bare botanical name at 0.80 reaching the wrong
species. The rationale does not transfer, because these labels are not bare
names — they carry a strength token, and the strength token is what the scorer
checks hardest. Measured over a 70-label band-enriched probe, confidence is
quantised to 0.05 steps (there is no 0.81-0.84 sub-band, so the choice is
binary), and the ENTIRE 0.80 bucket is:

    895,677  Heparin Sodium 5,000 Unit Vial      1361615  correct (5000 U/mL x 1 mL)
    239,633  Heparin Sodium 25,000 unit Premix    1658717  correct (250 mL premix)
     79,996  Ipratropium Neb 2.5 mL Vial           836358  correct
     28,602  CeftriaXONE 1 g / 100 mL NaCl        1665021  lossy but true
     10,801  Nafcillin 2 g / 100 mL NaCl           311895  correct (= 20 mg/mL)
      8,597  Morphine 100 mg / 100 mL NaCl        1728802  correct (= 1 mg/mL)
      5,838  Amiodarone 450 mg / 250 mL NaCl      1663276  correct (= 1.8 mg/mL)
      4,744  Clindamycin 600 mg Premix Bag         309335  correct

Zero wrong answers in the band, by row and by occurrence. The real errors sit at
0.50 — `Ondansetron 16 mg / 50 mL` proposing a 32 MG product, `Diltiazem 125 mg
/ 100 mL` proposing 5 MG/ML — because a strength error is what the scorer
punishes hardest, so it does not park them near the gate. Staying at 0.85 would
decline 1,273,888 occurrences of correct mappings, 895,677 of them one row: the
element's fourth-largest label, on an answer that is exactly right.

Do not go lower. The next stop below 0.80 is 0.75, which buys two correct
cefazolin rows (42,930 occurrences), and the stop after that is 0.50, where the
substance and strength errors live.

TEMPLATE: none, as in #25 — these strings already ARE drug names. A wrapper was
re-tested here and rejected again. On informative labels it is neutral on
identity and mildly DEFLATES confidence (0.95 -> 0.90); its one real benefit was
on uninformative mnemonic labels, and THE_UNINFORMATIVE_LABEL_RULE below removes
that population from the service's reach entirely, which is a structural fix
where the template was a probabilistic one.

NORMALISATION: QUERY-SIDE ONLY, and narrow on purpose. The committed
`mimic_display`, the source enumeration and the term index are all untouched;
only the string sent to the index and the service is rewritten. Three rules,
each with its own evidence, and the two rules NOT adopted matter as much:

  N1  strip `*NF*`, the non-formulary marker (105 codes, 148,633 occurrences).
      Across 8 probe pairs it never changed the IDENTITY of the answer — what
      it changes is confidence, non-monotonically and across the gate in both
      directions (`Loratadine 10mg Tab` 0.80 with it and 0.85 without,
      `Diazepam` 1.00 without and 0.85 with). Acceptance must not be a function
      of a pharmacy artefact.
  N2  strip runs of three or more underscores, a redaction artefact (63 codes,
      470,987 occurrences). 6 probe pairs, same code every time, same
      gate-straddling behaviour: `CefePIME 2 g / 100 mL NS ___` scores 0.80 with
      it and 0.85 without, on an identical target. Where the underscores are the
      WHOLE label the query goes empty, which THE_UNINFORMATIVE_LABEL_RULE then
      catches.
  N3  strip a parenthetical or asterisk-delimited run naming a CONTAINER or a
      COMPOUNDING note. `Ampicillin Sodium 2 g / 100 mL 0.9% Sodium Chloride
      (Mini Bag Plus)` returns NO MATCH; without the parenthetical it returns
      `1721476` at 0.85. `Calcium Gluconate 2 g STAT KIT (1g vial x #2)` is the
      same shape. The list is a DATA-DERIVED KEYWORD LIST rather than "strip
      parentheticals", because #25 established that a parenthetical is semantic
      by DEFAULT — `(Oral Solution)`, `(Extended Release)`, `(PF)`, `(Dilaudid)`
      and `(Envarsus XR)` all appear in this very population and every one of
      them must survive. Anything not on the list is left in.

  NOT ADOPTED — packaging nouns. The issue proposed stripping `Vial` / `Bag` /
      `Syringe` on the ground that RxNorm models packaging only at GPCK/BPCK.
      The premise is not borne out: across 16 probe arms NO GPCK or BPCK was
      ever returned, the service stays at SCD throughout, and stripping
      actively destroys the largest rows in the element. `HYDROmorphone
      (Dilaudid) 1mg/1mL Syringe` falls 0.95 -> 0.80 because "Prefilled Syringe"
      is an RxNorm DOSE FORM; the heparin premix silently moves from the 250 mL
      bag to the 10 mL vial. Packaging is signal here, not noise.
  NOT ADOPTED — `Floor Stock` (4 codes, 659,015 occurrences). All four are
      correct either way, but stripping loses the trailing `Bag`, which is what
      marks sodium chloride as an injectable solution rather than the salt, and
      326,783 occurrences fall below the gate.

THE_UNINFORMATIVE_LABEL_RULE, and it is the reason this stream needed a probe
round of its own. #27 counted 28 codes whose display is `___`. The real
population is worse: 63 contain `___` (35 of them on an otherwise perfect
label, which N2 handles), and a further 89 have a display EQUAL TO THE CODE —
`EPOP0.3NS100`, `ABE1200/400NS` — a class the issue does not list. Together,
121 codes and 225,898 occurrences carry no label at all.

The constraint and the threshold do NOT handle them. Eight of ten probed decline
correctly, but the two that answer both land exactly on the gate, and one of
them is the only confident commission found anywhere in 194 probes:

    NORE16/250NS  ->  1251499 estradiol 50 MCG / norethindrone acetate
                      250 MCG/Day Twice Weekly Transdermal System   at 0.85

reproduced on two independent runs, a member of the constraint, and it would
pass the gate and be committed. It is norepinephrine 16 mg / 250 mL. A pure
`NORE` prefix collision — and the identical mechanism produces a RIGHT answer
for `VASO40/100N`, which is exactly why no threshold can separate them.

So: after normalisation, if the query is empty OR equals the source code under
the index's own keying, the row is declared unmapped WITHOUT calling the
service. Deterministic, uniform, and not a per-item judgement. It costs
`VASO40/100N` (9,855 occurrences, right by luck) — an omission traded for a
commission, the direction this repo takes everywhere.

ORDERING IS LOAD-BEARING: the rule fires AFTER the term join, not before. Four
codes have display == code because the code IS a real brand name — `KCENTRA`,
`LITHOBID`, `PULMOZYME`, `VICODIN` — and the exact term join answers all four
(2,746 occurrences) with no service call and no judgement. Only the SERVICE call
is suppressed, which is precisely where the collision came from. As a bonus this
recovers `203321 Lithobid`, one of the two BN-retrieval misses #25 recorded as a
known limit of the service.

SHARED-DISPLAY FAN-OUT. 2,188 codes carry only 1,969 distinct labels; 128 labels
are shared by 347 codes (`Synthroid` x5, `Lipitor` x4, `Hydromorphone (Oral
Solution) 1 mg/1 mL` x4). The label is resolved ONCE per distinct normalised
query and the answer fanned to every member, so two codes for one drug cannot
receive different targets — the same treatment #24 gave the `SWAB` families.
Note this is a correctness guarantee first and a saving second: it removes only
89 calls, because most shared labels are also the ones the term join settles.

WHAT THE JOIN REACHES, measured offline against the committed index: 555 of
2,188 codes and 7,784,344 occurrences (29.6%) never reach the service at all —
421 by exact match, 52 after salt canonicalisation, 80 after dropping a trailing
parenthetical, 2 by both. Normalisation adds 17 of those outright. With the 117
codes the uninformative rule declines without a call, 1,516 codes reach
code-search as 1,427 distinct queries.

THE GATE, per target system, unchanged from #25 and applied as a filter rather
than an assertion:
  RxNorm  membership of CONSTRAINT_VCL, asserted with $validate-code against the
          VCL URL rather than assumed from having asked politely.
  SNOMED  exists, active, international core module rather than a national
          extension, and the display really is a designation.
Target displays are then replaced with the server's preferred term, so
verify-curated's display check passes by construction.

NOT PART OF `make mappings`: it needs the network and a model-backed service,
and it WRITES a build input. Determinism lives in the split — this runs by hand,
its output is committed, and the build reads the committed CSV and never a
server.

Usage:
  uv run .../build_formulary_drug_table.py --insecure
  uv run .../build_formulary_drug_table.py --append --insecure
  uv run .../build_formulary_drug_table.py --only NACLFLUSH,HEPA5I --insecure
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
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common import fhirclient                                     # noqa: E402
from common.cli import add_common_args, DEFAULT_CODE_SEARCH       # noqa: E402
from common.fhirclient import configure_tls, http                 # noqa: E402
from common import paths                                          # noqa: E402
from conceptmaps.lib.builders import (describe_population,        # noqa: E402
                                      table_population)
from conceptmaps.lib.canonical import RXNORM, SNOMED, TABLE_DIR    # noqa: E402
from conceptmaps.lib.termindex import (load_index, query_rungs,    # noqa: E402
                                       r3)

OUT_CSV = TABLE_DIR / "formulary-drug-standard.csv"
LOG_JSON = paths.OUTPUT / "formulary-drug-generation-log.json"

# The RxNorm release the index and the table were built from. Asserted on every
# run against what the server echoes back: a silent release bump would change
# committed answers with no diff to explain them. NOT pinned into the map —
# see lib/canonical.py UNVERSIONED_SYSTEMS for why those are different claims.
RXNORM_VERSION = "20231106"

# Character-identical to build_medication_name_table.CONSTRAINT_VCL, which is
# what lets this generator join against the committed term index. load_index
# asserts the index was built under it rather than trusting this comment.
CONSTRAINT_VCL = (f"({RXNORM})"
                  "(TTY=IN;TTY=PIN;TTY=MIN;TTY=BN;TTY=SCD;TTY=GPCK;TTY=BPCK)")

# Rung 2: ingredient term types only, for when the service gives up because the
# FORM it was asked for is unreachable while the ingredient was in scope.
INGREDIENT_VCL = f"({RXNORM})(TTY=IN;TTY=PIN;TTY=MIN)"

# Rung 3: SNOMED substances, for labels naming a drug class. Substances only —
# emphatically not procedures: a procedure concept in a column whose FHIRPath is
# medication[x] resolves correctly and makes the data mean something else.
SNOMED_ECL = "<<105590001"

# 0.80, not #25's 0.85. See THRESHOLD in the module docstring — the whole 0.80
# bucket was adjudicated and contains no wrong answer.
CONFIDENCE_THRESHOLD = 0.80

# No template. Tested here and rejected again; see TEMPLATE above.
TEMPLATE = "{}"

# SNOMED CT international core. A national extension resolves on the server it
# was authored against and nowhere else, which is invisible from reading a CSV.
INTERNATIONAL_CORE = "900000000000207008"

CURATED_HEADER = [
    "mimic_code", "mimic_display",
    "target_system", "target_code", "target_display", "comment",
    # Provenance: read by lib/stats.py and discarded by the build. Recorded on
    # every row INCLUDING the ones where the proposal was then rejected, so any
    # mapping and any non-mapping can be audited from the CSV alone. `query` is
    # this table's addition — with a normalisation layer in play, the string
    # that was actually sent is not recoverable from mimic_display by eye.
    "method", "join_rung", "query",
    "codesearch_target", "codesearch_display", "codesearch_confidence",
    "codesearch_status", "codesearch_reasoning",
]


# --------------------------------------------------------------------------- #
# Normalisation. QUERY-SIDE ONLY — see NORMALISATION in the module docstring.
# --------------------------------------------------------------------------- #

# N1. The non-formulary marker, wherever it sits. Whitespace tolerated inside
# the asterisks because the source is hand-typed pharmacy text.
_NF = re.compile(r"\*\s*NF\s*\*", re.IGNORECASE)

# N2. The redaction artefact. Three or more, so an ordinary underscore inside a
# product name is left alone.
_REDACTION = re.compile(r"_{3,}")

# N3. Container and compounding annotations, derived by enumerating every
# parenthetical and asterisk-delimited run in the 2,188 observed labels rather
# than by imagining what pharmacists write. Deliberately CONSERVATIVE: a
# parenthetical is semantic by default (#25), and this population really does
# carry `(Oral Solution)`, `(Extended Release)`, `(Immediate Release)`,
# `(Disintegrating Tablet)`, `(Suspension)`, `(Liquid)`, `(PF)`, `(Rectal)`,
# `(Human)`, `(Dilaudid)`, `(Envarsus XR)`, `(Lamictal Brand)`, `(Topamax)`,
# `(25g / 500mL)` and `(Peripheral or Central Line)` — none of which may be
# touched. Only a run whose content matches one of these is removed.
_CONTAINER_NOTE = re.compile(
    r"""(?xi)
    (?: mini[\s-]*bag (?:\s+plus)?            # (Mini Bag Plus), (Mini-bag Plus)
      | mini\s+bag\s+or\s+compound
      | vial[\s-]*mate (?:\s+adapt[eo]r)?     # (Vial-Mate Adaptor)
      | vial\s+to\s+be\s+attached[^)*]*       # (Vial to be attached to MB+ ...)
      | (?:rx|pharmacy)\s+compound(?:ed)?     # (Rx Compound), ***Rx Compound***
      | \d*\s*g?\s*vial\s+x\s*\#?\s*\d+       # (1g vial x #2)
      | choose\s+this\s+package[^)*]*
      | latex\s*free
      | do\s+not\s+edit
      | non[\s-]*standard
      )""")

# A run of either shape, whose CONTENT is then tested against _CONTAINER_NOTE.
# Asterisk runs are included because `***Rx Compound***` is written that way —
# but the test is the same, so `*GammaGARD Liquid*` and `*NF*`-adjacent brand
# markers are not caught by it.
_DELIMITED = re.compile(r"\(([^()]*)\)|\*+([^*]+)\*+")


def _drop_container_notes(text):
    """N3: remove a delimited run naming a container or compounding note."""
    def replace(match):
        content = match.group(1) if match.group(1) is not None else match.group(2)
        return " " if _CONTAINER_NOTE.fullmatch(content.strip()) else match.group(0)
    return _DELIMITED.sub(replace, text)


def normalise(display):
    """The string actually sent to the index and the service.

    Returns (query, [rule names applied]) so the CSV can record which rules
    touched a row and a reader can reproduce the query by hand.
    """
    applied = []
    text = display
    if _NF.search(text):
        text, applied = _NF.sub(" ", text), applied + ["N1-nf"]
    if _REDACTION.search(text):
        text, applied = _REDACTION.sub(" ", text), applied + ["N2-redaction"]
    dropped = _drop_container_notes(text)
    if dropped != text:
        text, applied = dropped, applied + ["N3-container"]
    return " ".join(text.split()).strip(" -,"), applied


def uninformative(code, query):
    """Does this row carry no label at all?

    Two shapes, one test: nothing survived normalisation, or the "display" is
    the formulary code repeated. See THE_UNINFORMATIVE_LABEL_RULE — this
    suppresses the SERVICE call only, and is applied after the term join.
    """
    key = r3(query)
    return not key or key == r3(code)


# --------------------------------------------------------------------------- #
# code-search, the gate, and the constraint URLs.
# --------------------------------------------------------------------------- #

def constraint_url(vcl=None):
    """A VCL expression as a resolvable implicit-ValueSet canonical."""
    return ("http://fhir.org/VCL?v1="
            + urllib.parse.quote(vcl or CONSTRAINT_VCL, safe=""))


def snomed_url(ecl=None):
    """A SNOMED ECL as its implicit-ValueSet canonical.

    NOT the VCL form. SNOMED CT has its own implicit ValueSet syntax and that is
    what the server and code-search resolve; a VCL wrapper round an ECL string
    404s.
    """
    return (f"{SNOMED}?fhir_vs=ecl/"
            + urllib.parse.quote(ecl or SNOMED_ECL, safe=""))


def rungs():
    """The rungs build_row tries, in order: (constraint URL, target system)."""
    return ((constraint_url(CONSTRAINT_VCL), RXNORM),
            (constraint_url(INGREDIENT_VCL), RXNORM),
            (snomed_url(), SNOMED))


def get(fhir_base, path, **params):
    """A GET returning the parsed body, or None. Non-200 is not an answer."""
    query = urllib.parse.urlencode(params)
    status, body = http("GET", f"{fhir_base.rstrip('/')}/{path}?{query}")
    return body if status == 200 and body else None


def find_code(service, text, url, system, timeout, attempts=4):
    """code-search's best match for `text`, constrained to `url`.

    Retries transport failures: a dropped connection is not an answer, and a run
    that quietly mixes 'no match' with 'the service was not running' produces a
    table that understates coverage and reads exactly like a real result.
    Exhausted retries raise, and main() refuses to write the CSV.

    A 4xx IS NOT RETRIED, and that distinction cost a full generation run. The
    service rejecting a request is a permanent answer about that request, not a
    transport fault — but urllib raises HTTPError, a SUBCLASS of URLError, so
    the transport clause below swallowed it and retried a guaranteed-identical
    failure four times before raising anyway. Re-raised immediately instead, so
    the traceback names the request that was malformed rather than the fourth
    attempt at it.
    """
    body = json.dumps({
        "text": TEMPLATE.format(text),
        "url": url,
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
        except urllib.error.HTTPError as exc:
            if 400 <= exc.code < 500:
                raise RuntimeError(
                    f"code-search rejected the request with HTTP {exc.code} "
                    f"({exc.reason}) for text={text!r}. That is a permanent "
                    f"answer about this request, not a transport fault, so it "
                    f"is not retried.") from exc
            last = exc
            if attempt < attempts - 1:
                time.sleep(2 ** attempt)
        except (urllib.error.URLError, ConnectionError, TimeoutError,
                HTTPException) as exc:
            last = exc
            if attempt < attempts - 1:
                time.sleep(2 ** attempt)
    raise RuntimeError(f"{attempts} attempt(s) failed: {last}")


def best(answer):
    """(code, display, confidence, reasoning) or None, from a find-code reply."""
    matches = (answer or {}).get("matches") or []
    if not matches:
        return None
    top = matches[0]
    return (top.get("code"), top.get("display", ""),
            float(top.get("confidence", 0.0)), top.get("reasoning", ""))


def in_constraint(fhir_base, code, url, system):
    """True if `code` is a member of `url`, per the server. Asserted, not assumed."""
    result = get(fhir_base, "ValueSet/$validate-code",
                 url=url, system=system, code=code)
    if result is None:
        return False
    return any(p.get("name") == "result" and p.get("valueBoolean")
               for p in result.get("parameter", []))


def snomed_gate(fhir_base, code):
    """(ok, preferred_display) for a SNOMED target: exists, active, core module.

    The module check is the one a reader of the CSV cannot make. An AU- or
    US-extension concept resolves on the server it was picked from and nowhere
    else.
    """
    result = get(fhir_base, "CodeSystem/$lookup", system=SNOMED, code=code)
    if result is None:
        return False, ""
    display, properties = "", {}
    for parameter in result.get("parameter", []):
        if parameter.get("name") == "display":
            display = parameter.get("valueString", "")
        elif parameter.get("name") == "property":
            part = {p["name"]: p for p in parameter.get("part", [])}
            name = part.get("code", {}).get("valueCode")
            value = part.get("value", {})
            properties[name] = (value.get("valueCode")
                                or value.get("valueString")
                                or value.get("valueBoolean"))
    if properties.get("inactive") is True:
        return False, display
    if str(properties.get("moduleId", "")) != INTERNATIONAL_CORE:
        return False, display
    return True, display


def rxnorm_display(fhir_base, code):
    """The server's preferred term, so verify-curated's display check passes."""
    result = get(fhir_base, "CodeSystem/$lookup", system=RXNORM, code=code)
    if result is None:
        return ""
    return next((p.get("valueString", "") for p in result.get("parameter", [])
                 if p.get("name") == "display"), "")


def assert_rxnorm_version(fhir_base):
    """Fail closed if the server is serving a different RxNorm release.

    The term index carries its release in its manifest; the SERVICE does not,
    so this asks the server directly before any answer is accepted. Mixing
    releases would change committed answers with no diff to explain them.
    """
    body = get(fhir_base, "CodeSystem/$lookup", system=RXNORM, code="161",
               property="version")
    served = ""
    for parameter in (body or {}).get("parameter", []):
        if parameter.get("name") == "version":
            served = parameter.get("valueString", "")
    if served and served != RXNORM_VERSION:
        sys.exit(f"  server is serving {RXNORM}|{served}, this table is built "
                 f"against |{RXNORM_VERSION}. Refusing to mix releases.")


# --------------------------------------------------------------------------- #
# Resolving one distinct query.
# --------------------------------------------------------------------------- #

def resolve(query, index, fhir_base, service, timeout):
    """Resolve ONE normalised label. Returns the target/provenance fields only.

    Keyed on the query rather than on a code, because a label shared by several
    formulary codes is asked once and the answer fanned across its members —
    see SHARED-DISPLAY FAN-OUT. Everything code-specific (the uninformative
    test, mimic_code, mimic_display) is applied by the caller.
    """
    out = {c: "" for c in CURATED_HEADER}

    for rung, key in query_rungs(query):
        if (rxcui := index.get(key)):
            out.update(method="term-join", join_rung=rung,
                       target_system=RXNORM, target_code=rxcui,
                       target_display=rxnorm_display(fhir_base, rxcui) or query,
                       codesearch_status="not-needed")
            return out

    # THE_UNINFORMATIVE_LABEL_RULE, empty-query half. This has to be HERE and
    # not only in the caller: resolve() is keyed on the query, so the 28 codes
    # whose display is `___` collapse into ONE group whose query is the empty
    # string, and the caller's per-code test does not run until after this
    # function has returned. Sending "" to code-search is an HTTP 400 — a
    # permanent rejection — which failed a whole generation run that had
    # already paid for 1,954 good answers.
    #
    # Tested on r3() rather than on the raw string so a query that is only
    # punctuation is caught by the same rule, for the same reason: neither
    # carries a label to search on. The per-CODE half of the rule (query equals
    # the formulary code) stays in the caller, where the code is in scope.
    if not r3(query):
        out.update(method="no-label", codesearch_status="no-label")
        return out

    out["method"] = "code-search"
    for url, system in rungs():
        answer = best(find_code(service, query, url, system, timeout))
        if answer is None:
            continue
        target, proposed, confidence, reasoning = answer
        out.update(codesearch_target=target, codesearch_display=proposed,
                   codesearch_confidence=f"{confidence:.2f}",
                   codesearch_reasoning=reasoning)
        if confidence < CONFIDENCE_THRESHOLD:
            out["codesearch_status"] = "below-threshold"
            continue
        if system == SNOMED:
            ok, preferred = snomed_gate(fhir_base, target)
            if not ok:
                out["codesearch_status"] = "gate-failed"
                continue
        else:
            if not in_constraint(fhir_base, target, url, system):
                out["codesearch_status"] = "out-of-constraint"
                continue
            preferred = rxnorm_display(fhir_base, target) or proposed
        out.update(codesearch_status="ok", target_system=system,
                   target_code=target, target_display=preferred)
        return out

    out["codesearch_status"] = out["codesearch_status"] or "no-match"
    return out


def declined_comment(row):
    """Why a blank target is a DECISION. A blank one with no reason is fatal in
    lib/curated.py, and rightly: a reader cannot audit silence."""
    if row["codesearch_status"] == "no-label":
        return ("source display carries no label — it is the formulary code "
                "repeated, or a redaction artefact — so no search was made. "
                "Searching a pharmacy mnemonic returns a confident answer to a "
                "string prefix rather than to a drug.")
    proposal = (f"{row['codesearch_target']} "
                f"'{row['codesearch_display']}' at "
                f"{row['codesearch_confidence']}")
    return {
        "no-match": (f"code-search returned no match within {CONSTRAINT_VCL}, "
                     f"its ingredient-only subset, or SNOMED CT "
                     f"{SNOMED_ECL}."),
        "below-threshold": (f"code-search proposed {proposal}, below the "
                            f"{CONFIDENCE_THRESHOLD} threshold."),
        "out-of-constraint": (f"code-search proposed {proposal} but that code "
                              f"is not a member of the search constraint."),
        "gate-failed": (f"code-search proposed {proposal} but that concept is "
                        f"inactive or outside the SNOMED CT international "
                        f"core module."),
    }.get(row["codesearch_status"], f"code-search: {row['codesearch_status']}.")


# --------------------------------------------------------------------------- #

def ig_codes():
    """The observed source codes for EVERY field that reads this table.

    `mimic-medication-formulary-drug-cd` is bound to one element today, so this
    is one field's population — but it is discovered rather than declared, so
    binding the CodeSystem to a second element extends the generation
    population with nothing to keep in step. See lib/builders.py for why a
    hand-kept list is the failure mode this avoids.
    """
    return table_population(OUT_CSV)


def read_committed():
    """The committed table as {code: row}, or {} if there is none yet."""
    if not OUT_CSV.is_file():
        return {}
    with open(OUT_CSV, newline="") as fh:
        return {row["mimic_code"]: row for row in csv.DictReader(fh)}


def assert_same_settings():
    """Refuse to append onto rows generated under different settings.

    The generation log records the constraint, template and threshold ONCE, at
    top level, and lib/stats.py reads them as the settings that produced every
    row. Appending to a table whose committed rows predate a settings change
    would make that a lie. Fail closed instead: a full regeneration is the
    correct response to moving a setting.
    """
    if not LOG_JSON.is_file():
        sys.exit(f"  --append needs {LOG_JSON.name} to check the committed "
                 f"rows were generated under today's settings, and it is "
                 f"missing. Run a full generation instead.")
    log = json.loads(LOG_JSON.read_text())
    current = {"constraint_vcl": CONSTRAINT_VCL,
               "ingredient_fallback_vcl": INGREDIENT_VCL,
               "snomed_fallback_ecl": SNOMED_ECL,
               "template": TEMPLATE,
               "confidence_threshold": CONFIDENCE_THRESHOLD,
               "rxnorm_version": RXNORM_VERSION}
    drifted = {k: (log.get(k), v) for k, v in current.items()
               if log.get(k) != v}
    if drifted:
        detail = "\n".join(f"      {k}: log {was!r} -> now {now!r}"
                           for k, (was, now) in sorted(drifted.items()))
        sys.exit(f"  --append refused: the committed rows were generated under "
                 f"different settings.\n{detail}\n"
                 f"    The log states one set of settings for the whole table, "
                 f"so appending would attribute today's to yesterday's rows. "
                 f"Regenerate the table in full.")


def report(rows):
    print(f"\n  {len(rows):,} row(s)", file=sys.stderr)
    for method, n in Counter(r["method"] for r in rows).most_common():
        print(f"    {method or '(none)':16s} {n:>6,}", file=sys.stderr)
    print("\n  normalisation applied", file=sys.stderr)
    for rule, n in Counter(r["normalisation"] for r in rows
                           if r.get("normalisation")).most_common():
        print(f"    {rule:16s} {n:>6,}", file=sys.stderr)
    print("\n  join rung", file=sys.stderr)
    for rung, n in Counter(r["join_rung"] for r in rows
                           if r["join_rung"]).most_common():
        print(f"    {rung:16s} {n:>6,}", file=sys.stderr)
    print("\n  code-search status", file=sys.stderr)
    for status, n in Counter(r["codesearch_status"] for r in rows
                             if r["codesearch_status"]).most_common():
        print(f"    {status:18s} {n:>6,}", file=sys.stderr)
    print("\n  target system", file=sys.stderr)
    for system, n in Counter(r["target_system"] for r in rows
                             if r["target_code"]).most_common():
        print(f"    {system:50s} {n:>6,}", file=sys.stderr)
    mapped = sum(1 for r in rows if r["target_code"])
    print(f"\n  {mapped:,}/{len(rows):,} mapped "
          f"({100 * mapped / len(rows):.1f}%)", file=sys.stderr)


def main():
    ap = argparse.ArgumentParser(
        description=__doc__.split("\n\n")[0],
        formatter_class=argparse.RawDescriptionHelpFormatter)
    add_common_args(ap)
    ap.add_argument("--code-search", default=DEFAULT_CODE_SEARCH
                    or "http://localhost:3000",
                    help="code-search base URL (default: $CODE_SEARCH_URL "
                         "or %(default)s)")
    ap.add_argument("--workers", type=int, default=8,
                    help="concurrent code-search calls (default: %(default)s)")
    ap.add_argument("--timeout", type=int, default=120)
    ap.add_argument("--only", help="comma-separated MIMIC codes, for probing. "
                                   "WITHOUT --append this REWRITES the table "
                                   "to just those rows")
    ap.add_argument("--append", action="store_true",
                    help="keep every committed row and ask the service only "
                         "for codes that have none. Refuses if the committed "
                         "log's settings differ from this script's")
    args = ap.parse_args()

    fhir_base = (args.fhir_base or "").rstrip("/")
    if not fhir_base:
        sys.exit("  no --fhir-base and $ONTOSERVER_URL unset.")
    configure_tls(args.ca_bundle, args.insecure)
    assert_rxnorm_version(fhir_base)

    # The index is the drug-name generator's file. Passing the constraint makes
    # "this reader searches what that index describes" an assertion rather than
    # a comment — see lib/termindex.load_index.
    index, manifest = load_index(CONSTRAINT_VCL)
    print(f"  term index: {len(index):,} keys, {manifest['system']}|"
          f"{manifest['version']}", file=sys.stderr)

    concepts = ig_codes()
    for field, element, count in describe_population(OUT_CSV):
        print(f"  {field:26s} {element:42s} {count:>6,} observed",
              file=sys.stderr)

    if args.only:
        wanted = {c.strip() for c in args.only.split(",")}
        concepts = {k: v for k, v in concepts.items() if k in wanted}
        if missing := wanted - set(concepts):
            sys.exit(f"  --only names code(s) not in the observed population: "
                     f"{sorted(missing)}")

    carried = {}
    if args.append:
        assert_same_settings()
        carried = read_committed()
        # Carried rows are kept verbatim, including the declined ones: a row
        # that says the service found nothing is an answer, and re-asking it
        # would spend the most expensive calls in the run re-deriving it.
        concepts = {k: v for k, v in concepts.items() if k not in carried}
        print(f"  --append: {len(carried):,} committed row(s) kept, "
              f"{len(concepts):,} to generate", file=sys.stderr)
        if not concepts:
            print("  nothing to do — every code already has a row.",
                  file=sys.stderr)
            return 0
    elif args.only:
        print(f"  WARNING: --only without --append rewrites {OUT_CSV.name} to "
              f"{len(concepts)} row(s). Add --append to keep the rest.",
              file=sys.stderr)

    # Normalise once, then group by the query actually sent. Every code sharing
    # a query shares its answer by construction — see SHARED-DISPLAY FAN-OUT.
    normalised = {code: normalise(display)
                  for code, display in concepts.items()}

    # THE_UNINFORMATIVE_LABEL_RULE is applied HERE, before grouping, so that it
    # really does mean "without calling the service" — applied after resolve()
    # it still paid for 89 answers and then threw them away, which is the cost
    # this rule exists to avoid, and it left the CSV unable to say the call was
    # never made.
    #
    # Still ordered AFTER the term join, which is the load-bearing part: a
    # query the index answers is settled deterministically no matter what the
    # code looks like, so KCENTRA, LITHOBID, PULMOZYME and VICODIN keep their
    # mappings. Only a query the index CANNOT answer is tested for being
    # labelless, and only then is the service skipped.
    joins = {query: any(key in index for _, key in query_rungs(query))
             for query, _ in normalised.values()}
    labelless = {code for code, (query, _) in normalised.items()
                 if not joins[query] and uninformative(code, query)}

    members = defaultdict(list)
    for code, (query, _) in normalised.items():
        if code not in labelless:
            members[query].append(code)

    # Broken down rather than printed as one number: most groups never reach
    # the service, and a bare "-> 1,955 queries" reads as 1,955 code-search
    # calls, which is what made the first run's failure so expensive to read.
    joinable = sum(1 for q in members if joins[q])
    print(f"  {len(concepts):,} code(s) -> {len(members):,} distinct query(s) "
          f"after normalisation and fan-out", file=sys.stderr)
    print(f"    {joinable:,} answered by the committed term index, "
          f"{len(members) - joinable:,} go to code-search; "
          f"{len(labelless):,} code(s) carry no label and are declined "
          f"without a call", file=sys.stderr)

    rows, failed = [], []
    with concurrent.futures.ThreadPoolExecutor(args.workers) as pool:
        futures = {pool.submit(resolve, query, index, fhir_base,
                               args.code_search, args.timeout): query
                   for query in members}
        answers = {}
        for done, future in enumerate(
                concurrent.futures.as_completed(futures), 1):
            query = futures[future]
            try:
                answers[query] = future.result()
            except Exception as exc:                             # noqa: BLE001
                failed.append((query, exc))
            print(f"    {done:,}/{len(futures):,}", end="\r", file=sys.stderr)

    if failed:
        # Refusing to write is the point: a table missing the rows whose calls
        # died is indistinguishable from one where the service said no.
        for query, exc in failed[:5]:
            print(f"    {query!r}: {exc}", file=sys.stderr)
        sys.exit(f"\n  {len(failed)} of {len(members)} call(s) failed. "
                 f"Refusing to write a table that would understate coverage.")

    for code, display in concepts.items():
        query, applied = normalised[code]
        # A labelless code never joined a group, so there is no answer to copy
        # and no call was made for it — see the rule above.
        row = ({c: "" for c in CURATED_HEADER} | {"method": "no-label",
                                                  "codesearch_status": "no-label"}
               if code in labelless else dict(answers[query]))
        row.update(mimic_code=code, mimic_display=display, query=query,
                   normalisation="+".join(applied))
        rows.append(row)

    for row in rows:
        if not row["target_code"]:
            row["comment"] = declined_comment(row)
    # Committed rows first so a generated row can never silently replace one;
    # `concepts` was already narrowed to the codes that had none.
    rows = list(carried.values()) + rows
    rows.sort(key=lambda r: r["mimic_code"])

    with open(OUT_CSV, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=CURATED_HEADER, restval="",
                                extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    report(rows)
    print(f"  wrote {OUT_CSV.name}", file=sys.stderr)

    LOG_JSON.parent.mkdir(parents=True, exist_ok=True)
    LOG_JSON.write_text(json.dumps({
        "elements": [element for _, element, _ in
                     describe_population(OUT_CSV)],
        "constraint_vcl": CONSTRAINT_VCL,
        "constraint_url": constraint_url(),
        "ingredient_fallback_vcl": INGREDIENT_VCL,
        "snomed_fallback_ecl": SNOMED_ECL,
        "template": TEMPLATE,
        "confidence_threshold": CONFIDENCE_THRESHOLD,
        "rxnorm_version": RXNORM_VERSION,
        "normalisation": {
            "N1-nf": "strip the *NF* non-formulary marker",
            "N2-redaction": "strip runs of three or more underscores",
            "N3-container": ("strip a delimited run naming a container or "
                             "compounding note"),
            "uninformative_rule": ("after the term join, a query that is empty "
                                   "or equal to the source code is declared "
                                   "unmapped without calling the service"),
        },
        "term_index": {k: manifest[k] for k in
                       ("codes", "terms", "keys", "ambiguous_keys_dropped",
                        "tsv_sha256")},
        "rows": rows,
    }, indent=1) + "\n")
    print(f"  wrote {LOG_JSON.name}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
