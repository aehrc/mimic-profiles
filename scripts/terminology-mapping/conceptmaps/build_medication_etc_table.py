#!/usr/bin/env python3
"""Generate conceptmaps/medication-etc-snomed.csv — FDB therapeutic classes -> SNOMED CT.

The first stream whose source codes name a drug CLASS and nothing else. FDB's
Enhanced Therapeutic Classification assigns every drug a category —
`ACE Inhibitors`, `Calcium Channel Blockers - Dihydropyridines`,
`Diuretic - Loop` — and MIMIC-ED's medrecon table carries the class code
alongside the drug's own gsn and ndc codes, sliced onto
MedicationStatement.medication[x]. 1,201 codes, all 1,201 observed, 2,975,614
codings. See issue #28 for the probe evidence behind every setting below.

    make medication-etc-table ARGS=--insecure

Note the element carries MORE ETC codings than resources (2,975,614 against
2,586,657): FDB assigns a drug to more than one class, so the `etc` slice is
genuinely 1..* and a per-resource count is not a per-coding count here.

WHY SNOMED CT, AND WHY NOTHING ELSE WAS AVAILABLE. RxNorm publishes no
therapeutic-class concepts at any term type — classes live in RxClass, which is
sourced from ATC and MeSH and is not an RxNorm code set — so an RxNorm rung has
nothing to answer with and this is the one medication stream in the repo with no
RxNorm target at all. ATC would be the natural target and is not on the server:
velonto hosts 123 distinct CodeSystems and ATC is not among them (no
`http://www.whocc.no/atc`, no MED-RT, no NDF-RT). SNOMED CT is the only class
vocabulary available, which makes this a single-target table.

CONSTRAINT `<<105590001 |Substance|`. Probed both ways, and the semantic
instinct loses to the evidence. `medication[x]` argues for the product
hierarchy — a Substance is not a medication, and this repo refuses that kind of
category substitution everywhere else — but `<<763158003 |Medicinal product|`
does not contain the vocabulary these labels use. Measured on velonto:

    ECL                   $expand   filter=diuretic   filter=dihydropyridine
    <<105590001            29,670          8                  1
    <<763158003            58,095          0                  0

The 8 are exactly FDB's own carve-up — `372695000 Diuretic`,
`372691009 Loop diuretic`, `372747003 Thiazide diuretic`,
`372753003 Potassium-sparing diuretic`, `372792005 Osmotic diuretic`,
`43585000 Sulfonamide diuretic`, `373751005 Mercurial diuretic`,
`419151007 Purine derivative diuretic` — all active, all international core.
MIMIC's `Diuretic - *` family is 10 codes / 85,487 occurrences and
`Calcium Channel Blockers - *` 4 codes / 53,328, so a product-only constraint
cannot reach 4.66% of this element's data for a structural reason no threshold
or template repairs.

The cost is real and is one measured row of twelve:
`Thyroid Hormones - Synthetic T4 (Thyroxine)` (40,276 occ.) reaches
`777760008 Thyroxine only product` under the product hierarchy and collapses to
`126202002 Levothyroxine sodium` here — a specific salt the label never
asserted. Recovering it would cost a second rung on every miss; declined for
now, and recorded in #28 as an open decision rather than discovered later.

Two dead ends, recorded so nobody re-walks them.
`<<763158003 MINUS <<781405001` — meant to strip the dose-form and clinical-drug
levels — is a NO-OP: `781405001` is |Medicinal product package|, a disjoint
sibling branch, and the expansion is 58,095 either way. The working form is
`<<763158003 MINUS (<<763158003: 411116001 = *)` (10,569 concepts), which does
preserve the class groupers and still produces no diuretic and no
dihydropyridine.

THE CONSTRAINT IS WHAT CARRIES THE ACCURACY, and here that is not a stylistic
preference — 57 of the 1,201 labels are not medications at all (98,183
occurrences, 3.30%): the `Medical Supplies and DME`, `Medical Supply`,
`Wound Care`, `Bulk Chemicals` and `Chemicals -` families, which MIMIC files in
the same column. Every one has a confident, correct-as-English, unusable-as-
`medication[x]` answer waiting in SNOMED. Nine of them, four search spaces,
bare text, top match only:

    label                                    unconstrained        <<105590001
    ... - Urinary Catheters and Related Dev.  20568009 @0.85       -
    ... - Crutches, Walkers, and related dev. 224899006 @0.85      -
    Wound Care - Dressings                    333453004 @0.85      -
    ... - Glucose Monitoring Test Supplies    337388004 @0.85      -
    ... - Blood Glucose Tests                 337388004 @0.80      -
    ... - Miscellaneous Other                 425399007 @0.60      -
    Bulk Chemicals                            -                    441900009 @0.70
    Chemicals - Solvents                      311835000 @0.90      311835000 @0.85
    Medical Supply, FDB Superset              -                    -

Correctly declined: unconstrained 2/9, `<<105590001` 7/9 raw and **8/9 once the
threshold applies** (`Bulk Chemicals` falls at 0.70), `<<763158003` 8/9, the
union 7/9.

Two things that establishes beyond the choice of hierarchy. **Confidence does
not separate good answers from bad ones** — the highest-scoring answer in the
whole adversarial run is a wrong one, `311835000 |Organic chemical solvent|` at
0.90 unconstrained, and every device answer sits at 0.85, the same value the
correct class answers sit at. And **the active/core-module gate catches none of
them**: `311835000`, `441900009`, `337388004`, `333453004`, `224899006`,
`20568009` and `425399007` are all active and all module 900000000000207008.
The gate is still required — velonto serves only the AU edition
(`32506021000036107`), so extension leakage is structural rather than
hypothetical — but the search space is what protects this stream.

> KNOWN ACCEPTED DEFECT: `00001123 Chemicals - Solvents` maps to
> `311835000 |Organic chemical solvent|` at 0.85, a laboratory reagent in a
> column whose FHIRPath is `medication[x]`. 17 occurrences. Left in place
> because the only fix available is a hand-written per-row rejection, which is
> the judgement the generated-table contract exists to remove — the same
> standing as `227719 AVA` in build_d_items_table.py. A consumer should drop it.

TEMPLATE: none, the label sent bare. Tested against the null hypothesis over 8
labels x 2 constraints x 2 variants. `Therapeutic drug class recorded on a
medication reconciliation record: {label}` changed nothing on 5 of 15 measured
pairs, changed only the confidence on 7, and changed the ANSWER on 3 — all three
harmfully. The decisive one: `Otic (Ear) - Glucocorticoids` goes from an honest
NO MATCH to `419933005 |Glucocorticoid|` at 0.85, because the sentence tells the
service the string is a class and it discards the route the record actually
stated, asserting a systemic steroid where the source said ear drops.

It also moves confidence in BOTH directions across the accept gate on rows whose
target code never changes — `Calcium Channel Blockers - Dihydropyridines`
0.95 -> 0.85, `Antiseptic - Quaternary Ammonium` 0.70 -> 0.85 — so the wrapper
moves the gate rather than the evidence, which is worse than the uniform
inflation build_medication_name_table.py rejected it for. Same conclusion as
that stream and for a compatible reason: these labels already ARE class names,
so there is nothing for a template to supply.

THRESHOLD 0.80, the repo default, and deliberately NOT the 0.85 that
build_medication_name_table.py deviated to. Measured over 40 probes the
confidence distribution is coarse and quantised:

    0.60 x1 - 0.70 x5 - 0.75 x2 - 0.85 x20 - 0.92 x1 - 0.95 x3 - 0.97 x1 - 0.98 x1

**The interval [0.80, 0.85) is empty — not one probe of 40 landed in it** — so
0.80 and 0.85 admit and reject exactly the same rows here and there is no row to
name where they differ. A deviation a reader has to be told the reason for
should buy something measurable. The live boundaries are 0.75 -> 0.80, which
rejects two lossy generalisations and is correctly strict, and 0.85 -> 0.90,
which would destroy every correct class answer measured.

THE GATE, applied as a filter rather than an assertion: exists, is active, is in
the SNOMED international core module rather than a national extension, and —
the addition this stream makes — **is genuinely a member of the constraint**,
asserted with `$validate-code` against the ECL's implicit ValueSet URL rather
than assumed from having asked politely.

That last one is not defensive tidiness; it was measured twice. `Multivitamins`
returned `412250002 |Multivitamin agent|` — a Substance — under BOTH product
constraints at 0.80 and 0.85, and `Wound Care - Dressings` returned
`225358003 |Wound care|`, a procedure, under `<<763158003` at 0.70. Both are
outside the value set that was requested. The service does not reliably confine
itself to the constraint, so the constraint has to be enforced on the way back
as well as asked for on the way out. build_lab_fluid_table.py already does this
after #24's `inVS` leak; the medication-side SNOMED rungs still gate on module
and activity alone. Target displays are then replaced with the server's
preferred term, so verify-curated's display check passes by construction.

`No response from agentic evaluator` IS AN ERROR, NOT A DECLINE, and the
service itself proves it. When the agentic loop genuinely looks and finds
nothing it says so precisely — 203 of this table's 241 `no-match` rows carry
`"Agentic eval matched 0 candidate(s) after N tool call(s)"`, which names the
outcome and the work done. `"No response from agentic evaluator"` is a
different, anomalous state: 30 rows carry it, all 30 with that string and
nothing else. Two cleanly separated populations, so the message is not a
badly-worded no-match.

This was got wrong once and the cost is worth recording. An intermediate version
of this file reclassified it as a decline, on the strength of a server log
showing the loop running 10-13 rounds and burning real tokens rather than
erroring. That evidence was real but incomplete: no legitimate empty result had
been captured for comparison, and once one was, the two proved distinguishable.
A rule inferred from failures alone, with no control, is how a wrong
classification looks right.

So the row is recorded with `codesearch_status: agentic-no-result`, a blank
target and a comment saying the service failed on it — NOT fatal to the run, and
NOT a claim that no SNOMED concept exists. `--append` re-asks exactly those rows,
which is the recovery path: the outcome is worth retrying and a genuine decline
is not.

THE CACHE IS TWO-TIER, AND BOTH TIERS OUTLIVE A RETRY. code-search caches errors
alongside successes, in an in-memory LRU with a 2-hour TTL checked BEFORE a
SQLite table (`resolutions` in `code-search.db`). So a poisoned entry returns the
identical empty body: retrying in-process is useless, restarting clears only the
memory tier, and evicting the database row alone leaves the memory tier serving
it for up to two hours. Recovering a failed label takes BOTH — delete the row,
then restart — after which `--append` re-asks it. That is why `find_code` does
not retry this outcome.

The key is `lower(text) + "||" + url + "||" + scope`, with whitespace runs
collapsed. Case and spacing therefore do not bust it; punctuation DOES, so a
hyphen-for-space edit produces a genuinely fresh call rather than a cache hit.

A run whose `agentic-no-result` count is identical to a previous run's is almost
certainly replaying cache rather than asking anything — that is exactly how the
first committed version of this table was caught carrying 30 replayed rows.

The classification is a SUBSTRING MATCH ON AN UNDOCUMENTED MESSAGE, because the
response carries no machine-readable outcome. If the authors reword it, these
rows silently become plain `no-match` and start being published as genuine
declines. The distinct status is what makes that drift visible in a diff. See
CODE-SEARCH-BUG-REPORT.md at the repo root.

NOT PART OF `make mappings`: it needs the network and a model-backed service,
and it WRITES a build input. Determinism lives in the split — this runs by hand,
its output is committed, and the build reads the committed CSV and never a
server.

Usage:
  uv run .../build_medication_etc_table.py --insecure
  uv run .../build_medication_etc_table.py --append --insecure
  uv run .../build_medication_etc_table.py --only 00000224,00001123 --insecure
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
from conceptmaps.lib.canonical import SNOMED, TABLE_DIR           # noqa: E402
from conceptmaps.lib.curated import CURATED_COLUMNS               # noqa: E402

OUT_CSV = TABLE_DIR / "medication-etc-snomed.csv"
LOG_JSON = paths.OUTPUT / "medication-etc-generation-log.json"

# Substances. The measured argument is in the docstring; the short version is
# that the product hierarchy contains no diuretic and no dihydropyridine, which
# is 4.66% of this element's occurrences.
SNOMED_ECL = "<<105590001"

CONFIDENCE_THRESHOLD = 0.80

# No template. The label is sent bare; see TEMPLATE above.
TEMPLATE = "{}"

# SNOMED CT international core. A national extension resolves on the server it
# was authored against and nowhere else, which is invisible from reading a CSV —
# and velonto serves only the AU edition, so this is load-bearing here.
INTERNATIONAL_CORE = "900000000000207008"

# What code-search puts in `reasoning` when its agentic loop finishes without
# converging on a concept. Matched as a SUBSTRING of an UNDOCUMENTED free-text
# message: if the authors reword it, this stops matching and these rows silently
# become plain `no-match`. That fragility is unavoidable from the client side —
# the response carries no machine-readable outcome — and is why the rows get
# their own status rather than being folded into no-match. See the docstring.
AGENTIC_NO_RESULT = "No response from agentic evaluator"

CURATED_HEADER = CURATED_COLUMNS + [
    # Provenance: read by lib/stats.py and discarded by the build. Recorded on
    # every row INCLUDING the ones where the proposal was then rejected, so any
    # mapping and any non-mapping can be audited from the CSV alone.
    "codesearch_target", "codesearch_display", "codesearch_confidence",
    "codesearch_status", "codesearch_reasoning",
]


def snomed_url(ecl=None):
    """A SNOMED ECL as its implicit-ValueSet canonical.

    NOT the VCL form. SNOMED CT has its own implicit ValueSet syntax and that is
    what the server and code-search resolve; a VCL wrapper round an ECL string
    404s.
    """
    return (f"{SNOMED}?fhir_vs=ecl/"
            + urllib.parse.quote(ecl or SNOMED_ECL, safe=""))


def get(fhir_base, path, **params):
    """A GET returning the parsed body, or None. Non-200 is not an answer."""
    query = urllib.parse.urlencode(params)
    status, body = http("GET", f"{fhir_base.rstrip('/')}/{path}?{query}")
    return body if status == 200 and body else None


# --------------------------------------------------------------------------- #
# code-search.
# --------------------------------------------------------------------------- #

def agentic_no_result(answer):
    """Did the service fail on this label rather than decline it?

    A genuine no-match says `Agentic eval matched 0 candidate(s) after N tool
    call(s)`. This string is a different, anomalous state, so the row is marked
    for retry rather than published as "no SNOMED concept exists". Recorded, not
    raised: one bad label must not discard a whole run's worth of good answers.
    """
    if (answer or {}).get("matches"):
        return False
    return AGENTIC_NO_RESULT in ((answer or {}).get("reasoning") or "")


def find_code(service, text, url, timeout, attempts=4):
    """code-search's best match for `text`, constrained to `url`.

    Retries transport failures for the reason build_d_items_table.py gives: a
    dropped connection is not an answer, and a run that quietly mixes 'no match'
    with 'the service was not running' produces a table that understates
    coverage and reads exactly like a real result. Exhausted retries raise, and
    main() refuses to write the CSV.

    A non-converging agentic loop is NOT in that class and is returned as an
    ordinary answer — build_row classifies it. Retrying it would be pointless
    anyway: the service caches the outcome and hands the identical body back.
    """
    body = json.dumps({
        "text": TEMPLATE.format(text),
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

def in_constraint(fhir_base, code):
    """True if `code` is a member of SNOMED_ECL, per the server.

    Asserted rather than assumed, because the service demonstrably answers with
    concepts outside the value set it was handed — `412250002 |Multivitamin
    agent|`, a Substance, came back from a product-hierarchy search above the
    threshold. Same check build_lab_fluid_table.py makes after #24's leak.
    """
    result = get(fhir_base, "ValueSet/$validate-code",
                 url=snomed_url(), system=SNOMED, code=code)
    if result is None:
        return False
    return any(p.get("name") == "result" and p.get("valueBoolean")
               for p in result.get("parameter", []))


def snomed_gate(fhir_base, code):
    """(ok, preferred_display): exists, active, international core module.

    The module check is the one a reader of the CSV cannot make. velonto serves
    only the AU edition, so an extension concept is not a hypothetical here — it
    resolves on the server it was picked from and nowhere else.
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


