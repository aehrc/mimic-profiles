#!/usr/bin/env python3
"""Generate conceptmaps/micro-susc-loinc.csv — the 27 antibiotics → LOINC table.

The second generated table, and the first that targets LOINC. It follows
build_d_items_table.py in shape — network generation is a separate explicit
target, the build stays offline and byte-reproducible — and differs from it in
the three places a stream is allowed to differ: the constraint, the template and
the gate. Everything else here is that script's machinery.

WHAT THE SOURCE CODES MEAN. mimic-microbiology-antibiotic holds 27 bare drug
names — IMIPENEM, PIPERACILLIN/TAZO, CIPROFLOXACIN. They are bound to
Observation.code on MimicObservationMicroSusc, where the observation is a
susceptibility RESULT, so the code means 'susceptibility of this isolate to
imipenem', not the drug. That is why the target is LOINC and not RxNorm: RxNorm
names the substance, LOINC has a complete antibiotic-susceptibility set for
exactly this question, and it belongs to the medication rows of the parent
issue instead.

CONSTRAINT_VCL. LOINC's ABXBACT class IS the antibiotic-susceptibility set, so
the constraint can be much tighter than the CLASSTYPE=1 (Laboratory) filter the
issue proposed generically:

    CLASS = ABXBACT                              2,115 codes
      + STATUS = ACTIVE                          2,020
      + METHOD_TYP absent                          380

The third filter is the one that carries this stream. Without it the reachable
set includes `Imipenem [Susceptibility] by Minimum inhibitory concentration
(MIC)`, `… by Disk diffusion (KB)` and `… by Gradient strip` — all valid, all
active, all in class, and all asserting a laboratory method that MIMIC does not
record in Observation.code. That is the `Hemoglobin, Blood -> …by Oximetry`
inflation the parent issue predicted, and it is the case a CLASSTYPE/STATUS
filter provably cannot catch, because the bad target passes both. Excluding
METHOD_TYP means the bad answer is never proposed rather than rejected after the
fact — the same reason the d_items ECL is a union of three hierarchies and not
the implicit SNOMED ValueSet.

MimicObservationMicroSusc does carry a DilutionDetails extension, which is MIC
data, so a case exists for the MIC-method codes. It is declined deliberately:
the extension carries the dilution, and the code stays method-neutral, so a
consumer filtering Observation.code gets every susceptibility result for an
antibiotic rather than only the ones whose method happened to be recorded.

The constraint is passed to code-search as a VCL implicit ValueSet, which needs
no publish and therefore no write to the shared terminology server:

    http://fhir.org/VCL?v1=(http://loinc.org)(CLASS=ABXBACT,STATUS=ACTIVE,...)

Verified end to end before this script was written: asked for `Sodium [Moles/
volume] in Serum or Plasma` under this constraint, code-search escalates to its
agentic path and returns NO MATCH, while the same text against
`http://loinc.org/vs` returns 2951-2 at confidence 1.0. So the constraint is
genuinely applied and not silently dropped — which is the failure that would
have made every check here pass while measuring nothing.

TEMPLATE. Unsettled, and the one setting worth an A/B before the table is
committed. The d_items labels needed a template because 'Foley Catheter' names
a device and leaves the procedure implicit; here CLASS=ABXBACT already supplies
the entire context, and a bare 'IMIPENEM' probe scored 0.95 against the
constraint with no template at all. The sentence below is kept as the starting
point because the odd labels in this population are abbreviations
('PIPERACILLIN/TAZO', 'TRIMETHOPRIM/SULFA') rather than bare nouns, and it costs
nothing to state what the column is. Run both over the 27 and keep whichever
answers more of them correctly, then record the choice here.

THE GATE is the LOINC analogue of the SNOMED one, and it is shorter for a
principled reason. SNOMED needed 'active' and 'international core module'
because neither is expressible in an ECL constraint. Both LOINC analogues ARE
expressible here — STATUS=ACTIVE is in the constraint, and LOINC has no national
extensions — so membership of the constraint is the whole check, asserted with
$validate-code against the VCL URL rather than assumed from the fact that the
service was asked nicely.

One check the constraint cannot make is added: the target's display must have
the shape `<substance> [Susceptibility]`. The reachable 380 include qualified
variants such as `Ciprofloxacin [Susceptibility] for meningitis`, which is a
susceptibility code with a clinical breakpoint context MIMIC never records. A
target that fails the shape check is treated exactly as an absent one and the
item is left unmapped with the proposal recorded — the same treatment a
retired or extension concept gets in the d_items script. If the dry run shows
qualified variants winning, the fix is the template, not a relaxed gate.

EQUIVALENCE is not this script's concern. Every mapping a table supplies is
`relatedto`, set by lib/assemble.py when it builds the group. An earlier version
compared the MIMIC drug name against the target's substance and claimed
`equivalent` on a match, and the two abbreviated labels — PIPERACILLIN/TAZO,
TRIMETHOPRIM/SULFA — needed hand-written overrides to undo the mismatch that
produced; see lib/curated.py for why that whole layer went.

Why it is NOT part of `make mappings`: same as build_d_items_table.py. It needs
the network and an LLM-backed service, and it WRITES a build input. Determinism
lives in the split — this runs by hand, its output is committed, and `make
mappings` reads the committed CSV and never a server.

    make micro-susc-table ARGS=--insecure

Usage:
  uv run scripts/terminology-mapping/conceptmaps/build_micro_susc_table.py
  uv run .../build_micro_susc_table.py --only 90020,90026 --insecure
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
from conceptmaps.lib.canonical import LOINC  # noqa: E402
from conceptmaps.lib.curated import curated_columns  # noqa: E402
from conceptmaps.lib.igsource import source_concepts  # noqa: E402

# --------------------------------------------------------------------------- #
# The stated rules
# --------------------------------------------------------------------------- #

# LOINC's antibiotic-susceptibility class, active codes, no laboratory method.
# See the module docstring for the three counts and why the third filter is the
# one that matters.
CONSTRAINT_VCL = "(http://loinc.org)(CLASS=ABXBACT,STATUS=ACTIVE,METHOD_TYP?false)"

# One sentence, identical for all 27 items. Under review — see the module
# docstring. Set to "{}" to ask the bare label instead.
TEMPLATE = "Antimicrobial susceptibility test result for the antibiotic: {}"

# Below this, code-search's answer is discarded and the item is left unmapped.
# Matches build_d_items_table.py. The distribution is printed at the end of
# every run so it can be moved with evidence rather than by taste.
CONFIDENCE_THRESHOLD = 0.8

# What a usable LOINC susceptibility display looks like. A target outside this
# shape carries a clinical qualifier the MIMIC code does not — see the gate.
SUSCEPTIBILITY_SHAPE = re.compile(r"^(?P<substance>.+?) \[Susceptibility\]$")

# --------------------------------------------------------------------------- #
# Paths and provenance
# --------------------------------------------------------------------------- #

TERM = Path(__file__).resolve().parents[1]
OUT_CSV = Path(__file__).resolve().parent / "micro-susc-loinc.csv"
LOG_JSON = TERM / "output" / "micro-susc-generation-log.json"

# This table targets LOINC, so it says so in its own header rather than
# borrowing the SNOMED naming. lib.curated.load_table normalises both to
# `target_code` / `target_display` for the build.
TARGET_COLUMNS = ("loinc_code", "loinc_display")
CURATED = curated_columns(TARGET_COLUMNS)

# Identical in purpose to build_d_items_table.py's: what the service proposed on
# every row, including rows where the proposal was then rejected, so that "this
# antibiotic is unmapped" is auditable in the committed diff. Note that
# code-search's `fast` path returns an empty reasoning string, which is most of
# this population — the confidence and the proposed target still record.
PROVENANCE_COLUMNS = ["codesearch_target", "codesearch_display",
                      "codesearch_confidence", "codesearch_status",
                      "codesearch_reasoning"]

LOG_ONLY_COLUMNS = ["path"]

# --------------------------------------------------------------------------- #
# Sources
# --------------------------------------------------------------------------- #


def ig_codes():
    """(code, display) for the 27 antibiotics, read from the IG itself.

    Routed through the observation builder's own SOURCES declaration for the
    reason build_d_items_table.py gives: lib.curated.load_table rejects a row
    whose display differs from the IG's by so much as a character, so the
    generator and the build must read displays through the same function or the
    table this writes can fail the build that reads it.

    Note the source names the CodeSystem, not the bound ValueSet:
    ValueSet-mimic-microbiology-antibiotic.json is a bare compose with no
    enumerated concepts, so the CodeSystem is the only enumeration there is.
    """
    from conceptmaps.build_observation_cm_vs import SOURCES

    source = next(s for s in SOURCES if s.get("table") == OUT_CSV)
    return dict(source_concepts(source))


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

    Retries transport failures, for the reason build_d_items_table.py gives: a
    dropped connection is not an answer, and a run that quietly mixes 'no match'
    with 'the service was not running' produces a table that understates
    coverage and reads exactly like a real result. Exhausted retries raise, and
    main() refuses to write the CSV.
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

    Asserted rather than assumed. code-search was asked to honour the
    constraint and demonstrably does, but 'the service was asked nicely' is not
    a property a committed table should rest on — this is the LOINC counterpart
    of the d_items module check, and it subsumes STATUS=ACTIVE because the
    constraint carries that filter.
    """
    query = urllib.parse.urlencode({
        "url": constraint_url(), "system": LOINC, "code": code})
    status, body = http(
        "GET", f"{fhir_base.rstrip('/')}/ValueSet/$validate-code?{query}")
    if status != 200 or not body:
        return False
    return any(p["name"] == "result" and p.get("valueBoolean")
               for p in body.get("parameter", []))


