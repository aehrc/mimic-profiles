#!/usr/bin/env python3
"""Generate conceptmaps/medication-gsn-rxnorm.csv — MIMIC GSN codes -> RxNorm.

FDB **Generic Sequence Numbers**: 9,347 six-digit keys whose display is a drug
NAME, which makes this a `medication-name`-shaped stream rather than an
`medication-etc`-shaped one. It is the population behind
MedicationStatement.medication[x]'s `gsn` coding slice (9,178 codes) and
MedicationDispense.medication[x]'s ED pyxis rows (704), overlapping in 535 —
4,137,258 codings between them, and every one of the 9,347 enumerated codes is
observed somewhere. See issue #29 for the full probe evidence, and #28 for the
sibling `etc` slice on the same element.

    make medication-gsn-table ARGS=--insecure

THE DETERMINISTIC TIER CARRIES MOST OF THIS STREAM, which is why the shape below
is build_medication_name_table.py's and not build_medication_etc_table.py's.
Measured against the committed term index, with no network and no model:

    Q1-Q4 (the shared rungs)              4,266 codes   45.6%   46.3% of occ
    + B1-B4 (the generic before the [ )   +1,256        60.3%   63.4%
    + B5-B6 (the brand inside the [ )       +214        61.4%   64.1%
    residual, asked of code-search         3,611        38.6%   35.9%

THE BRACKET RUNGS ARE THE ONE THING THIS STREAM ADDS to the join. FDB writes a
drug two ways in one string — `lamotrigine [Lamictal]`, `hepatitis A and B
vaccine (PF) [Twinrix (PF)]` — and 2,137 of the 9,347 displays take that form,
none of which the shared rungs can key on because RxNorm has no term for the
whole string. lib/termindex.bracketed_rungs is opt-in and documents why it is
not folded into query_rungs: the bracket is GSN's grammar and nobody else's
(0 of 9,971 `medication-name` displays, 0 of 4,108 `formulary-drug`, 0 of 474
`medication-icu`), and `join_rung` exists so a reader can tell which loss a row
took.

Generic before brand, and that ORDER IS A DECISION: 874 displays reach both with
DIFFERENT RxCUIs (`warfarin [Jantoven]` -> 11289 warfarin vs 405155 Jantoven),
so one had to be preferred. The generic is what FDB puts first and what the
clinical record is about; the brand rung then recovers 214 rows the generic
cannot reach (`divalproex [Depakote]`, `ipratropium-albuterol [Combivent]`),
where RxNorm's ingredient term differs from FDB's compound spelling. Both are
recorded per row, so neither is mistaken for an exact-product mapping.

CONSTRAINT_VCL is #25's, character for character, and that is not laziness — it
is FORCED. lib/termindex.load_index refuses an index built under a different
constraint, because its keys would then describe concepts outside this
generator's search space, every one of them a target the gate would have
rejected arriving through the one tier that has no gate. Deviating here means
either refreshing the single shared index (changing what two committed tables
settle) or giving up the 61.4% above. It was probed on its own merits anyway,
and it holds:

    (rxnorm)(TTY=IN;TTY=PIN;TTY=MIN;TTY=BN;TTY=SCD;TTY=GPCK;TTY=BPCK)

73,214 codes. A bare `(system)` with no property clause is a VCL parse error, so
an RxNorm constraint always needs at least one filter.

THE CONSTRAINT CARRIES THE ACCURACY, AND CONFIDENCE DOES NOT. 15 adversarial
labels — MIMIC files devices, test strips, enteral formulas and bulk chemicals
in this same drug-name column — asked against the constraint above and against
all 22 RxNorm term types (209,927 codes). Constrained, every device, test supply
and nutrition product was declined, INCLUDING the deliberately drug-shaped ones.
Unconstrained, `Hi-Cal` — Abbott's high-calorie oral supplement — came back as
`1897 calcium carbonate` at **0.85**, a confident wrong answer sitting in the
same confidence band as that arm's correct ones, and no threshold separates it.
It is the `Foley Catheter` lesson repeating: the worst answer does not score
worst. The term-type filter is what declines `Truetrack Test`,
`Sure Comfort Pen Needle`, `Peptamen 1.5 Cal With Prebio1` and
`Spectravite Advanced Formula`; nothing else in the pipeline would.

TEMPLATE: none. The labels already ARE drug names, as in #25. Tested here rather
than inherited, 13 labels x 2 arms, and the null hypothesis lost on a THIRD
ground after the usual two. The wrapper did fix three invented-detail answers
(`Tylenol Extra Strength` -> acetaminophen, `Women's Stool Softener` ->
docusate, `TAB A VITE` -> an honest decline) and broke one (`Ventolin HFA` ->
`albuterol`, discarding a brand the label states outright). What decides it is
that on every row whose target code did NOT change, the wrapper compressed
confidence onto exactly the accept line — 0.90, 0.95 and 0.97 all became 0.85.
A template that moves the gate rather than the evidence removes the threshold's
whole margin, and the threshold is the only defence a table row has. It also
defeated the service's exact-term fast path on 11 of 13 calls (median 0.0s ->
6.2s), the same ~60x tax #25 measured.

THRESHOLD 0.85, not the repo default 0.80, and the argument is
occurrence-weighted. Exactly three probed rows land in [0.80, 0.85):

    Tylenol Extra Strength      80,619 occ   0.80   `220577 Tylenol Gelcap
                                                    Extra Strength` — invents a
                                                    dose form, and the service
                                                    says so itself in its
                                                    reasoning
    CeFAZolin 1g/50mL 50mL BAG   3,040 occ   0.80   correct
    heparin lock flush (porcine)   968 occ   0.80   a true generalisation

So 0.85 avoids 80,619 occurrences of invented detail — the single highest-volume
residual code in the stream — at the price of demoting 3,040 to whatever the
ingredient rung returns. 0.90 is not available: it destroys the exact-dose
matches that are this population's best answers (`FoLIC Acid 1mg TAB` 0.95,
`Hydrochlorothiazide 25mg TAB` 0.97, `TraZODone 50mg TAB` 0.98).

THE INGREDIENT FALLBACK, as in #25, and it earns its place here on its own
numbers: 3 of 9 probed misses converted, all 3 correct, 62,684 occurrences. Its
best row is `vancomycin in D5W` (20,780 occ), where the primary call proposed
`vancomycin 1.25 GM in 250 ML Injection` at 0.50 — a dose and a volume the label
never states — and the fallback returns the ingredient instead. The trigger is
"no accepted answer", NOMATCH **or** below threshold, for the reason #25 gives:
NOMATCH alone would silently fail to fire on exactly the rows where the primary
call invented detail and scored below the gate, which is this stream's dominant
failure mode rather than an edge case.

NO SNOMED RUNG, which makes this the repo's first SINGLE-TARGET RxNorm table.
#25 needs one because `Insulin` (122,879 occ) names a drug CLASS RxNorm does not
model. GSN has no such gap — its displays are specific drug names — and the
probes bear that out: over 6 still-unresolved labels the substance rung
converted ONE (`omega-3 fatty acids-vitamin E [Fish Oil]`, 4,663 occ, and lossy
at that), while for `TAB A VITE` it returned `363648006 |Tabun|`, the nerve
agent, at 0.50. Gated out by the threshold, but on 9,347 rows the substance
hierarchy is a hazard for garbled FDB labels and it was buying almost nothing.
Dropping it also lets the header say `rxnorm_code` and mean it.

Consequence worth stating: a label naming a drug class in this population is
declared unmapped rather than reaching for SNOMED. That is the intended failure
direction — an omission, not a commission.

THE GATE, RxNorm only now:
  membership of CONSTRAINT_VCL (or the ingredient subset the answer came from),
  asserted with $validate-code against the VCL URL rather than assumed from
  having asked politely — 17 of 17 returned codes were members when probed, so
  no leak was found here, but a sibling stream's SNOMED rung did leak and the
  check costs one call;
  the target display is then replaced with the server's preferred term, so
  verify-curated's display check passes by construction.

`No response from agentic evaluator` IS RECORDED, NOT RAISED, and it is NOT a
decline. code-search answers `{"matches": [], "reasoning": "No response from
agentic evaluator"}` when its evaluator fails. At the wire that is
indistinguishable from a legitimate NO MATCH, so committing it as one would
publish a service fault as "no RxNorm concept exists" — but raising is the wrong
correction, because one bad label then discards a whole run's worth of good
answers. This file follows build_medication_etc_table.py, which established the
classification on 1,201 rows: the service distinguishes the two states itself,
saying `Agentic eval matched 0 candidate(s) after N tool call(s)` when it looked
and found nothing, and this bare string when it did not complete.

So the row carries `codesearch_status: agentic-no-result`, a blank target and a
comment saying the search did not finish — NOT a claim that nothing exists — and
`--append` drops exactly those rows from the carry-over so they are re-asked.
That recovery needs the service's cache cleared first: the outcome is cached in
an in-memory LRU checked before a SQLite table, so retrying in-process returns
the identical empty body, which is why find_code does not retry it. See
CODE-SEARCH-BUG-REPORT.md at the repo root.

The classification is a SUBSTRING MATCH ON AN UNDOCUMENTED MESSAGE — the response
carries no machine-readable outcome — so if the authors reword it these rows
silently become plain `no-match` and start being published as genuine declines.
The distinct status is what makes that drift visible in a diff.

TWO RUNGS MAKE ONE ADDITION TO THAT RULE. The etc stream has a single rung; here
a label that stalls on the primary constraint is still asked of the ingredient
one, because a different constraint URL is a different cache key and may well
answer. But if ANY rung stalled and the row still has no target, the row is
marked `agentic-no-result` even when a later rung proposed something that was
then rejected: the search did not complete, which is the condition a retry is
for. Whatever was proposed stays in the `codesearch_*` columns either way.

NOT PART OF `make mappings`: it needs the network and a model-backed service,
and it WRITES a build input. Determinism lives in the split — this runs by hand,
its output is committed, and the build reads the committed CSV and never a
server.

THE TABLE IS SHARED BETWEEN TWO BOUND ELEMENTS, so its population is the union
of what both observe (lib/builders.table_population), not either field's. A
table per field over those sets is a way to publish two different RxNorm
concepts for one MIMIC drug name, in two ConceptMaps, with nothing in the repo
to notice. `--append` is what makes that cheap: committed rows are kept
verbatim, including the declined ones — which are answers, and the most
expensive calls in a run — and only codes with no row are asked. It refuses when
the committed log's settings differ from this script's constants.

Usage:
  uv run .../build_medication_gsn_table.py --insecure
  uv run .../build_medication_gsn_table.py --append --insecure
  uv run .../build_medication_gsn_table.py --only 004490,006373 --insecure
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
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common import fhirclient                                     # noqa: E402
from common.cli import add_common_args, DEFAULT_CODE_SEARCH       # noqa: E402
from common.fhirclient import configure_tls, http                 # noqa: E402
from common import paths                                          # noqa: E402
from conceptmaps.lib.builders import (describe_population,        # noqa: E402
                                      table_population)
from conceptmaps.lib.canonical import RXNORM, TABLE_DIR           # noqa: E402
# The keying and the reader live in lib/ because the index is a COMMITTED file
# three generators now join against; see lib/termindex.py. bracketed_rungs is
# this stream's addition and is opt-in there for the reason stated in its
# docstring.
from conceptmaps.lib.termindex import (bracketed_rungs, load_index,  # noqa: E402
                                       query_rungs)

OUT_CSV = TABLE_DIR / "medication-gsn-rxnorm.csv"
LOG_JSON = paths.OUTPUT / "medication-gsn-generation-log.json"

# The RxNorm release the index and the table were built from. Asserted on every
# run against what the server echoes back: a silent release bump would change
# committed answers with no diff to explain them. NOT pinned into the map —
# see lib/canonical.py UNVERSIONED_SYSTEMS for why those are different claims.
RXNORM_VERSION = "20231106"

# Character-identical to build_medication_name_table.CONSTRAINT_VCL, which is
# what lets this generator join against the committed term index. load_index
# asserts the two agree and exits rather than joining across search spaces.
CONSTRAINT_VCL = (f"({RXNORM})"
                  "(TTY=IN;TTY=PIN;TTY=MIN;TTY=BN;TTY=SCD;TTY=GPCK;TTY=BPCK)")

# Rung 2: ingredient term types only. See THE INGREDIENT FALLBACK above.
INGREDIENT_VCL = f"({RXNORM})(TTY=IN;TTY=PIN;TTY=MIN)"

CONFIDENCE_THRESHOLD = 0.85

# No template. The label is sent bare; see TEMPLATE above.
TEMPLATE = "{}"

# What code-search says when its agentic loop did not complete. Not a no-match,
# and cached — see the docstring. Same constant, same spelling and same
# classification as build_medication_etc_table.py: two generators disagreeing
# about which outcomes are answers would publish two different kinds of table.
AGENTIC_NO_RESULT = "No response from agentic evaluator"

CURATED_HEADER = [
    "mimic_code", "mimic_display",
    # Single-target: every mapping in this table is RxNorm, so the header says
    # so rather than carrying a per-row target_system. See lib/curated.py.
    "rxnorm_code", "rxnorm_display", "comment",
    # Provenance: read by lib/stats.py and discarded by the build. Recorded on
    # every row INCLUDING the ones where the proposal was then rejected, so any
    # mapping and any non-mapping can be audited from the CSV alone.
    "method", "join_rung",
    "codesearch_target", "codesearch_display", "codesearch_confidence",
    "codesearch_status", "codesearch_reasoning",
]


# --------------------------------------------------------------------------- #
# Tier 1: the term index.
# --------------------------------------------------------------------------- #

def join_rungs(display):
    """Every deterministic rung for a GSN display, in the order tried.

    The shared rungs first, then GSN's bracket grammar. A hit on any of them is
    unique by construction: refresh_index deletes every key reaching more than
    one RxCUI, so ordering decides only which LOSS a row takes, never which of
    two candidate concepts wins a tie.
    """
    return list(query_rungs(display)) + list(bracketed_rungs(display))


def constraint_url(vcl=None):
    """A VCL expression as a resolvable implicit-ValueSet canonical."""
    return ("http://fhir.org/VCL?v1="
            + urllib.parse.quote(vcl or CONSTRAINT_VCL, safe=""))


# The rungs build_row tries, in order: (constraint URL, the VCL it encodes).
# Each is a resolvable canonical, so code-search and $validate-code are asked
# about exactly the same search space.
def rungs():
    return ((constraint_url(CONSTRAINT_VCL), CONSTRAINT_VCL),
            (constraint_url(INGREDIENT_VCL), INGREDIENT_VCL))


def get(fhir_base, path, **params):
    """A GET returning the parsed body, or None. Non-200 is not an answer."""
    query = urllib.parse.urlencode(params)
    status, body = http("GET", f"{fhir_base.rstrip('/')}/{path}?{query}")
    return body if status == 200 and body else None


def assert_version(fhir_base):
    """Fail closed if the server serves a different RxNorm release than the
    index and this table were built against."""
    result = get(fhir_base, "CodeSystem/$lookup", system=RXNORM, code="161")
    if result is None:
        sys.exit(f"  {fhir_base} did not answer a $lookup for RxNorm 161 "
                 f"(acetaminophen). Refusing to generate against a server "
                 f"whose release cannot be established.")
    version = next((p.get("valueString", "")
                    for p in result.get("parameter", [])
                    if p.get("name") == "version"), "")
    if version != RXNORM_VERSION:
        sys.exit(f"  server is serving {RXNORM}|{version}, this table is built "
                 f"against |{RXNORM_VERSION}. Refusing to mix releases: the "
                 f"committed term index is keyed to that release, so a table "
                 f"generated now would join yesterday's keys onto today's "
                 f"concepts. Re-pin RXNORM_VERSION and --refresh-index "
                 f"deliberately (in build_medication_name_table.py, which owns "
                 f"the index), and review the resulting diff.")


# --------------------------------------------------------------------------- #
# Tier 2: code-search.
# --------------------------------------------------------------------------- #

def find_code(service, text, url, timeout, attempts=4):
    """code-search's best match for `text`, constrained to `url`.

    Retries transport failures for the reason build_d_items_table.py gives: a
    dropped connection is not an answer, and a run that quietly mixes 'no match'
    with 'the service was not running' produces a table that understates
    coverage and reads exactly like a real result. Exhausted retries raise, and
    main() refuses to write the CSV.

    A non-converging agentic loop is NOT in that class and is returned as an
    ordinary answer — build_row classifies it. Retrying it in-process would be
    pointless anyway: the service caches the outcome and hands the identical
    body back.
    """
    body = json.dumps({
        "text": TEMPLATE.format(text),
        "url": url,
        "system": RXNORM,
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


def agentic_no_result(answer):
    """Did code-search fail on this label rather than decline it?

    An empty `matches` carrying AGENTIC_NO_RESULT and nothing else. A genuine
    decline instead reports `Agentic eval matched 0 candidate(s) after N tool
    call(s)`, which names the outcome and the work done — two cleanly separated
    populations over the 1,201 rows build_medication_etc_table.py measured, so
    the message is not a badly-worded no-match. The row is marked for retry
    rather than published as "no RxNorm concept exists".
    """
    if (answer or {}).get("matches"):
        return False
    return AGENTIC_NO_RESULT in ((answer or {}).get("reasoning") or "")


def best(answer):
    """(code, display, confidence, reasoning) or None, from a find-code reply."""
    matches = (answer or {}).get("matches") or []
    if not matches:
        return None
    top = matches[0]
    return (top.get("code"), top.get("display", ""),
            float(top.get("confidence", 0.0)), top.get("reasoning", ""))


# --------------------------------------------------------------------------- #
# The gate.
# --------------------------------------------------------------------------- #

def in_constraint(fhir_base, code, url):
    """True if `code` is a member of the value set `url` names, per the server.

    Asserted rather than assumed. The service is asked to confine itself to a
    constraint; on a sibling stream it did not, and a target that arrived
    outside the requested space would open a ConceptMap group into a search
    space this stream never agreed to map into.
    """
    result = get(fhir_base, "ValueSet/$validate-code",
                 url=url, system=RXNORM, code=code)
    if result is None:
        return False
    return any(p.get("name") == "result" and p.get("valueBoolean")
               for p in result.get("parameter", []))


def rxnorm_display(fhir_base, code):
    """The server's preferred term, so verify-curated's display check passes."""
    result = get(fhir_base, "CodeSystem/$lookup", system=RXNORM, code=code)
    if result is None:
        return ""
    return next((p.get("valueString", "") for p in result.get("parameter", [])
                 if p.get("name") == "display"), "")


# --------------------------------------------------------------------------- #
# Resolving one row.
# --------------------------------------------------------------------------- #

def build_row(code, display, index, fhir_base, service, timeout):
    """One CSV row: the deterministic tier first, then the service."""
    row = {c: "" for c in CURATED_HEADER}
    row["mimic_code"], row["mimic_display"] = code, display

    for rung, key in join_rungs(display):
        if (rxcui := index.get(key)):
            row.update(method="term-join", join_rung=rung,
                       rxnorm_code=rxcui,
                       rxnorm_display=rxnorm_display(fhir_base, rxcui)
                                      or display,
                       codesearch_status="not-needed")
            return row

    row["method"] = "code-search"
    stalled = False
    for url, vcl in rungs():
        reply = find_code(service, display, url, timeout)
        if agentic_no_result(reply):
            # The service failed on this rung rather than declining. Try the
            # next one anyway — a different constraint URL is a different cache
            # key — but remember that this row's search never completed.
            stalled = True
            continue
        answer = best(reply)
        if answer is None:
            # Deliberately does NOT set the status. A NOMATCH on the ingredient
            # rung must not overwrite a `below-threshold` recorded on the
            # primary one, or `comment` would say the service found nothing
            # while codesearch_target still holds the proposal it found — the
            # row would contradict itself. The fallback at the end of this
            # function supplies `no-match` only when no rung proposed anything.
            continue
        target, proposed, confidence, reasoning = answer
        row.update(codesearch_target=target, codesearch_display=proposed,
                   codesearch_confidence=f"{confidence:.2f}",
                   codesearch_reasoning=reasoning)
        if confidence < CONFIDENCE_THRESHOLD:
            row["codesearch_status"] = "below-threshold"
            continue
        if not in_constraint(fhir_base, target, url):
            row["codesearch_status"] = "out-of-constraint"
            continue
        row.update(codesearch_status="ok", rxnorm_code=target,
                   rxnorm_display=rxnorm_display(fhir_base, target) or proposed)
        return row

    # A stalled rung wins over whatever a later one proposed and had rejected:
    # the search did not complete, which is the condition --append retries for.
    # The proposal itself stays in the codesearch_* columns regardless.
    if stalled:
        row["codesearch_status"] = "agentic-no-result"
    row["codesearch_status"] = row["codesearch_status"] or "no-match"
    return row


def declined_comment(row):
    """Why a blank target is a DECISION. A blank one with no reason is fatal
    in lib/curated.py, and rightly: a reader cannot audit silence."""
    proposal = (f"{row['codesearch_target']} "
                f"'{row['codesearch_display']}' at "
                f"{row['codesearch_confidence']}")
    return {
        "no-match": (f"code-search returned no match within {CONSTRAINT_VCL} "
                     f"or its ingredient-only subset."),
        "agentic-no-result": (
            f"NOT A DECLINE — code-search failed on this label, answering "
            f"'{AGENTIC_NO_RESULT}'. Its search did not complete, so no "
            f"concept was rejected and this must not be read as 'no RxNorm "
            f"concept exists within {CONSTRAINT_VCL}'; a genuine no-match "
            f"instead reports 'Agentic eval matched 0 candidate(s) after N "
            f"tool call(s)'. Any proposal in the codesearch_* columns came "
            f"from a rung that did answer and was rejected on its own terms. "
            f"The outcome is cached by the service in memory and on disk, so "
            f"re-asking needs both tiers cleared first; `--append` then "
            f"re-asks this row. See CODE-SEARCH-BUG-REPORT.md."),
        "below-threshold": (f"code-search proposed {proposal}, below the "
                            f"{CONFIDENCE_THRESHOLD} threshold."),
        "out-of-constraint": (f"code-search proposed {proposal} but that code "
                              f"is not a member of the search constraint."),
    }.get(row["codesearch_status"], f"code-search: {row['codesearch_status']}.")


# --------------------------------------------------------------------------- #

def ig_codes():
    """The observed source codes for EVERY field that reads this table.

    Not one element's population. `mimic-medication-gsn` is bound on
    MedicationStatement.medication[x]'s `gsn` coding slice and, through the
    merged facade, on MedicationDispense.medication[x] — which observe
    overlapping-but-different subsets of it. One table over the union is what
    stops this repo publishing two different RxNorm concepts for one GSN code.
    lib/builders.py discovers which fields those are rather than taking a list.
    """
    return table_population(OUT_CSV)


def read_committed():
    """The committed table as {code: row}, or {} if there is none yet."""
    if not OUT_CSV.is_file():
        return {}
    with open(OUT_CSV, newline="") as fh:
        return {row["mimic_code"]: row for row in csv.DictReader(fh)}


def settings():
    """The settings the log states for the whole table, in one place.

    Read back by assert_same_settings and written into the log, so the two
    cannot describe different things.
    """
    return {"constraint_vcl": CONSTRAINT_VCL,
            "ingredient_fallback_vcl": INGREDIENT_VCL,
            "template": TEMPLATE,
            "confidence_threshold": CONFIDENCE_THRESHOLD,
            "rxnorm_version": RXNORM_VERSION}


def assert_same_settings():
    """Refuse to append onto rows generated under different settings.

    The generation log records constraint, template and threshold ONCE, at top
    level, and lib/stats.py reads them as the settings that produced every row.
    Appending to a table whose committed rows predate a settings change would
    make that a lie — the log would describe the new rows and be quoted for all
    of them. Fail closed instead: a full regeneration is the correct response to
    moving a setting.
    """
    if not LOG_JSON.is_file():
        sys.exit(f"  --append needs {LOG_JSON.name} to check the committed "
                 f"rows were generated under today's settings, and it is "
                 f"missing. Run a full generation instead.")
    log = json.loads(LOG_JSON.read_text())
    drifted = {k: (log.get(k), v) for k, v in settings().items()
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
        print(f"    {method or '(none)':14s} {n:>6,}", file=sys.stderr)
    print("\n  join rung", file=sys.stderr)
    for rung, n in Counter(r["join_rung"] for r in rows
                           if r["join_rung"]).most_common():
        print(f"    {rung:24s} {n:>6,}", file=sys.stderr)
    print("\n  code-search status", file=sys.stderr)
    for status, n in Counter(r["codesearch_status"] for r in rows
                             if r["codesearch_status"]).most_common():
        print(f"    {status:18s} {n:>6,}", file=sys.stderr)
    # The full spread, so the threshold can be moved with evidence rather than
    # by taste — and so the near-misses are visible without opening the CSV.
    print("\n  confidence (code-search rows only)", file=sys.stderr)
    for value, n in sorted(Counter(r["codesearch_confidence"] for r in rows
                                   if r["codesearch_confidence"]).items()):
        mark = "  <- below threshold" if float(value) < CONFIDENCE_THRESHOLD \
            else ""
        print(f"    {value:>5s} {n:>6,}{mark}", file=sys.stderr)
    mapped = sum(1 for r in rows if r["rxnorm_code"])
    print(f"\n  {mapped:,}/{len(rows):,} mapped "
          f"({100 * mapped / len(rows):.1f}%)", file=sys.stderr)
    # Said out loud, because these rows are the ones a reader would otherwise
    # mistake for declines — and because a count identical to the previous
    # run's means the service replayed its cache rather than being asked.
    if (stalled := sum(1 for r in rows
                       if r["codesearch_status"] == "agentic-no-result")):
        print(f"  {stalled:,} row(s) where code-search FAILED rather than "
              f"declined — not counted as answers. Clear the service's caches "
              f"and re-run with --append to retry exactly those.",
              file=sys.stderr)


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
    assert_version(fhir_base)

    index, manifest = load_index(CONSTRAINT_VCL)
    print(f"  term index: {len(index):,} keys, {manifest['system']}|"
          f"{manifest['version']}", file=sys.stderr)

    concepts = ig_codes()
    for element, count in describe_population(OUT_CSV):
        print(f"  {element:42s} {count:>6,} observed", file=sys.stderr)
    print(f"  {len(concepts):,} distinct source code(s) across "
          f"{len(describe_population(OUT_CSV))} element(s)", file=sys.stderr)

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
        #
        # EXCEPT the rows where the service FAILED. Those carry no answer at
        # all, so keeping them verbatim would make --append the thing that
        # cements a service fault into the committed table. They are dropped
        # from the carry-over and re-asked. This only helps once the service's
        # caches have been cleared of them — otherwise the identical empty body
        # comes straight back; see the docstring.
        retry = {code for code, row in carried.items()
                 if row.get("codesearch_status") == "agentic-no-result"}
        for code in retry:
            del carried[code]
        concepts = {k: v for k, v in concepts.items() if k not in carried}
        print(f"  --append: {len(carried):,} committed row(s) kept, "
              f"{len(concepts):,} to generate"
              + (f" (including {len(retry):,} retried after a service failure)"
                 if retry else ""), file=sys.stderr)
        if not concepts:
            print("  nothing to do — every code already has a row.",
                  file=sys.stderr)
            return 0
    elif args.only:
        print(f"  WARNING: --only without --append rewrites {OUT_CSV.name} to "
              f"{len(concepts)} row(s). Add --append to keep the rest.",
              file=sys.stderr)

    # How much of this run the network is even needed for. Printed before the
    # calls start because the join is the reason this stream is affordable.
    joined = sum(1 for display in concepts.values()
                 if any(key in index for _, key in join_rungs(display)))
    print(f"  {joined:,} of {len(concepts):,} settle on the term index; "
          f"{len(concepts) - joined:,} go to code-search", file=sys.stderr)

    rows, failed = [], []
    with concurrent.futures.ThreadPoolExecutor(args.workers) as pool:
        futures = {pool.submit(build_row, code, display, index, fhir_base,
                               args.code_search, args.timeout): code
                   for code, display in concepts.items()}
        for done, future in enumerate(
                concurrent.futures.as_completed(futures), 1):
            try:
                rows.append(future.result())
            except Exception as exc:                             # noqa: BLE001
                failed.append((futures[future], exc))
            print(f"    {done:,}/{len(futures):,}", end="\r", file=sys.stderr)

    if failed:
        # Refusing to write is the point: a table missing the rows whose calls
        # died is indistinguishable from one where the service said no. An
        # evaluator failure lands here too, which is why it is raised rather
        # than recorded as a decline.
        for code, exc in failed[:5]:
            print(f"    {code}: {exc}", file=sys.stderr)
        sys.exit(f"\n  {len(failed)} of {len(concepts)} call(s) failed. "
                 f"Refusing to write a table that would understate coverage.")

    for row in rows:
        if not row["rxnorm_code"]:
            row["comment"] = declined_comment(row)
    # Committed rows first so a generated row can never silently replace one;
    # `concepts` was already narrowed to the codes that had none.
    rows = list(carried.values()) + rows
    rows.sort(key=lambda r: r["mimic_code"])

    with open(OUT_CSV, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=CURATED_HEADER, restval="")
        writer.writeheader()
        writer.writerows(rows)
    report(rows)
    print(f"  wrote {OUT_CSV.name}", file=sys.stderr)

    LOG_JSON.parent.mkdir(parents=True, exist_ok=True)
    LOG_JSON.write_text(json.dumps({
        "elements": [element for element, _ in describe_population(OUT_CSV)],
        **settings(),
        "constraint_url": constraint_url(),
        "term_index": {k: manifest[k] for k in
                       ("codes", "terms", "keys", "ambiguous_keys_dropped",
                        "tsv_sha256")},
        "rows": rows,
    }, indent=1) + "\n")
    print(f"  wrote {LOG_JSON.name}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