# --------------------------------------------------------------------------- #
# Resolving one row.
# --------------------------------------------------------------------------- #

def build_row(code, display, fhir_base, service, timeout):
    """One CSV row. One rung: there is no deterministic tier to try first.

    Unlike the drug-NAME streams there is nothing to join against — an FDB class
    label is not a term in any published terminology, so no index can settle a
    single row and every code goes to the service.
    """
    row = {c: "" for c in CURATED_HEADER}
    row["mimic_code"], row["mimic_display"] = code, display

    reply = find_code(service, display, snomed_url(), timeout)
    answer = best(reply)
    if answer is None:
        # Two ways to come back empty, kept apart because only one of them is
        # the service saying it looked and found nothing within the constraint.
        row["codesearch_status"] = ("agentic-no-result"
                                    if agentic_no_result(reply) else "no-match")
        row["codesearch_reasoning"] = (reply or {}).get("reasoning", "")
        return row

    target, proposed, confidence, reasoning = answer
    row.update(codesearch_target=target, codesearch_display=proposed,
               codesearch_confidence=f"{confidence:.2f}",
               codesearch_reasoning=reasoning)

    if confidence < CONFIDENCE_THRESHOLD:
        row["codesearch_status"] = "below-threshold"
        return row
    if not in_constraint(fhir_base, target):
        row["codesearch_status"] = "out-of-constraint"
        return row
    ok, preferred = snomed_gate(fhir_base, target)
    if not ok:
        row["codesearch_status"] = "gate-failed"
        return row

    row.update(codesearch_status="ok", snomed_code=target,
               snomed_display=preferred or proposed)
    return row


