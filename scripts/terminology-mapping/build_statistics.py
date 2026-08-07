#!/usr/bin/env python3
"""Flatten every <field>-report.json into one per-stream statistics table.

Three views of the same numbers, all derived, none hand-edited:

    output/mapping-statistics.csv    one row per stream across every field —
                                     the thesis interface. Committed.
    output/mapping-statistics.html   the same table plus stacked coverage
                                     bars, for looking at. Gitignored: a pure
                                     derived view, regenerate any time.
    the terminal table               printed on every run unless --quiet.

This script recomputes no mapping. It reads the `by_stream` arrays the builders
wrote (see lib/report.py) and flattens them, which is what keeps a partial run
honest: `make observation` refreshes observation-report.json, every other
field's report is the committed one, and the CSV assembled from all of them is
complete and current. Offline, deterministic, byte-identical from unchanged
reports — `make mappings && git diff --exit-code` stays a valid test.

One optional addition to that: if occurrences/code-occurrences.csv is present —
the committed per-code counts extracted once on the HPC node — every coverage
figure gains an occurrence-weighted twin, plus

    output/occurrence-buckets.csv    where every occurrence of a bound element
                                     goes: mapped, declined, no stream yet, or
                                     admitted by no bound ValueSet. Committed.

and the HTML grows a per-field section showing the head of the distribution with
each code's mapping status. Coverage over codes says how much of the dictionary
was mapped; coverage over occurrences says how likely a data point is to carry a
code $translate cannot resolve, and only the second is a claim about the data.
Both inputs are committed, so this stays offline and deterministic either way;
without the artifact everything behaves exactly as it did before it existed.
See common/occurrences.py and occurrences/README.md.

Usage:
  uv run scripts/terminology-mapping/build_statistics.py [--quiet] [--top-n 25]
"""

import argparse
import csv
import html
import json
import math
import sys
from pathlib import Path

from common import occurrences, paths

# The flat scalar columns. The nested Tier-B detail that does not flatten
# (confidence spread, constraint text, template) stays in the reports'
# by_stream entries; the CSV carries what a thesis table cites. Status and
# reason columns are appended dynamically from whatever the data contains, so
# a new generator status never needs a code change here.
FIXED_COLUMNS = ["field", "element", "stream", "source_system", "method",
                 "target_systems", "total", "mapped", "unmapped",
                 "coverage_pct", "equivalent", "relatedto", "unmatched",
                 "confidence_threshold", "confidence_median"]

# Present only when the occurrence artifact is, and placed immediately after
# coverage_pct rather than appended: the whole point is reading the weighted
# percentage against the unweighted one, which means they belong side by side.
OCCURRENCE_COLUMNS = ["occurrences_total", "occurrences_mapped",
                      "occurrence_coverage_pct", "codes_never_used",
                      "declined_never_used"]

# Present only for streams that narrowed their own population, and spliced in
# next to `total` so the narrowed denominator is read beside the number it
# narrowed. Dynamic for the same reason OCCURRENCE_COLUMNS is: a repo with no
# such stream gets a byte-identical CSV.
#
# `total` is the population the stream set out to map and `coverage_pct` is
# scored over it; `enumerated_total` is what the bound ValueSet admits. Both
# are carried because either one alone misleads — the first hides that a
# narrowing happened, the second describes a job nobody attempted.
RESTRICTION_COLUMNS = ["restriction", "enumerated_total", "not_observed"]

BAR_WIDTH = 20

# equivalent / relatedto / unmatched, in the HTML bars and nowhere else.
COLORS = {"equivalent": "#2f9e44", "relatedto": "#1971c2",
          "unmatched": "#adb5bd"}

# The occurrence buckets. Green for what $translate resolves, orange for a
# decision this repo made and will defend, purple for a stream blocked by
# something outside terminology, grey for a backlog, red for a code no bound
# ValueSet admits — which under a required binding is a defect, so it is the one
# colour that should never appear.
BUCKET_COLORS = {occurrences.MAPPED: "#2f9e44",
                 occurrences.DECLINED: "#e8590c",
                 # Hatched-looking mid grey-purple: not a mapping failure, so it
                 # must not read as one, but not neutral backlog either.
                 occurrences.BLOCKED: "#7048e8",
                 occurrences.NO_STREAM: "#adb5bd",
                 occurrences.NOT_IN_ENUMERATION: "#c92a2a"}

BUCKET_LABELS = {occurrences.MAPPED: "mapped",
                 occurrences.DECLINED: "declined",
                 occurrences.BLOCKED: "blocked upstream",
                 occurrences.NO_STREAM: "no stream yet",
                 occurrences.NOT_IN_ENUMERATION: "in no bound ValueSet"}

