#!/usr/bin/env python3
"""Resolve every stream once and write the per-stream statistics artefacts.

    output/stream-report.json     one block per stream: the headline numbers,
                                  the occurrence buckets, and the codesearch
                                  detail for table-backed streams. Committed —
                                  this is THE statistics file.
    unmapped-<stream>.csv         one worklist per stream, with each gap's
                                  reason and comment. Committed.
    output/occurrence-buckets.csv where every occurrence of every bound element
                                  goes: mapped, declined, blocked upstream, no
                                  stream yet, or admitted by no bound ValueSet.
                                  Committed.

A stream resolves identically wherever it is consumed (lib/assemble.py), so its
numbers are computed HERE, once, rather than once per consuming ConceptMap —
which is also why nothing here reads a ConceptMap: stream and map are two
projections of the same resolution, and verify_mappings checks they agree.

The report is over the BINDINGS, not over the stream registry. Every code a
bound ValueSet admits gets a row it can be found in, and a population no stream
declares is synthesised as a `declared: false` row at 0% rather than left out
(lib/streams.undeclared). The registry is hand-kept, so "we did not declare it"
and "there is nothing there" look identical from inside it; only the bindings
can tell them apart. Leaving the gap out would keep it out of the DENOMINATOR
too, which is the failure that matters — the headline coverage figure would be
computed over the work that was declared, and declaring a stream could then only
lower it.

Everything is a pure function of committed inputs (the IG's enumerations, the
committed tables, the built CodeSystems, the committed occurrence counts), so a
run from unchanged inputs is byte-identical and `make mappings && git diff
--exit-code` stays a valid test. No wall-clock timestamps.

The occurrence artifacts are OPTIONAL. Without them every count over the data
is omitted rather than zeroed — "nobody counted" and "the count found nothing"
are different statements — and the used-in-data denominator, the headline
percentage and the buckets simply do not appear. The one behavioural effect on
the maps themselves is documented in lib/assemble.resolve_source: without the
counts, a code nobody uses reports as `no-row-in-curated-table` rather than
`not-observed-in-data`.

Occurrence WEIGHTS mix two artifacts on purpose. An event element's codes are
weighted by code-occurrences.csv — one coding, one thing that happened to a
patient. A dictionary element (Medication, deduplicated to one resource per
drug tuple) is weighted by reference-occurrences.csv instead, which counts each
code once per REFERRING resource: summing dictionary counts with event counts
would be a category error, and counting the reference branch this way counts
each prescription exactly once.

Usage:
  uv run scripts/terminology-mapping/build_stream_reports.py [--quiet]
"""

import argparse
import csv
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import occurrences, paths                              # noqa: E402
from conceptmaps.lib import streams                                # noqa: E402
from conceptmaps.lib.assemble import MAPPED as OUTCOME_MAPPED      # noqa: E402
from conceptmaps.lib.assemble import (NOT_BUILT, method_of,        # noqa: E402
                                      resolve_source, unmapped_row)
from conceptmaps.lib.builders import consumers, discover           # noqa: E402
from conceptmaps.lib.built import load_built                       # noqa: E402
from conceptmaps.lib.igsource import resource_path                 # noqa: E402
from conceptmaps.lib.report import write_unmapped                  # noqa: E402
from conceptmaps.lib.stats import codesearch_block                 # noqa: E402

REPORT_NAME = "stream-report.json"


def floor_pct(numerator, denominator):
    """Floored, not rounded: only a genuinely complete population may show 100."""
    return int(10000 * numerator / denominator) / 100 if denominator else 0.0


def weight_for(element, kind, key, counts, refs):
    """How much data one (system, code) on one element stands for.

    Events: the coding count. Dictionary: the referring-resource count, and 0
    when reference-occurrences.csv is absent — never the dictionary count,
    which measures the size of a drug list rather than any data volume.
    """
    if kind == occurrences.EVENTS:
        return counts.by_element[element][key]
    return refs.get(key, 0)