def declined_comment(row):
    """Why a blank target is a DECISION. A blank one with no reason is fatal
    in lib/curated.py, and rightly: a reader cannot audit silence."""
    proposal = (f"{row['codesearch_target']} "
                f"'{row['codesearch_display']}' at "
                f"{row['codesearch_confidence']}")
    return {
        "no-match": (f"code-search returned no match within SNOMED CT "
                     f"{SNOMED_ECL}."),
        "agentic-no-result": (
            f"NOT A DECLINE — code-search failed on this label, answering "
            f"'{AGENTIC_NO_RESULT}'. No concept was searched for and none was "
            f"rejected, so this must not be read as 'no SNOMED CT concept "
            f"exists within {SNOMED_ECL}'; a genuine no-match instead reports "
            f"'Agentic eval matched 0 candidate(s) after N tool call(s)'. The "
            f"outcome is cached on disk by the service, so re-asking requires "
            f"evicting it from code-search.db first; `--append` then re-asks "
            f"this row. See CODE-SEARCH-BUG-REPORT.md."),
        "below-threshold": (f"code-search proposed {proposal}, below the "
                            f"{CONFIDENCE_THRESHOLD} threshold."),
        "out-of-constraint": (f"code-search proposed {proposal} but that code "
                              f"is not a member of SNOMED CT {SNOMED_ECL}."),
        "gate-failed": (f"code-search proposed {proposal} but that concept is "
                        f"inactive or outside the SNOMED CT international "
                        f"core module."),
    }.get(row["codesearch_status"], f"code-search: {row['codesearch_status']}.")