# The code-search status split, in the order the second HTML table reads best:
# what the gate accepted, what it rejected on confidence, then the cases where
# there was nothing to score. Any status not listed here is appended, sorted —
# a new generator status shows up without a code change, same as in the CSV.
STATUS_ORDER = ("ok", "below-threshold", "no-match", "extension")

# The grand total is 99.45%, and on its own it says almost nothing: 40,488 of
# the 41,138 source codes are ICD, mapped by a deterministic notation transform
# that cannot fail. The method split is what stops that number being read as a
# claim about mapping quality — the 637 codes code-search touched are where the
# thresholds, the near-miss ladder, and the actual difficulty live.
METHOD_ORDER = ("notation", "identity", "table")
METHOD_LABELS = {"notation": "notation (ICD)", "table": "code-search"}


def load_reports(out_dir):
    """Every field report carrying a by_stream array, sorted by field."""
    reports = []
    for path in sorted(out_dir.glob("*-report.json")):
        data = json.loads(path.read_text())
        if isinstance(data, dict) and "field" in data and "by_stream" in data:
            reports.append(data)
    return sorted(reports, key=lambda r: r["field"])


def flatten(reports):
    """One flat dict per stream, in (field, declaration) order."""
    rows = []
    for report in reports:
        for stream in report["by_stream"]:
            search = stream.get("codesearch", {})
            confidence = search.get("confidence", {})
            row = {
                "field": report["field"],
                "element": report["element"],
                "stream": stream["stream"],
                "source_system": stream["source_system"],
                "method": stream["method"],
                "target_systems": ";".join(stream["target_systems"]),
                "total": stream["total"],
                "mapped": stream["mapped"],
                "unmapped": stream["unmapped"],
                "coverage_pct": stream["coverage_pct"],
                "equivalent": stream["by_equivalence"].get("equivalent", 0),
                "relatedto": stream["by_equivalence"].get("relatedto", 0),
                "unmatched": stream["by_equivalence"].get("unmatched", 0),
                "confidence_threshold": search.get("confidence_threshold", ""),
                "confidence_median": confidence.get("median", ""),
            }
            # Not a CSV column: prose does not belong in a citable table, and
            # the HTML is where a reader meets the number that needs it.
            if stream.get("note"):
                row["_note"] = stream["note"]
                row["_note_url"] = stream.get("note_url", "")
            if stream.get("restriction"):
                row["restriction"] = stream["restriction"]
                row["enumerated_total"] = stream.get("enumerated_total", "")
                row["not_observed"] = stream.get("not_observed", "")
            # Blank, not zero, for a stream that never ran a code search: "no
            # proposal was ever scored" and "no proposal landed near the gate"
            # are different claims, and only the second is a zero.
            for rung, count in search.get("near_threshold", {}).items():
                row[f"within_{rung}"] = count
            for status, count in search.get("status", {}).items():
                row[f"status_{status}"] = count
            for reason, count in stream["unmapped_by_reason"].items():
                row[f"reason_{reason}"] = count
            rows.append(row)
    return rows


def totals(rows):
    """[(label, mapped, total, pct)] — every stream, then one line per method.

    Never the grand total alone; see METHOD_ORDER for why.
    """
    def line(label, group):
        mapped = sum(r["mapped"] for r in group)
        total = sum(r["total"] for r in group)
        if not total:
            return (label, mapped, total, 0.0)
        # Floored, not rounded: 40,486/40,488 is 99.995%, and rounding that to
        # 100.00% would report two unmapped ICD-9 procedure codes as a complete
        # stream. Only a genuinely complete group may display 100.
        return (label, mapped, total, math.floor(10000 * mapped / total) / 100)

    methods = sorted({r["method"] for r in rows},
                     key=lambda m: (METHOD_ORDER.index(m)
                                    if m in METHOD_ORDER else len(METHOD_ORDER),
                                    m))
    return [line("all streams", rows)] + [
        line(METHOD_LABELS.get(m, m), [r for r in rows if r["method"] == m])
        for m in methods]


def codesearch_streams(reports):
    """The table-backed streams only, carrying their whole codesearch block.

    The flat CSV rows cannot serve the second HTML table: `near_misses` is a
    list of rejections, which is not a cell. This walks the same reports again
    and keeps the nested block intact.
    """
    streams = []
    for report in reports:
        for stream in report["by_stream"]:
            if stream.get("codesearch"):
                streams.append({"field": report["field"],
                                "stream": stream["stream"],
                                **stream["codesearch"]})
    return streams


