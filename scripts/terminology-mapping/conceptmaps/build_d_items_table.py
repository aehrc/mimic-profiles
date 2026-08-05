#!/usr/bin/env python3
"""Generate conceptmaps/d-items-snomed.csv — the ICU flowsheet → SNOMED table.

Why this is a generator and not a curated file. Every other population in this
repo maps by rule, so a wrong target is a bug you can read in the code. The ICU
d_items were the exception: their displays are flowsheet labels rather than
clinical terms, so the table used to be built by hand. That makes each row rest
on a person's clinical judgement, which is not a method a reader can check or
reproduce. This script replaces judgement with one source whose answers carry
their own confidence and reasoning, and a gate that can be re-run: the
code-search service, constrained by CONSTRAINT_ECL and asked through TEMPLATE.

Anything it cannot answer above threshold is left unmapped, spelled as a blank
target with a comment saying why it declined. A declared gap is honest; a
plausible guess is not.

Why not OHDSI. An earlier version took OHDSI's MIMIC-IV → OMOP CDM crosswalk as
the primary source and used code-search as a gated second opinion. It was
dropped because the second opinion kept winning on clinical grounds: OHDSI put
'Presep Catheter' (a central venous oximetry catheter) on Swan-Ganz pulmonary
catheterisation and 'Midline' (by definition not a central line) on peripherally
inserted CENTRAL catheterisation, and it repeatedly chose a target carrying a
qualifier the flowsheet label never asserted — 'Hemodialysis' onto INTERMITTENT
haemodialysis, 'Tunneled (Hickman) Line' onto FLUOROSCOPY GUIDED tunnelled
catheterisation. Precedence was given to OHDSI on reproducibility grounds, which
is a real property, but it was shipping targets that were wrong about the
patient. The cost of dropping it is 32 items that now have no target at all,
chiefly the vascular-line family ('14/16/18/20/22 Gauge', 'Multi Lumen',
'Cordis/Introducer', 'Triple Introducer'), the temporary-LVAD lines and the
spine imaging items. Those are declared unmapped rather than guessed.

Why it is NOT part of `make mappings`. It needs the network and an LLM-backed
service, and it is the one stage whose output is not a pure function of the
inputs in this repo. Determinism lives in the split: this script runs
occasionally and by hand, its output is committed, and `make mappings` reads
the committed CSV and never a server. So `make mappings && git diff
--exit-code` stays a valid test of the build.

    make d-items-table ARGS=--insecure

Two configuration choices carry the accuracy, and both are stated rules applied
identically to all 169 items — neither involves a per-item decision.

Equivalence is not one of this script's concerns. Every mapping a table supplies
is `relatedto`, set by lib/assemble.py when it builds the group. An earlier
version derived a direction per row from the label and the target's designations
and kept an override list for the rows where that came out wrong; see
lib/curated.py for why that went.

CONSTRAINT_ECL. Queries are constrained to procedure ∪ clinical finding ∪
event. Not the full implicit SNOMED ValueSet: asked for 'Foley Catheter'
against all of SNOMED the service answers 73368009 |Foley catheter (physical
object)| at confidence 1.0, which is a correct reading of the text and an
unusable Procedure.code. The same is true of 'Midline' (a qualifier value),
'MAC' (a substance) and 'Pelvis' (a body structure). Confidence does not
separate these from good answers — the worst of them score highest, because the
service is confidently coding what the label literally says. Only the hierarchy
constraint separates them. Procedure alone would be too narrow: 'Fall',
'Chest Pain' and 'Pneumothorax' are genuinely not procedures, hence the union.

TEMPLATE. Each label is wrapped in one fixed sentence before being sent. The
labels are column headings from a procedureevents table, and that table is the
only place the word 'procedure' appears — 'Foley Catheter' names the device and
leaves the act of catheterisation implicit. The template supplies that context
uniformly, so it adds a fact about the source table rather than a judgement
about any item. Without it the constrained search correctly declines most of
the line/catheter population; with it they resolve to the insertion procedures.

Output columns. The five in CURATED_COLUMNS are what the builder reads;
everything after them is provenance, ignored by the build and present so a
reader can audit any row without re-running this script — what the service
proposed, at what confidence, and on what reasoning.
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
from conceptmaps.build_procedure_cm_vs import SOURCES  # noqa: E402
from conceptmaps.lib.canonical import SNOMED  # noqa: E402
from conceptmaps.lib.curated import CURATED_COLUMNS  # noqa: E402
from conceptmaps.lib.igsource import source_concepts  # noqa: E402
from verify.verify_curated_snomed import INTL_MODULE, lookup  # noqa: E402

# --------------------------------------------------------------------------- #
# The two stated rules
# --------------------------------------------------------------------------- #

# procedure ∪ clinical finding ∪ event. See the module docstring for why this
# is neither `<< 71388002` nor the unconstrained implicit ValueSet.
CONSTRAINT_ECL = "(<<71388002 OR <<404684003 OR <<272379006)"

# One sentence, identical for all 169 items.
TEMPLATE = "ICU procedure event recorded on placement or performance of: {}"

# Below this, code-search's answer is discarded and the item is left unmapped.
# The distribution is printed at the end of every run so this can be moved with
# evidence rather than by taste.
CONFIDENCE_THRESHOLD = 0.8

# --------------------------------------------------------------------------- #
# Paths and provenance
# --------------------------------------------------------------------------- #

TERM = Path(__file__).resolve().parents[1]
OUT_CSV = Path(__file__).resolve().parent / "d-items-snomed.csv"
LOG_JSON = TERM / "output" / "d-items-generation-log.json"

# What travels in the committed CSV: facts about the mapping, all stable across
# re-runs.
#
# The codesearch_* columns record what the service proposed on every row,
# including the rows where the proposal was then rejected by the threshold or
# by the gate — which is what makes "this item is unmapped" auditable in the
# committed diff rather than only in a run that has since scrolled away.
#
# The build ignores all of them: lib.curated.load_table reads CURATED_COLUMNS
# and discards the rest.
#
# Deliberately NOT `path` (cached / fast / agentic). That says how this
# particular run fetched an answer, not anything about the answer, so it flips
# to "cached" on the next run and shows up as 29 changed rows in a diff where
# no mapping moved. It is kept in the JSON log, where run detail belongs.
PROVENANCE_COLUMNS = ["codesearch_target", "codesearch_display",
                      "codesearch_confidence", "codesearch_status",
                      "codesearch_reasoning"]

# Recorded per row in the log only.
LOG_ONLY_COLUMNS = ["path"]

# --------------------------------------------------------------------------- #
# Sources
# --------------------------------------------------------------------------- #


def ig_codes():
    """(code, display) for the 169 items, read from the IG's own ValueSet.

    Deliberately routed through lib.igsource.source_concepts, and through the
    procedure builder's own SOURCES declaration, rather than reading the JSON
    here: lib.curated.load_table rejects a row whose display differs from the
    IG's by so much as a character, so the generator and the build must read the
    displays through the same function or the table it writes can fail the build
    that reads it.
    """
    source = next(s for s in SOURCES if "table" in s)
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
    'the service was not running' both end up as an unmapped row, and only one
    of them is a finding. A run that quietly mixes the two produces a table
    that understates coverage and reads exactly like a real result — which is
    how an earlier run reported 54 unmapped items when the true figure was 29.
    Exhausted retries raise, and main() refuses to write the CSV.
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

    The same three checks verify_curated_snomed.py enforces, but used as a
    filter rather than an assertion: a target that fails here is treated
    exactly as an absent one, and the item is left unmapped with the rejected
    proposal recorded. A confidence score says nothing about whether a concept
    is retired or belongs to a national extension — the service proposes 7
    AU-extension concepts that resolve on the server they were authored against
    and nowhere else, which is invisible by reading the CSV and would survive
    the build.

    The display returned is the server's preferred term, not whatever string
    the service carried next to the code. That is what keeps verify-curated's
    fourth check (display must be a real designation of the concept) green by
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


# --------------------------------------------------------------------------- #
# Reviewed comments
# --------------------------------------------------------------------------- #


# Prose notes on individual mappings, keyed on (mimic_code, snomed_code).
#
# NOT equivalence. Every mapping this table supplies is `relatedto`, fixed by
# lib/assemble.py, and nothing here can change it. What an entry adds is a
# sentence in ConceptMap.target.comment for a row where the code pair alone
# would mislead a reader — the mapping is stated, and so is what it does not
# carry.
#
# Keyed on the PAIR and not on the itemid alone, because each note was written
# about one specific target concept. If a re-run moves the target, the note no
# longer describes what it was written about, and apply_comments exits rather
# than carrying it silently onto a different concept.
#
# An entry that matches no row is fatal, not a no-op. A silent miss means a
# human's reading of a row quietly evaporates — the same failure
# lib.curated.load_table refuses on display drift, for the same reason.
#
# Comments only: this mechanism deliberately cannot pin a snomed_code. The
# moment it can, it becomes a way to hand-write mappings that bypass
# CONFIDENCE_THRESHOLD and the module gate, and the table stops being "what the
# service returned, gated" — which is the property that makes it reviewable. A
# target we believe is wrong is left unmapped, or TEMPLATE is changed; it is
# not overwritten here.
COMMENT_OVERRIDES = {
    # An epidural for ICU analgesia is sited at the level the indication asks
    # for — thoracic for thoracotomy or rib fractures, lumbar for the lower
    # body — and the flowsheet label records neither, while the target names the
    # lumbar space specifically. Worth stating because the two displays read as
    # an exact pair.
    ("227713", "446244002"): (
        "The MIMIC item records an epidural placed at any level; the target "
        "names the lumbar epidural space specifically. Thoracic placements "
        "are within the source item and outside the target."),
}


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


def build_row(item, fhir_base, service, timeout):
    """One CSV row: the service asked once, its answer gated.

    The proposal is recorded whether or not it survives — a row rejected at
    CONFIDENCE_THRESHOLD or at the module gate keeps `codesearch_target` and
    `codesearch_reasoning`, so the committed table shows what was considered and
    on what ground it was declined, rather than only that nothing was found.
    """
    code, label = item
    row = {c: "" for c in CURATED_COLUMNS + PROVENANCE_COLUMNS + LOG_ONLY_COLUMNS}
    row["mimic_code"] = code
    row["mimic_display"] = label

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
    """Why a row carries no target. load_curated requires one, and rightly:
    an empty target is a claim that the source could not answer, and a claim
    has to say what it rests on."""
    proposal = (f"{row['codesearch_target']} "
                f"|{row['codesearch_display']}| at {confidence:.2f}")
    return {
        "no-match": (f"code-search returned no match within "
                     f"{CONSTRAINT_ECL}."),
        "below-threshold": (f"code-search proposed {proposal}, below the "
                            f"{CONFIDENCE_THRESHOLD} threshold."),
        "retired": f"code-search proposed {proposal} but that concept is retired.",
        "extension": (f"code-search proposed {proposal} but that concept is "
                      f"not in the SNOMED international core."),
        "absent": f"code-search proposed {proposal} but that code is not known.",
        "no-display": f"code-search proposed {proposal} but it has no usable display.",
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
        print(f"    {status:<16} {count:>4}")

    scored = sorted(float(r["codesearch_confidence"]) for r in rows
                    if r["codesearch_confidence"])
    if scored:
        print(f"\n  code-search confidence, {len(scored)} answered")
        buckets = [(1.0, 1.01), (0.9, 1.0), (0.8, 0.9), (0.7, 0.8), (0.0, 0.7)]
        for low, high in buckets:
            hits = [s for s in scored if low <= s < high]
            label = f"{low:.2f}" if high > 1.0 else f"{low:.2f}–{high:.2f}"
            bar = "#" * len(hits)
            print(f"    {label:<12} {len(hits):>4}  {bar}")
        print(f"    threshold {CONFIDENCE_THRESHOLD}: "
              f"{sum(1 for s in scored if s >= CONFIDENCE_THRESHOLD)} kept, "
              f"{sum(1 for s in scored if s < CONFIDENCE_THRESHOLD)} dropped")

    commented = [r for r in rows if r["snomed_code"] and r["comment"]]
    if commented:
        print(f"\n  {len(commented)} mapped row(s) carrying a reviewed comment")
        for row in commented:
            print(f"    {row['mimic_code']} {row['mimic_display'][:34]:<34} "
                  f"-> {row['snomed_code']:<11} {row['snomed_display'][:44]}")

    unmapped = [r for r in rows if not r["snomed_code"]]
    print(f"\n  {len(unmapped)} unmapped, declared:")
    for row in unmapped:
        print(f"    {row['mimic_code']} {row['mimic_display']}")


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    add_common_args(parser)
    parser.add_argument("--service",
                        default=DEFAULT_CODE_SEARCH or "http://localhost:3000",
                        help="code-search base URL (default: $CODE_SEARCH_URL or "
                             "%(default)s)")
    parser.add_argument("--workers", type=int, default=6,
                        help="concurrent code-search calls (default: %(default)s)")
    parser.add_argument("--timeout", type=int, default=600,
                        help="per-call timeout in seconds (default: %(default)s)")
    parser.add_argument("--dry-run", action="store_true",
                        help="report only; do not write the CSV")
    args = parser.parse_args()

    configure_tls(args.ca_bundle, args.insecure)
    if not args.fhir_base:
        sys.exit("  no --fhir-base and ONTOSERVER_URL unset — the validation "
                 "gate needs a terminology server.")

    items = sorted(ig_codes().items())
    print(f"  {len(items)} IG code(s)")
    print(f"  gate:      {args.fhir_base}")
    print(f"  service:   {args.service}")
    print(f"  ECL:       {CONSTRAINT_ECL}")
    print(f"  template:  {TEMPLATE}")
    print(f"  threshold: {CONFIDENCE_THRESHOLD}")
    print(f"  comments:  {len(COMMENT_OVERRIDES)}\n")

    def work(item):
        row = build_row(item, args.fhir_base, args.service, args.timeout)
        print(f"    {row['mimic_code']} {row['mimic_display'][:34]:<34} "
              f"{row['codesearch_status']:<16} {row['snomed_code'] or '—':<12} "
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
        for row in failed[:5]:
            print(f"    {row['mimic_code']} {row['mimic_display'][:34]:<34} "
                  f"{row['codesearch_status'][:70]}")
        if len(failed) > 5:
            print(f"    … and {len(failed) - 5} more")
        sys.exit("  Fix the service and re-run; cached answers make the "
                 "retry cheap.")

    # After the failure gate, so that a run where the service dropped out
    # reports the transport failure rather than a wall of comments that could
    # not match because their targets never arrived.
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
        # curation as well as the run. The rest of the table is whatever the
        # service said, gated.
        "comment_overrides": {f"{code}->{target}": comment
                              for (code, target), comment
                              in sorted(COMMENT_OVERRIDES.items())},
        "fhir_base": args.fhir_base,
        # The service's own configuration at the end of the run. Recorded
        # because a `cached` path means the answer was produced by whatever
        # model was configured when it was first asked, which is not
        # necessarily this one — so this pins the run, not every row.
        "codesearch_service": service_info(args.service),
        "rows": rows,
    }, indent=2) + "\n")
    print(f"  wrote {LOG_JSON.relative_to(TERM.parents[1])}")


if __name__ == "__main__":
    main()