def occurrence_weights(enum_set, mapped_keys, counts, refs, reg):
    """(total, mapped) occurrences over a population's codes, across elements.

    Shared by the declared and undeclared blocks so the two are weighted by one
    rule: an undeclared population reported on a different basis than the
    streams beside it would be a row a reader cannot compare with its
    neighbours, which is the whole reason for putting it in the table.
    """
    total = mapped = 0
    for element in counts.by_element:
        kind = occurrences.element_kind(element, reg)
        for key in counts.by_element[element]:
            if key not in enum_set:
                continue
            weight = weight_for(element, kind, key, counts, refs)
            total += weight
            if key in mapped_keys:
                mapped += weight
    return total, mapped


def stream_block(name, source, outcomes, counts, observed, refs, reg,
                 consumed_by, out_dir):
    """One stream's entry in the report."""
    enum_keys = [(source["system"], code) for code, _, _ in outcomes]
    enum_set = set(enum_keys)
    mapped_keys = {(source["system"], code)
                   for code, _, o in outcomes if o["kind"] == OUTCOME_MAPPED}
    by_equivalence = Counter(o["equivalence"] for _, _, o in outcomes
                             if o["kind"] == OUTCOME_MAPPED)
    by_equivalence["unmatched"] = len(outcomes) - len(mapped_keys)
    reasons = Counter(o["kind"] for _, _, o in outcomes
                      if o["kind"] != OUTCOME_MAPPED)

    block = {
        "stream": name,
        # Explicit on every block rather than defaulted on the undeclared ones:
        # this file is read by things that did not write it, and "declared" is
        # exactly the property a reader must not have to infer from an absence.
        "declared": True,
        "source_system": source["system"],
        "source_file": resource_path(source).name,
        "method": method_of(source),
        "target_systems": sorted({t["system"] for t in source["targets"]}),
        "consumed_by": consumed_by,
        "enumerated_total": len(outcomes),
        "mapped": len(mapped_keys),
        "by_equivalence": dict(sorted(by_equivalence.items())),
        "unmapped_by_reason": dict(sorted(reasons.items())),
    }
    if source.get("blocked_upstream"):
        block["blocked_upstream"] = True
    if source.get("note"):
        block["note"] = source["note"]
    if source.get("note_url"):
        block["note_url"] = source["note_url"]

    # A stream may sit OUTSIDE the extract: the occurrence job counts the ten
    # bound elements in occurrences/elements.json, and `units` is read off
    # Quantity.code, which is not one of them. Its used-in-data figures are
    # therefore OMITTED here for exactly the reason they are omitted when the
    # artifact is absent altogether — an empty column says "nobody counted",
    # while a zero would say "the count found nothing" and hand the stream a
    # 0.0 coverage_pct in mapping-statistics.csv despite 299 of 505 codes
    # resolving. Same distinction as observed_anywhere returning None rather
    # than an empty set, applied per stream because the artifact's coverage is
    # per element and so its silence is too.
    if counts is not None and not source.get("outside_occurrence_extract"):
        used = [key for key in enum_keys if key in observed]
        mapped_used = [key for key in used if key in mapped_keys]
        block.update({
            "used_in_data": len(used),
            "mapped_used": len(mapped_used),
            # THE headline: of the codes the warehouse actually uses, how many
            # resolve. Scored over used-in-data, with enumerated_total beside
            # it — either denominator alone misleads.
            "coverage_pct": floor_pct(len(mapped_used), len(used)),
            "codes_never_used": len(enum_keys) - len(used),
        })
        total_occ, mapped_occ = occurrence_weights(enum_set, mapped_keys,
                                                   counts, refs, reg)
        block.update({
            "occurrences_total": total_occ,
            "occurrences_mapped": mapped_occ,
            "occurrence_coverage_pct": floor_pct(mapped_occ, total_occ),
        })

    search = codesearch_block(source, out_dir)
    if search:
        block["codesearch"] = search
    return block