def designations(fhir_base, code):
    """(display, {designations}) for a LOINC code, or None if absent.

    `display` is the server's own — the LONG_COMMON_NAME — not whatever string
    code-search carried next to the code, which is what keeps a display in the
    committed table a real designation of its concept by construction.
    """
    query = urllib.parse.urlencode({"system": LOINC, "code": code})
    status, body = http(
        "GET", f"{fhir_base.rstrip('/')}/CodeSystem/$lookup?{query}")
    if status != 200 or not body or body.get("resourceType") != "Parameters":
        return None
    display, names = None, set()
    for parameter in body.get("parameter", []):
        if parameter["name"] == "display":
            display = parameter["valueString"]
            names.add(display)
        elif parameter["name"] == "designation":
            for part in parameter["part"]:
                if part["name"] == "value":
                    names.add(part["valueString"])
    if display is None:
        return None
    return display, names


def gate(fhir_base, code):
    """('ok', display) if `code` is usable, else (reason, None).

    Used as a filter rather than an assertion: a target that fails here is
    treated exactly as an absent one and the item is left unmapped with the
    rejected proposal recorded.
    """
    if not in_constraint(fhir_base, code):
        return "out-of-constraint", None
    found = designations(fhir_base, code)
    if found is None:
        return "absent", None
    display, _ = found
    if not SUSCEPTIBILITY_SHAPE.match(display):
        # e.g. `Ciprofloxacin [Susceptibility] for meningitis` — a real
        # susceptibility code carrying a clinical breakpoint context that the
        # MIMIC code does not assert.
        return "qualified", None
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
# Both entries are here because the two displays do not read as a pair. MIMIC
# writes `AMPICILLIN/SULBACTAM` in full, matching LOINC, but truncates these two,
# so a reader comparing `PIPERACILLIN/TAZO` against `Piperacillin+Tazobactam`
# cannot tell from the row alone whether the extra component is a mismapping.
# Nothing in MIMIC's antibiotic dictionary names trimethoprim or piperacillin as
# a single agent alongside these, so the abbreviation is orthographic and not a
# claim about which components were tested.
COMMENT_OVERRIDES = {
    ("90008", "18998-5"): (
        "The MIMIC label abbreviates the second component of the combination "
        "the target names in full: `SULFA` is sulfamethoxazole. Both concepts "
        "are susceptibility to trimethoprim+sulfamethoxazole."),
    ("90026", "18970-4"): (
        "The MIMIC label abbreviates the second component of the combination "
        "the target names in full: `TAZO` is tazobactam. Both concepts are "
        "susceptibility to piperacillin+tazobactam."),
}


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