def columns_for(rows):
    """Fixed columns (occurrence and restriction ones spliced in where they
    belong, if present), the within_ rungs in numeric order, then whatever
    status_/reason_ columns the data has."""
    # `_`-prefixed keys are HTML-only annotations (see write_html); the CSV is
    # the citable table and carries numbers, not prose.
    present = {k for row in rows for k in row if not k.startswith("_")}
    fixed = list(FIXED_COLUMNS)
    if present & set(OCCURRENCE_COLUMNS):
        at = fixed.index("coverage_pct") + 1
        fixed[at:at] = OCCURRENCE_COLUMNS
    if present & set(RESTRICTION_COLUMNS):
        at = fixed.index("total")
        fixed[at:at] = RESTRICTION_COLUMNS
    dynamic = present - set(fixed)
    within = sorted((k for k in dynamic if k.startswith("within_")),
                    key=lambda k: float(k.split("_", 1)[1]))
    return fixed + within + sorted(dynamic - set(within))


def write_csv(rows, out_dir):
    path = out_dir / "mapping-statistics.csv"
    with open(path, "w", newline="") as fh:
        # extrasaction: columns_for() already drops the `_`-prefixed HTML-only
        # annotations from the header, and without this DictWriter then refuses
        # the rows that carry them. Narrow by construction — every other key a
        # row can hold is picked up dynamically, so this cannot silently swallow
        # a real column.
        writer = csv.DictWriter(fh, fieldnames=columns_for(rows), restval="",
                                extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    return path


def apply_occurrences(rows, stream_stats):
    """Merge the per-stream occurrence numbers into the flat rows, in place.

    A stream with no entry keeps no occurrence columns at all rather than zeros:
    "this stream's codes never occur" and "nobody counted this element" are
    different statements, and only the first is a zero.
    """
    for row in rows:
        stats = stream_stats.get((row["field"], row["stream"]))
        if stats:
            row.update(stats)
    return rows


def write_buckets_csv(buckets, out_dir):
    """Where every occurrence of every bound element goes. Committed."""
    path = out_dir / "occurrence-buckets.csv"
    with open(path, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["element", "bucket", "codes",
                                               "occurrences", "share_pct"])
        writer.writeheader()
        writer.writerows(buckets)
    return path


def bar(row, width=BAR_WIDTH):
    """`██████████░░░░` — mapped share of a stream, for the terminal."""
    filled = round(width * row["mapped"] / row["total"]) if row["total"] else 0
    return "█" * filled + "░" * (width - filled)


def print_table(rows):
    stream_width = max([len(r["stream"]) for r in rows] + [len("stream")])
    header = (f"  {'field':22s} {'stream':{stream_width}s} {'method':8s} "
              f"{'mapped':>13s}  {'':{BAR_WIDTH}s} {'cov':>6s}  "
              f"{'equivalent':>10s} {'relatedto':>9s} {'unmatched':>9s}")
    print(header, file=sys.stderr)
    print("  " + "-" * (len(header) - 2), file=sys.stderr)
    for r in rows:
        print(f"  {r['field']:22s} {r['stream']:{stream_width}s} "
              f"{r['method']:8s} {r['mapped']:>6,}/{r['total']:<6,} "
              f"{bar(r)} {r['coverage_pct']:>5.1f}%  "
              f"{r['equivalent']:>10,} {r['relatedto']:>9,} "
              f"{r['unmatched']:>9,}", file=sys.stderr)
    print("  " + "-" * (len(header) - 2), file=sys.stderr)
    for i, (label, mapped, total, pct) in enumerate(totals(rows)):
        indent = "  " if i else ""
        print(f"  {indent}{label:{22 + stream_width + 10 - len(indent)}s}"
              f"{mapped:>6,}/{total:<6,} {'':{BAR_WIDTH}s} {pct:>6.2f}%",
              file=sys.stderr)


def print_occurrences(buckets):
    """The element-level headline: what share of the DATA the maps resolve.

    Printed under the per-stream table because it answers a different question
    from every line above it — not "how much of the dictionary did we map" but
    "how often does a code the map cannot resolve actually turn up".
    """
    summary = occurrences.element_summary(buckets)
    width = max([len(element) for element, *_ in summary] + [len("element")])
    # `achievable` shows only when something is blocked, so an element with
    # nothing blocked reads exactly as it did before.
    any_blocked = any(achievable != total
                      for _, _, total, _, achievable, _ in summary)
    extra = f"{'achievable':>11s}" if any_blocked else ""
    print(f"\n  {'element':{width}s} {'occurrences mapped':>22s} "
          f"{'cov':>7s}  {'unmapped chance':>15s}{extra}", file=sys.stderr)
    print("  " + "-" * (width + 49 + len(extra)), file=sys.stderr)
    for element, mapped, total, pct, achievable, achievable_pct in summary:
        tail = ""
        if any_blocked:
            tail = (f"{achievable_pct:>10.2f}%" if achievable != total
                    else f"{'—':>11s}")
        print(f"  {element:{width}s} {mapped:>10,}/{total:<11,} "
              f"{pct:>6.2f}%  {100 - pct:>14.2f}%{tail}", file=sys.stderr)


def codesearch_table(streams):
    """The second table: what code-search proposed, and what the gate refused.

    The coverage table above it can only say a code went unmapped. This says
    the proposal existed, scored 0.75, and was a broader concept — which is the
    difference between "no candidate" and "a candidate this threshold declined",
    and the only form in which "should the threshold be lower?" is a question a
    reader can actually answer.
    """
    if not streams:
        return ""
    statuses = {s for stream in streams for s in stream.get("status", {})}
    status_cols = ([s for s in STATUS_ORDER if s in statuses]
                   + sorted(statuses - set(STATUS_ORDER)))
    rungs = sorted({r for stream in streams
                    for r in stream.get("near_threshold", {})}, key=float)
    width = 3 + len(status_cols) + len(rungs) + 3

    def cls(index, base):
        """`sep` on the first column of a group, so the reader can tell the
        status block from the rung block at a glance."""
        return f"{base} sep" if index == 0 else base

    def misses(stream):
        rejected = stream.get("near_misses", [])
        if not rejected:
            return ""
        # Not every table records a reasoning; outputevents has none at all.
        items = "".join(
            "<li>"
            f'<span class="conf">{m["confidence"]:.2f}</span> '
            f'{html.escape(m["mimic_display"])} '
            f'<span class="arrow">&rarr;</span> '
            f'{html.escape(m["proposed_display"])} '
            f'<code>{html.escape(m["proposed_code"])}</code>'
            + (f'<div class="why">{html.escape(m["reasoning"])}</div>'
               if m["reasoning"].strip() else "")
            + "</li>"
            for m in rejected)
        return (f'<tr class="detail"><td colspan="{width}">'
                f"<details><summary>{len(rejected)} rejected "
                f"proposal{'s' if len(rejected) != 1 else ''}, furthest below "
                f'the gate last</summary><ul class="misses">{items}</ul>'
                "</details></td></tr>")

    def row(stream):
        confidence = stream.get("confidence", {})
        spread = (f'{confidence["min"]:.2f} / {confidence["median"]:.2f} / '
                  f'{confidence["max"]:.2f}' if confidence else "")
        return (
            "<tr>"
            f"<td>{html.escape(stream['field'])}</td>"
            f"<td>{html.escape(stream['stream'])}</td>"
            f"<td class='n'>{stream.get('confidence_threshold', '')}</td>"
            + "".join(f"<td class='{cls(i, 'n')}'>"
                      f"{stream.get('status', {}).get(s, 0):,}</td>"
                      for i, s in enumerate(status_cols))
            + "".join(f"<td class='{cls(i, 'n rung')}'>"
                      f"{stream.get('near_threshold', {}).get(r, '')}</td>"
                      for i, r in enumerate(rungs))
            + f"<td class='n sep'>{spread}</td>"
            "</tr>") + misses(stream)

    head = ("<tr><th>field</th><th>stream</th><th class='n'>threshold</th>"
            + "".join(f"<th class='{cls(i, 'n')}'>{html.escape(s)}</th>"
                      for i, s in enumerate(status_cols))
            + "".join(f'<th class="{cls(i, "n rung")}">'
                      f"&le;&thinsp;{html.escape(r)}</th>"
                      for i, r in enumerate(rungs))
            + "<th class='n sep'>min / median / max</th></tr>")
    return f"""
<h2>Code-search proposals, and what the threshold refused</h2>
<p>The table-backed streams only. The <span class="rung-key">&le;&nbsp;x</span>
columns are <em>cumulative</em>: each counts every rejected proposal scoring
within <em>x</em> of the gate, so the column reads as the number of mappings a
threshold lowered by <em>x</em> would have accepted &mdash; a proposal sitting
exactly on the new line included, because such a threshold accepts it. Expand a
row to read the rejections themselves: most are relevant but <em>broader</em>
concepts, which would enter as <code>relatedto</code> rather than
<code>equivalent</code>, so lowering the gate buys coverage at the cost of
precision rather than simply recovering lost matches.</p>
<table class="cs">
{head}
{"".join(row(s) for s in streams)}
</table>
"""


def occurrence_section(reports, counts, buckets, top):
    """Per bound element: the two percentages, the four buckets, and the head of
    the distribution with each code's status.

    The coverage table above this page's fold can only say a code went unmapped.
    This says how much data sat behind it — and the top-N table is where the two
    percentages diverging becomes legible, because you can read down the most
    frequent codes and see which of them nothing resolves.
    """
    if not counts:
        return ""
    by_element = {r["element"]: r for r in reports}
    rows_by_element = {}
    for row in buckets:
        rows_by_element.setdefault(row["element"], []).append(row)

    def stacked(element_rows, total):
        parts = []
        for row in element_rows:
            if not row["occurrences"]:
                continue
            share = 100 * row["occurrences"] / total
            parts.append(
                f'<div class="seg" style="width:{share:.2f}%;'
                f'background:{BUCKET_COLORS[row["bucket"]]}" '
                f'title="{BUCKET_LABELS[row["bucket"]]}: '
                f'{row["occurrences"]:,} ({share:.2f}%)"></div>')
        return f'<div class="bar">{"".join(parts)}</div>'

    def status(entry):
        label = BUCKET_LABELS[entry["bucket"]]
        if entry["bucket"] == occurrences.MAPPED and entry["target"]:
            return f'mapped <code>{html.escape(entry["target"])}</code>'
        if entry["bucket"] == occurrences.NO_STREAM:
            return (f'{label} <span class="dim">'
                    f'{html.escape(entry["system"].rsplit("/", 1)[-1])}</span>')
        return label

    def top_table(element):
        entries = top.get(element, [])
        if not entries:
            return ""
        cells = "".join(
            f'<tr class="{"miss" if e["bucket"] != occurrences.MAPPED else ""}">'
            f'<td class="n">{e["rank"]}</td>'
            f'<td><code>{html.escape(e["code"])}</code></td>'
            f'<td>{html.escape(e["display"])}</td>'
            f'<td class="n">{e["occurrences"]:,}</td>'
            f'<td class="n">{e["share_pct"]:.2f}%</td>'
            f"<td>{status(e)}</td></tr>"
            for e in entries)
        return (f"<details><summary>{len(entries)} most frequent codes</summary>"
                '<table class="top"><tr><th class="n">#</th><th>code</th>'
                '<th>display</th><th class="n">occurrences</th>'
                '<th class="n">share</th><th>status</th></tr>'
                f"{cells}</table></details>")

    def achievable_row(mapped, total, achievable, achievable_pct):
        """The second denominator, shown only when it differs from the first.

        Excluding the occurrences that were never a candidate for the target
        code system, so the figure says how well the MAPPING did rather than how
        well the data was modelled. Both are on the page because either alone
        misleads — see occurrences.element_summary.
        """
        if achievable == total:
            return ""
        blocked = total - achievable
        return (f'<tr><td>&nbsp;&nbsp;achievable</td>'
                f'<td class="n">{mapped:,}&thinsp;/&thinsp;{achievable:,}</td>'
                f'<td class="n">{achievable_pct:.2f}%</td>'
                f'<td class="dim">excluding {blocked:,} occurrence(s) in '
                f'streams blocked upstream, which no code system could have '
                f'covered &mdash; see the per-stream footnote</td></tr>')

    blocks = []
    for (element, mapped, total, pct, achievable,
         achievable_pct) in occurrences.element_summary(buckets):
        report = by_element.get(element)
        if report:
            code_total = report["source_total"]
            code_pct = 100 * report["mapped"] / code_total if code_total else 0.0
            code_row = (f'<tr><td>codes</td>'
                        f'<td class="n">{report["mapped"]:,}&thinsp;/&thinsp;'
                        f'{code_total:,}</td><td class="n">{code_pct:.1f}%</td>'
                        f'<td class="dim">of the bound dictionary</td></tr>')
        else:
            # No ConceptMap for this element yet. Its whole occurrence count is
            # backlog, and saying so is the point of listing it here at all.
            code_row = ('<tr><td>codes</td><td class="n">&mdash;</td>'
                        '<td class="n"></td><td class="dim">no ConceptMap for '
                        'this element yet</td></tr>')
        legend = "".join(
            f'<span class="key"><span class="swatch" '
            f'style="background:{BUCKET_COLORS[b]}"></span>'
            f"{BUCKET_LABELS[b]}</span>" for b in occurrences.BUCKETS)
        blocks.append(f"""
<h3>{html.escape(element)}</h3>
<table class="pair">
{code_row}
<tr><td>occurrences</td><td class="n">{mapped:,}&thinsp;/&thinsp;{total:,}</td>
<td class="n">{pct:.2f}%</td>
<td class="dim">&rarr; a data point here has a
<strong>{100 - pct:.2f}%</strong> chance of carrying an unresolvable code</td></tr>
{achievable_row(mapped, total, achievable, achievable_pct)}
</table>
{stacked(rows_by_element.get(element, []), total) if total else ""}
<p class="legend">{legend}</p>
{top_table(element)}
""")

    summary = counts.summary
    tables = ", ".join(
        f"{name} v{info['delta_version']}"
        for name, info in sorted(summary.get("tables", {}).items())
        if "delta_version" in info)
    return f"""
<h2>Occurrence-weighted coverage</h2>
<p>Every figure above counts each source code once. These count it as often as
it occurs in the warehouse, which is the difference between &ldquo;how much of
the dictionary did we map&rdquo; and &ldquo;how likely is a data point to carry
a code <code>$translate</code> cannot resolve&rdquo;. The two diverging is the
finding: a stream can map three quarters of its codes and a small fraction of
its rows.</p>
<p><em>declined</em> is a built stream that considered a code and said no, with
its reason in <code>unmapped-&lt;field&gt;.csv</code>; <em>no stream yet</em> is
a bound population nobody has built, which is a backlog rather than a mapping
failure; <em>in no bound ValueSet</em> is a code the data carries that no bound
ValueSet admits, and under a required binding that is a defect, so it should be
empty.</p>
<p class="dim">Counted on {html.escape(summary.get('host', '?'))} at
{html.escape(summary.get('generated', '?'))} from
<code>{html.escape(summary.get('warehouse', '?'))}</code>{f' ({html.escape(tables)})' if tables else ''}.
See <code>occurrences/README.md</code>.</p>
{"".join(blocks)}
"""


def write_html(rows, codesearch, out_dir, occurrence_html=""):
    """Self-contained table + stacked bars. A view, not a deliverable."""
    # Two extra per-stream columns, only when the occurrence artifact supplied
    # them: the weighted percentage next to the unweighted one is the whole
    # comparison, and it should not need a second file to be read.
    weighted = any("occurrence_coverage_pct" in row for row in rows)

    def occurrence_cells(row):
        if not weighted:
            return ""
        if "occurrence_coverage_pct" not in row:
            return "<td class='n sep'></td><td class='n'></td>"
        return (f"<td class='n sep'>{row['occurrences_mapped']:,}"
                f"&thinsp;/&thinsp;{row['occurrences_total']:,}</td>"
                f"<td class='n'>{row['occurrence_coverage_pct']:.1f}%</td>")

    def stacked(row):
        if not row["total"]:
            return ""
        parts = []
        for key in ("equivalent", "relatedto", "unmatched"):
            share = 100 * row[key] / row["total"]
            if share:
                parts.append(
                    f'<div class="seg" style="width:{share:.2f}%;'
                    f'background:{COLORS[key]}" title="{key}: {row[key]:,}">'
                    f'</div>')
        return f'<div class="bar">{"".join(parts)}</div>'

    # Footnotes, numbered in the order the streams appear so the markers read
    # top-to-bottom. A stream carries one when its numbers need prose to be
    # read correctly — a correct 0% is the motivating case.
    noted = [r for r in rows if r.get("_note")]
    marker = {id(r): n for n, r in enumerate(noted, 1)}

    def note_marker(row):
        if id(row) not in marker:
            return ""
        n = marker[id(row)]
        return (f'<sup class="fn"><a href="#fn{n}" id="ref{n}">{n}</a></sup>')

    def note_item(row):
        n = marker[id(row)]
        link = ""
        if (url := row.get("_note_url")):
            # A GitHub issue URL ends in its number, so "#26" is the label a
            # reader expects. Anything else is shown as itself.
            tail = url.rstrip("/").rsplit("/", 1)[-1]
            label = f"#{tail}" if tail.isdigit() else url
            link = f' <a href="{html.escape(url)}">{html.escape(label)}</a>'
        return (f'<li id="fn{n}">'
                f'<a class="back" href="#ref{n}">&#8593;</a> '
                f'<strong>{html.escape(row["stream"])}</strong> — '
                f'{html.escape(row["_note"])}{link}</li>')

    notes_html = (f'<ol class="notes">{"".join(note_item(r) for r in noted)}</ol>'
                  if noted else "")

    cells = "".join(
        "<tr>"
        f"<td>{html.escape(r['field'])}</td>"
        f"<td>{html.escape(r['stream'])}{note_marker(r)}</td>"
        f"<td>{html.escape(r['method'])}</td>"
        f"<td>{html.escape(r['target_systems'])}</td>"
        f"<td class='n'>{r['mapped']:,}/{r['total']:,}</td>"
        f"<td class='n'>{r['coverage_pct']:.1f}%</td>"
        + occurrence_cells(r) +
        f"<td class='bar-cell'>{stacked(r)}</td>"
        f"<td class='n'>{r['equivalent']:,}</td>"
        f"<td class='n'>{r['relatedto']:,}</td>"
        f"<td class='n'>{r['unmatched']:,}</td>"
        f"<td class='n'>{r['confidence_threshold']}</td>"
        f"<td class='n'>{r['confidence_median']}</td>"
        "</tr>"
        for r in rows)
    summary = totals(rows)
    # The share the deterministic streams hold, stated rather than asserted.
    algorithmic = sum(r["total"] for r in rows if r["method"] != "table")
    source_total = summary[0][2]
    summary_rows = "".join(
        f'<tr{" class=\'grand\'" if not i else ""}>'
        f"<td>{html.escape(label)}</td>"
        f"<td class='n'>{mapped:,}&thinsp;/&thinsp;{total:,}</td>"
        f"<td class='n'>{pct:.2f}%</td>"
        f"<td class='bar-cell'><div class=\"bar\">"
        f'<div class="seg" style="width:{pct:.2f}%;'
        f'background:{COLORS["equivalent"] if mapped == total else COLORS["relatedto"]}">'
        "</div></div></td></tr>"
        for i, (label, mapped, total, pct) in enumerate(summary))
    legend = "".join(
        f'<span class="key"><span class="swatch" '
        f'style="background:{color}"></span>{name}</span>'
        for name, color in COLORS.items())
    page = f"""<!doctype html>
<meta charset="utf-8">
<title>MIMIC mapping statistics, per stream</title>
<style>
  body {{ font: 14px/1.5 system-ui, sans-serif; margin: 2rem; color: #212529; }}
  table {{ border-collapse: collapse; width: 100%; }}
  th, td {{ padding: .35rem .6rem; border-bottom: 1px solid #dee2e6;
            text-align: left; white-space: nowrap; }}
  th {{ border-bottom: 2px solid #495057; }}
  th.n, td.n {{ text-align: right; font-variant-numeric: tabular-nums; }}
  td.bar-cell {{ min-width: 16rem; }}
  .bar {{ display: flex; height: 1rem; width: 100%; background: #f1f3f5;
          border-radius: 2px; overflow: hidden; }}
  .key {{ margin-right: 1.2rem; }}
  .swatch {{ display: inline-block; width: .8rem; height: .8rem;
             border-radius: 2px; margin-right: .35rem;
             vertical-align: -.05rem; }}
  p {{ color: #495057; max-width: 62rem; }}
  h2 {{ margin-top: 2.5rem; }}
  h2.first {{ margin-top: 1.5rem; }}
  table.summary {{ max-width: 44rem; }}
  table.summary td.bar-cell {{ min-width: 12rem; width: 40%; }}
  table.summary tr.grand td {{ font-weight: 600;
                               border-bottom: 2px solid #495057; }}
  table.summary tr:not(.grand) td:first-child {{ padding-left: 1.6rem;
                                                 color: #495057; }}
  table.cs th.rung, table.cs td.rung {{ background: #f8f9fa; }}
  /* Column-group boundary: settings | statuses | rungs | spread. Marked
     explicitly, because :first-of-type keys off the element type, not the
     class, and so never matched the first rung. */
  table.cs .sep {{ border-left: 2px solid #dee2e6; }}
  .rung-key {{ background: #f8f9fa; padding: 0 .2rem; }}
  tr.detail td {{ padding: 0 .6rem .6rem; border-bottom: 2px solid #495057; }}
  summary {{ cursor: pointer; color: #1971c2; padding: .3rem 0; }}
  ul.misses {{ margin: .2rem 0 .4rem; padding-left: 1.2rem;
               white-space: normal; }}
  ul.misses li {{ margin-bottom: .5rem; }}
  .conf {{ font-variant-numeric: tabular-nums; font-weight: 600;
           color: #c92a2a; margin-right: .3rem; }}
  .arrow {{ color: #868e96; }}
  .why {{ color: #868e96; font-size: .9em; }}
  code {{ background: #f1f3f5; padding: 0 .25rem; border-radius: 2px; }}
  .dim {{ color: #868e96; }}
  table .sep {{ border-left: 2px solid #dee2e6; }}
  h3 {{ margin: 2rem 0 .4rem; font-family: ui-monospace, monospace; }}
  table.pair {{ max-width: 46rem; margin-bottom: .6rem; }}
  table.pair td {{ border-bottom: none; padding: .1rem .6rem .1rem 0; }}
  table.pair td:first-child {{ color: #495057; width: 7rem; }}
  table.pair td.n {{ width: 9rem; }}
  p.legend {{ margin: .5rem 0 0; }}
  /* Stream footnotes. A coverage figure that is correct but reads as a failure
     needs its reason on the same page as the number, not in a commit message. */
  sup.fn {{ font-size: .7em; margin-left: .15rem; }}
  sup.fn a {{ color: #c92a2a; text-decoration: none; font-weight: 600; }}
  ol.notes {{ max-width: 52rem; margin: .8rem 0 0; padding-left: 1.4rem;
              color: #495057; font-size: .92em; }}
  ol.notes li {{ margin-bottom: .5rem; line-height: 1.5; }}
  ol.notes a.back {{ text-decoration: none; color: #868e96;
                     margin-right: .25rem; }}
  table.top {{ margin: .4rem 0 1rem; }}
  table.top td {{ padding: .2rem .6rem; }}
  /* A row the map cannot resolve, marked so the head of the distribution can be
     skimmed for holes rather than read cell by cell. */
  table.top tr.miss td {{ background: #fff5f5; }}
</style>
<h1>MIMIC mapping statistics, per stream</h1>
<p>Derived from the <code>by_stream</code> arrays of every
<code>&lt;field&gt;-report.json</code> in <code>output/</code>. Regenerated by
<code>build_statistics.py</code>; the committed CSV next to this file is the
citable version. {legend}</p>
<h2 class="first">Overall coverage</h2>
<p>Split by method, because the total is not a quality measure: the notation and
identity streams are mapped by deterministic transforms that cannot fail, and at
{algorithmic:,} of {source_total:,} source codes they set the total almost by
themselves. The <em>code-search</em> line is the one the rest of this page is
about.</p>
<table class="summary">
{summary_rows}
</table>
{occurrence_html}
<h2>Per stream</h2>
<table>
<tr><th>field</th><th>stream</th><th>method</th><th>targets</th>
<th class="n">mapped</th><th class="n">coverage</th>
{'<th class="n sep">occurrences</th><th class="n">occ coverage</th>' if weighted else ''}
<th>equivalence</th>
<th class="n">equivalent</th><th class="n">relatedto</th>
<th class="n">unmatched</th><th class="n">threshold</th>
<th class="n">median conf</th></tr>
{cells}
</table>
{notes_html}
{codesearch_table(codesearch)}
"""
    path = out_dir / "mapping-statistics.html"
    path.write_text(page)
    return path


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out-dir", type=Path, default=paths.OUTPUT,
                    help=f"where the reports are (default: {paths.OUTPUT})")
    ap.add_argument("--quiet", action="store_true",
                    help="write the files, skip the terminal table")
    ap.add_argument("--occurrences-dir", type=Path, default=paths.OCCURRENCES,
                    help=f"per-code occurrence counts, if extracted "
                         f"(default: {paths.OCCURRENCES})")
    ap.add_argument("--top-n", type=int, default=25,
                    help="how many of the most frequent codes per element the "
                         "HTML lists (default: 25)")
    args = ap.parse_args()

    reports = load_reports(args.out_dir)
    rows = flatten(reports)
    if not rows:
        sys.exit("no <field>-report.json with a by_stream array found — "
                 "run a builder first (make mappings)")

    # Optional: absent, every number below is the code-weighted one, as before.
    counts = occurrences.load(args.occurrences_dir)
    buckets, top, occurrence_html, buckets_path = [], {}, "", None
    if counts:
        stream_stats, buckets, top = occurrences.analyse(
            reports, counts, args.out_dir, args.top_n)
        apply_occurrences(rows, stream_stats)
        buckets_path = write_buckets_csv(buckets, args.out_dir)
        occurrence_html = occurrence_section(reports, counts, buckets, top)

    csv_path = write_csv(rows, args.out_dir)
    html_path = write_html(rows, codesearch_streams(reports), args.out_dir,
                           occurrence_html)
    if not args.quiet:
        print(f"== mapping statistics ({len(rows)} streams across "
              f"{len(reports)} fields) ==", file=sys.stderr)
        print_table(rows)
        if buckets:
            print_occurrences(buckets)
    written = ", ".join(p.name for p in
                        (csv_path, html_path, buckets_path) if p)
    print(f"  wrote {written}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