def undeclared_block(pop, counts, observed, refs, reg):
    """One BOUND population that no stream declares, as a stream row.

    Shaped exactly like stream_block's output so every consumer — the CSV, the
    HTML, the totals — carries it without a special case, and scored at 0%
    because that is what it resolves: nothing. The point is the DENOMINATOR.
    Left out of the table, 10,548 medication codes carrying 7.1M occurrences
    were absent from `all streams (used-in-data)` entirely, so declaring a
    stream for them could only ever move the headline figure DOWN — a coverage
    metric that punishes discovering work is a metric pointed the wrong way.

    `method` is `unstreamed` and not `declared`: `declared` is already a real
    resolver (see assemble.method_of), a population deliberately enumerated into
    a map so every admitted code gets a stated non-answer. This is its opposite
    — nothing enumerated it anywhere — and the two must not share a word.

    `consumed_by` carries the ELEMENTS whose bindings admit the codes. For a
    declared stream that column names the ConceptMaps consuming it; here there
    are none, and naming the bindings instead says who is waiting.
    """
    enum_set = {(pop["system"], code) for code in pop["concepts"]}
    block = {
        "stream": pop["stream"],
        "declared": False,
        "source_system": pop["system"],
        "source_file": "",
        "method": "unstreamed",
        "target_systems": [],
        "consumed_by": pop["bound_on"],
        "enumerated_total": len(enum_set),
        "mapped": 0,
        "by_equivalence": {"unmatched": len(enum_set)},
        "unmapped_by_reason": {NOT_BUILT: len(enum_set)},
        "note": (
            "No stream declares this population, so nothing resolves any of "
            "its codes and no ConceptMap carries an entry for them — a "
            f"$translate call returns silence. Bound on "
            f"{', '.join(pop['bound_on'])}. This row is synthesised from the "
            "bindings in occurrences/elements.json (lib/streams.undeclared) so "
            "the gap sits in the table and in the denominator; declare the "
            "stream in lib/streams.py to replace it with a real one."),
    }
    if counts is not None:
        used = [key for key in enum_set if key in observed]
        block.update({
            "used_in_data": len(used),
            "mapped_used": 0,
            "coverage_pct": 0.0,
            "codes_never_used": len(enum_set) - len(used),
        })
        total_occ, _ = occurrence_weights(enum_set, set(), counts, refs, reg)
        block.update({
            "occurrences_total": total_occ,
            "occurrences_mapped": 0,
            "occurrence_coverage_pct": 0.0,
        })
    return block


def undeclared_rows(pop):
    """The worklist for an undeclared population, one row per code.

    Written for the same reason every stream gets a worklist: the audience is
    whoever declares the stream, and a gap with no file is a gap with no
    handle. `expected_system` is empty because no target was ever chosen —
    naming one here would invent the decision the missing stream has to make.
    """
    return [{
        "stream": pop["stream"],
        "source_system": pop["system"],
        "mimic_code": code,
        "mimic_display": display,
        "expected_code": "",
        "expected_system": "",
        "reason": NOT_BUILT,
        "comment": (f"No stream declares {pop['system']}. Bound on "
                    f"{', '.join(pop['bound_on'])} and therefore admitted by a "
                    f"required binding, but nothing enumerates it into any "
                    f"ConceptMap, so $translate answers with silence rather "
                    f"than a declared non-answer."),
    } for code, display in sorted(pop["concepts"].items())]