def build_row(item, fhir_base, service, timeout):
    """One CSV row: the service asked once, its answer gated."""
    code, label = item
    row = {c: "" for c in CURATED + PROVENANCE_COLUMNS + LOG_ONLY_COLUMNS}
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
                    row.update(loinc_code=match["code"],
                               loinc_display=display)
                    return row

    row["comment"] = declined_comment(row, confidence)
    return row


def declined_comment(row, confidence):
    """Why a row carries no target. load_table requires one, and rightly: an
    empty target is a claim that the source could not answer, and a claim has to
    say what it rests on."""
    proposal = (f"{row['codesearch_target']} "
                f"|{row['codesearch_display']}| at {confidence:.2f}")
    return {
        "no-match": (f"code-search returned no match within "
                     f"{CONSTRAINT_VCL}."),
        "below-threshold": (f"code-search proposed {proposal}, below the "
                            f"{CONFIDENCE_THRESHOLD} threshold."),
        "out-of-constraint": (f"code-search proposed {proposal} but that code "
                              f"is not a member of {CONSTRAINT_VCL}."),
        "absent": f"code-search proposed {proposal} but that code is not known.",
        "qualified": (f"code-search proposed {proposal}, which is not a plain "
                      f"'<substance> [Susceptibility]' code — it asserts a "
                      f"clinical context the MIMIC code does not record."),
    }.get(row["codesearch_status"], f"code-search: {row['codesearch_status']}.")