# --------------------------------------------------------------------------- #

def ig_codes():
    """The observed source codes for every field that reads this table.

    Currently one — MedicationStatement.medication[x] — but read through
    lib/builders.table_population like every other generator, so a second
    consuming element extends the population with nothing to keep in step.
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

    The generation log records constraint, template and threshold ONCE, at top
    level, and lib/stats.py reads them as the settings that produced every row.
    Appending to a table whose committed rows predate a settings change would
    make that a lie — the log would describe the new rows and be quoted for all
    of them. A full regeneration is the correct response to moving a setting.
    """
    if not LOG_JSON.is_file():
        sys.exit(f"  --append needs {LOG_JSON.name} to check the committed "
                 f"rows were generated under today's settings, and it is "
                 f"missing. Run a full generation instead.")
    log = json.loads(LOG_JSON.read_text())
    current = {"constraint_ecl": SNOMED_ECL,
               "template": TEMPLATE,
               "confidence_threshold": CONFIDENCE_THRESHOLD}
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
    print("\n  code-search status", file=sys.stderr)
    for status, n in Counter(r["codesearch_status"] for r in rows
                             if r["codesearch_status"]).most_common():
        print(f"    {status:18s} {n:>6,}", file=sys.stderr)
    # The full distribution, so the threshold can be moved with evidence rather
    # than by taste — and so the [0.80, 0.85) gap the probes found can be
    # confirmed or refuted over the whole population.
    print("\n  confidence", file=sys.stderr)
    for confidence, n in sorted(Counter(r["codesearch_confidence"]
                                        for r in rows
                                        if r["codesearch_confidence"]).items()):
        print(f"    {confidence:18s} {n:>6,}", file=sys.stderr)
    mapped = sum(1 for r in rows if r["snomed_code"])
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
        # from the carry-over and re-asked. Note this only helps once the
        # service's on-disk cache has been cleared of them — otherwise the
        # identical empty body comes straight back; see the docstring.
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

    rows, failed = [], []
    with concurrent.futures.ThreadPoolExecutor(args.workers) as pool:
        futures = {pool.submit(build_row, code, display, fhir_base,
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
        # died is indistinguishable from one where the service said no.
        for code, exc in failed[:5]:
            print(f"    {code}: {exc}", file=sys.stderr)
        sys.exit(f"\n  {len(failed)} of {len(concepts)} call(s) failed. "
                 f"Refusing to write a table that would understate coverage.")

    for row in rows:
        if not row["snomed_code"]:
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
        "constraint_ecl": SNOMED_ECL,
        "constraint_url": snomed_url(),
        "template": TEMPLATE,
        "confidence_threshold": CONFIDENCE_THRESHOLD,
        "rows": rows,
    }, indent=1) + "\n")
    print(f"  wrote {LOG_JSON.name}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