def element_sections(counts, refs, reg, outcome_by_key, blocked_streams,
                     stream_of_key, mapped_elements, top_n):
    """Per-element buckets and top-N, for occurrence-buckets.csv and the HTML.

    Attribution is by code membership in a stream's enumeration — only the
    enumerations can say which stream a d-item belongs to.

    THE ORDER OF THE TESTS IS THE DESIGN. Each one asks about a deeper layer
    than the last, and the first that answers wins, so every occurrence lands in
    the bucket naming the OUTERMOST thing that has to change before $translate
    can resolve it:

      not-in-enumeration    no bound ValueSet admits the code. A defect whatever
                            any stream says about it, so it is asked first.
      no-stream-yet         no stream declares the population. Asked before the
                            ConceptMap question because building a map for this
                            element would not help — there is no answer to serve.
      blocked-upstream      a stream owns it and maps nothing by decision. A
                            property of the population, not of any map, so it
                            outranks the map question too; it is also what
                            element_summary subtracts for the achievable
                            denominator, which must not depend on which elements
                            happen to have builders.
      no-map-for-element    a stream resolved it, but this element has no
                            ConceptMap. The dictionary work is done and no
                            consumer can reach it.
      mapped / declined / unresolved-in-stream   what the stream itself found.

    Getting this order wrong is not an academic risk: with the ConceptMap test
    first — where it used to be — an element with no builder had EVERY admitted
    occurrence bucketed as backlog, and MedicationDispense.medication[x]'s
    1,550,601 genuinely unstreamed occurrences vanished inside 14,240,367 that
    only needed a builder.
    """
    index = occurrences._resource_index()  # noqa: SLF001 — same package
    buckets_rows, sections = [], []
    for element in sorted(counts.by_element):
        bound = {}
        for url in counts.registry.get(element, {}).get("bound_valuesets", []):
            bound.update(occurrences.expand(url, index))

        tallies = {b: {"codes": 0, "occurrences": 0}
                   for b in occurrences.BUCKETS}
        classified = {}
        element_total = counts.total(element)
        for key, n in counts.by_element[element].items():
            if key not in bound:
                bucket = occurrences.NOT_IN_ENUMERATION
            elif key not in stream_of_key:
                bucket = occurrences.NO_STREAM
            elif stream_of_key[key] in blocked_streams:
                bucket = occurrences.BLOCKED
            elif element not in mapped_elements:
                # `mapped_elements` is the builders' set. A stream may already
                # hold the answer — its own report still shows the code mapped
                # — but this table's question is "can a consumer calling
                # $translate resolve this data point", and with no map for the
                # element the answer is no.
                bucket = occurrences.NO_MAP
            else:
                # The full outcome dict for a mapped code, the reason string
                # for everything else — see main().
                kind = outcome_by_key[key]
                if isinstance(kind, dict):
                    bucket = occurrences.MAPPED
                elif kind == "no-suitable-concept":
                    bucket = occurrences.DECLINED
                else:
                    # no-row-in-curated-table / not-observed-in-data /
                    # absent-from-all-built-releases on an observed code: a
                    # backlog inside a stream that exists, not a judgement.
                    bucket = occurrences.UNRESOLVED
            classified[key] = bucket
            tallies[bucket]["codes"] += 1
            tallies[bucket]["occurrences"] += n

        for bucket in occurrences.BUCKETS:
            tally = tallies[bucket]
            buckets_rows.append({
                "element": element,
                "bucket": bucket,
                "codes": tally["codes"],
                "occurrences": tally["occurrences"],
                "share_pct": (round(100 * tally["occurrences"] / element_total, 2)
                              if element_total else 0.0),
            })

        ranked = sorted(counts.by_element[element].items(),
                        key=lambda kv: (-kv[1], kv[0]))[:top_n]
        top = [{
            "rank": rank,
            "system": system,
            "code": code,
            "display": (counts.displays[element].get((system, code))
                        or bound.get((system, code), "")),
            "occurrences": n,
            "share_pct": (round(100 * n / element_total, 2)
                          if element_total else 0.0),
            "bucket": classified[(system, code)],
            # outcome_by_key holds the full outcome dict for mapped codes and
            # only the reason string otherwise — see main().
            "target": (outcome["target_code"]
                       if isinstance(outcome := outcome_by_key.get(
                           (system, code)), dict) else ""),
        } for rank, ((system, code), n) in enumerate(ranked, 1)]
        sections.append({
            "element": element,
            "kind": occurrences.element_kind(element, reg),
            "has_conceptmap": element in mapped_elements,
            "observed_codes": len(counts.by_element[element]),
            "top": top,
        })
    return buckets_rows, sections