# --------------------------------------------------------------------------- #
# Reporting
# --------------------------------------------------------------------------- #


def report(rows):
    """What the run found. Printed so it can be pasted into a write-up."""
    mapped = [r for r in rows if r["loinc_code"]]
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
            print(f"    {label:<12} {len(hits):>4}  {'#' * len(hits)}")
        print(f"    threshold {CONFIDENCE_THRESHOLD}: "
              f"{sum(1 for s in scored if s >= CONFIDENCE_THRESHOLD)} kept, "
              f"{sum(1 for s in scored if s < CONFIDENCE_THRESHOLD)} dropped")

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
            print(f"    {row['mimic_code']} {row['mimic_display']}")


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

    items = sorted(ig_codes().items())
    if args.only:
        wanted = {c.strip() for c in args.only.split(",") if c.strip()}
        unknown = wanted - {c for c, _ in items}
        if unknown:
            sys.exit(f"  --only names code(s) not in the IG: {sorted(unknown)}")
        items = [i for i in items if i[0] in wanted]
        args.dry_run = True

    print(f"  {len(items)} IG code(s)"
          + (f" (subset of {len(ig_codes())}, --only)" if args.only else ""))
    print(f"  gate:       {args.fhir_base}")
    print(f"  service:    {args.service}")
    print(f"  constraint: {CONSTRAINT_VCL}")
    print(f"  template:   {TEMPLATE}")
    print(f"  threshold:  {CONFIDENCE_THRESHOLD}")
    print(f"  comments:   {len(COMMENT_OVERRIDES)}\n")

    def work(item):
        row = build_row(item, args.fhir_base, args.service, args.timeout)
        print(f"    {row['mimic_code']} {row['mimic_display'][:26]:<26} "
              f"{row['codesearch_status']:<18} {row['loinc_code'] or '—':<10} "
              f"{row['loinc_display'][:40]}", flush=True)
        return row

    with concurrent.futures.ThreadPoolExecutor(args.workers) as pool:
        rows = list(pool.map(work, items))

    # Sorted by mimic_code so a re-run diffs only where an answer changed, not
    # wherever the thread pool happened to finish first.
    rows.sort(key=lambda r: r["mimic_code"])

    # A transport failure is not an answer, so a partial run writes nothing.
    failed = [r for r in rows if r["codesearch_status"].startswith("error")]
    if failed:
        print(f"\n  {len(failed)} of {len(rows)} code-search call(s) failed "
              f"after retries — NOT writing {OUT_CSV.name}.")
        for row in failed[:5]:
            print(f"    {row['mimic_code']} {row['mimic_display'][:26]:<26} "
                  f"{row['codesearch_status'][:70]}")
        sys.exit("  Fix the service and re-run; cached answers make the "
                 "retry cheap.")

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