def write_buckets_csv(buckets, out_dir):
    path = out_dir / "occurrence-buckets.csv"
    with open(path, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["element", "bucket", "codes",
                                               "occurrences", "share_pct"])
        writer.writeheader()
        writer.writerows(buckets)
    return path


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out-dir", type=Path, default=paths.OUTPUT)
    ap.add_argument("--occurrences-dir", type=Path, default=paths.OCCURRENCES)
    ap.add_argument("--top-n", type=int, default=25,
                    help="most frequent codes kept per element (default: 25)")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)

    print("== stream reports ==", file=sys.stderr)
    disjoint = streams.check_disjoint()
    if disjoint:
        sys.exit("\n".join(f"  FAIL  {f}" for f in disjoint))

    built = load_built(args.out_dir)
    counts = occurrences.load(args.occurrences_dir)
    observed = occurrences.observed_anywhere(counts=counts) \
        if counts else None
    refs = occurrences.reference_counts(args.occurrences_dir)
    reg = occurrences.registry(args.occurrences_dir)
    if counts is None:
        print("  occurrence counts absent — reporting dictionary coverage "
              "only; used-in-data and every percentage over the data are "
              "omitted, not zeroed", file=sys.stderr)
    elif not refs and any(occurrences.element_kind(e, reg)
                          == occurrences.DICTIONARY
                          for e in counts.by_element):
        print("  reference-occurrences.csv absent — dictionary elements "
              "contribute no volume to the stream totals", file=sys.stderr)

    consumed = consumers()
    blocks = []
    outcome_by_key, stream_of_key, blocked_streams = {}, {}, set()
    for name in sorted(streams.STREAMS):
        source = streams.get(name)
        outcomes = resolve_source(source, built, observed)
        rows = [unmapped_row(source, code, display, o)
                for code, display, o in outcomes if o["kind"] != OUTCOME_MAPPED]
        write_unmapped(name, rows, args.out_dir)
        for code, _, o in outcomes:
            key = (source["system"], code)
            outcome_by_key[key] = o if o["kind"] == OUTCOME_MAPPED else o["kind"]
            stream_of_key[key] = name
        if source.get("blocked_upstream"):
            blocked_streams.add(name)
        block = stream_block(name, source, outcomes, counts, observed, refs,
                             reg, consumed.get(name, []), args.out_dir)
        blocks.append(block)
        if not args.quiet:
            used = block.get("used_in_data")
            tail = (f"{block.get('mapped_used'):>6,}/{used:<6,} used"
                    if used is not None else " " * 18)
            print(f"  {name:28s} {block['mapped']:>6,}/"
                  f"{block['enumerated_total']:<6,} enumerated  {tail}",
                  file=sys.stderr)

    # Every bound population no stream declares, as a 0% row. Synthesised AFTER
    # the declared streams and deliberately NOT added to stream_of_key: the
    # element buckets below distinguish "no stream declares this" from "a stream
    # does, and has no answer yet" by exactly that membership test.
    for pop in streams.undeclared():
        write_unmapped(pop["stream"], undeclared_rows(pop), args.out_dir)
        block = undeclared_block(pop, counts, observed, refs, reg)
        blocks.append(block)
        if not args.quiet:
            used = block.get("used_in_data")
            tail = (f"{0:>6,}/{used:<6,} used" if used is not None
                    else " " * 18)
            print(f"  {block['stream']:28s} {0:>6,}/"
                  f"{block['enumerated_total']:<6,} enumerated  {tail}"
                  f"  UNDECLARED", file=sys.stderr)
    # Alphabetical over the union, so a population declared later keeps its
    # place in the table rather than jumping out of an "undeclared" tail.
    blocks.sort(key=lambda b: b["stream"])

    buckets, sections, buckets_path = [], [], None
    if counts is not None:
        # element_sections wants MAPPED outcomes as dicts (for the target
        # column) and non-mapped as reason strings — outcome_by_key is built
        # exactly that way above.
        mapped_elements = {meta["element"] for _, _, meta in discover()}
        buckets, sections = element_sections(
            counts, refs, reg, outcome_by_key, blocked_streams,
            stream_of_key, mapped_elements, args.top_n)
        buckets_path = write_buckets_csv(buckets, args.out_dir)

    report = {"streams": blocks, "elements": sections}
    report_path = args.out_dir / REPORT_NAME
    report_path.write_text(json.dumps(report, indent=1) + "\n")
    written = [report_path.name,
               f"unmapped-<stream>.csv x{len(blocks)}"]
    if buckets_path:
        written.append(buckets_path.name)
    print(f"  wrote {', '.join(written)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
