#!/usr/bin/env python3
"""Render output/stream-report.json into the citable table and the HTML view.

Three views of the same numbers, all derived, none hand-edited:

    output/mapping-statistics.csv    one row per STREAM — the thesis
                                     interface. Committed.
    output/mapping-statistics.html   the same table plus stacked coverage
                                     bars and the per-element occurrence
                                     sections, for looking at. Gitignored: a
                                     pure derived view, regenerate any time.
    the terminal table               printed on every run unless --quiet.

This script computes no statistic. build_stream_reports.py resolves every
stream once and writes stream-report.json (plus occurrence-buckets.csv and the
per-stream worklists); this renders what that pass found. Offline,
deterministic, byte-identical from an unchanged report.

Rows are one per stream INCLUDING the synthesised `declared: false` ones — a
bound population no stream declares appears with method `unstreamed` at 0%,
which is what puts it in the totals' denominator. See build_stream_reports.py
and lib/streams.undeclared for why a table restricted to the declared streams
answers a question nobody asked.

The headline percentage per stream is `coverage_pct` = mapped ÷ used-in-data:
of the codes the warehouse actually records anywhere, how many resolve. The
full enumeration is carried beside it because either denominator alone
misleads — one hides that never-used codes were deliberately not attempted,
the other describes a job nobody attempted. When the occurrence artifacts are
absent the used-in-data columns and the percentage are EMPTY, never re-based
onto the enumeration: a blank says "nobody counted", a number would quietly
change what the column means.

Usage:
  uv run scripts/terminology-mapping/build_statistics.py [--quiet]
"""

import argparse
import csv
import html
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import occurrences, paths  # noqa: E402

# The flat scalar columns. The nested detail that does not flatten (confidence
# spread, constraint text, template, near-miss lists) stays in
# stream-report.json; the CSV carries what a thesis table cites. Status and
# reason columns are appended dynamically from whatever the data contains, so
# a new generator status never needs a code change here.
FIXED_COLUMNS = ["stream", "source_system", "method", "target_systems",
                 "consumed_by", "enumerated_total", "used_in_data",
                 "mapped", "mapped_used", "coverage_pct",
                 "occurrences_total", "occurrences_mapped",
                 "occurrence_coverage_pct", "codes_never_used",
                 "equivalent", "relatedto", "unmatched",
                 "confidence_threshold", "confidence_median"]

BAR_WIDTH = 20

# equivalent / relatedto / unmatched, in the HTML bars and nowhere else.
COLORS = {"equivalent": "#2f9e44", "relatedto": "#1971c2",
          "unmatched": "#adb5bd"}

# The occurrence buckets. Green for what $translate resolves, orange for a
# decision this repo made and will defend, purple for a stream blocked by
# something outside terminology, red for a code no bound ValueSet admits —
# which under a required binding is a defect, so it is the one colour that
# should never appear.
#
# The three backlogs share a grey RAMP rather than three unrelated hues,
# darkening as the gap deepens: a table that needs a row, then an element that
# needs a builder, then a population nobody has declared at all. They are one
# family of "not done yet" and should read as one, but they have three different
# fixes and must not be one bar.
BUCKET_COLORS = {occurrences.MAPPED: "#2f9e44",
                 occurrences.DECLINED: "#e8590c",
                 occurrences.BLOCKED: "#7048e8",
                 occurrences.UNRESOLVED: "#ced4da",
                 occurrences.NO_MAP: "#adb5bd",
                 occurrences.NO_STREAM: "#6c757d",
                 occurrences.NOT_IN_ENUMERATION: "#c92a2a"}

BUCKET_LABELS = {occurrences.MAPPED: "mapped",
                 occurrences.DECLINED: "declined",
                 occurrences.BLOCKED: "blocked upstream",
                 occurrences.UNRESOLVED: "unresolved in its stream",
                 occurrences.NO_MAP: "no map for this element",
                 occurrences.NO_STREAM: "no stream yet",
                 occurrences.NOT_IN_ENUMERATION: "in no bound ValueSet"}

# The code-search status split, in the order the second HTML table reads best.
STATUS_ORDER = ("ok", "below-threshold", "no-match", "extension")

# The grand total on its own says almost nothing: most source codes are ICD,
# mapped by a deterministic notation transform that cannot fail. The method
# split is what stops that number being read as a claim about mapping quality.
METHOD_ORDER = ("notation", "identity", "table", "declared", "unstreamed")
METHOD_LABELS = {
    "notation": "notation (ICD)",
    "table": "code-search / curated table",
    "declared": "declared for completeness",
    # Not a resolver — the absence of one. Last in the order and last in the
    # summary table, where it reads as what it is: bound codes with no stream,
    # sitting in the denominator at 0% until someone declares one. `declared`
    # above is nearly its opposite (a population enumerated on purpose so every
    # admitted code gets a stated non-answer), which is why neither borrows the
    # other's word.
    "unstreamed": "no stream declared",
}


def load_report(out_dir):
    path = out_dir / "stream-report.json"
    if not path.is_file():
        sys.exit(f"{path} not found — run build_stream_reports.py first "
                 f"(make mappings does)")
    return json.loads(path.read_text())


def flatten(blocks):
    """One flat dict per stream, in report (alphabetical) order."""
    rows = []
    for block in blocks:
        search = block.get("codesearch", {})
        confidence = search.get("confidence", {})
        row = {
            "stream": block["stream"],
            "source_system": block["source_system"],
            "method": block["method"],
            "target_systems": ";".join(block["target_systems"]),
            "consumed_by": ";".join(block["consumed_by"]),
            "enumerated_total": block["enumerated_total"],
            "used_in_data": block.get("used_in_data", ""),
            "mapped": block["mapped"],
            "mapped_used": block.get("mapped_used", ""),
            # EMPTY without the occurrence artifact, deliberately — see the
            # module docstring.
            "coverage_pct": block.get("coverage_pct", ""),
            "occurrences_total": block.get("occurrences_total", ""),
            "occurrences_mapped": block.get("occurrences_mapped", ""),
            "occurrence_coverage_pct": block.get("occurrence_coverage_pct", ""),
            "codes_never_used": block.get("codes_never_used", ""),
            "equivalent": block["by_equivalence"].get("equivalent", 0),
            "relatedto": block["by_equivalence"].get("relatedto", 0),
            "unmatched": block["by_equivalence"].get("unmatched", 0),
            "confidence_threshold": search.get("confidence_threshold", ""),
            "confidence_median": confidence.get("median", ""),
        }
        # Not CSV columns: prose does not belong in a citable table, and the
        # HTML is where a reader meets the number that needs it.
        if block.get("note"):
            row["_note"] = block["note"]
            row["_note_url"] = block.get("note_url", "")
        for rung, count in search.get("near_threshold", {}).items():
            row[f"within_{rung}"] = count
        for status, count in search.get("status", {}).items():
            row[f"status_{status}"] = count
        for reason, count in block["unmapped_by_reason"].items():
            row[f"reason_{reason}"] = count
        rows.append(row)
    return rows


def totals(rows):
    """[(label, mapped, total, pct)] — all streams, then one line per method.

    Over the used-in-data population when the occurrence artifacts supplied
    one, over the enumeration otherwise — mixing the two inside one sum would
    make the total mean nothing. Which denominator was used is in the label.
    """
    weighted = all(r["used_in_data"] != "" for r in rows)

    def line(label, group):
        if weighted:
            mapped = sum(r["mapped_used"] for r in group)
            total = sum(r["used_in_data"] for r in group)
        else:
            mapped = sum(r["mapped"] for r in group)
            total = sum(r["enumerated_total"] for r in group)
        if not total:
            return (label, mapped, total, 0.0)
        # Floored, not rounded: only a genuinely complete group may show 100.
        return (label, mapped, total, math.floor(10000 * mapped / total) / 100)

    methods = sorted({r["method"] for r in rows},
                     key=lambda m: (METHOD_ORDER.index(m)
                                    if m in METHOD_ORDER else len(METHOD_ORDER),
                                    m))
    suffix = " (used-in-data)" if weighted else " (enumerated)"
    return [line("all streams" + suffix, rows)] + [
        line(METHOD_LABELS.get(m, m), [r for r in rows if r["method"] == m])
        for m in methods]


def columns_for(rows):
    """The fixed columns, the within_ rungs in numeric order, then whatever
    status_/reason_ columns the data has."""
    present = {k for row in rows for k in row if not k.startswith("_")}
    fixed = list(FIXED_COLUMNS)
    dynamic = present - set(fixed)
    within = sorted((k for k in dynamic if k.startswith("within_")),
                    key=lambda k: float(k.split("_", 1)[1]))
    return fixed + within + sorted(dynamic - set(within))


def write_csv(rows, out_dir):
    path = out_dir / "mapping-statistics.csv"
    with open(path, "w", newline="") as fh:
        # extrasaction: columns_for() already drops the `_`-prefixed HTML-only
        # annotations from the header, and without this DictWriter refuses the
        # rows that carry them.
        writer = csv.DictWriter(fh, fieldnames=columns_for(rows), restval="",
                                extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    return path


def bar(row, width=BAR_WIDTH):
    """`██████████░░░░` — mapped share of a stream, for the terminal."""
    if row["used_in_data"] != "":
        mapped, total = row["mapped_used"], row["used_in_data"]
    else:
        mapped, total = row["mapped"], row["enumerated_total"]
    filled = round(width * mapped / total) if total else 0
    return "█" * filled + "░" * (width - filled)


def print_table(rows):
    width = max([len(r["stream"]) for r in rows] + [len("stream")])
    # Sized from the data: `unstreamed` is wider than the fixed 8 this used, and
    # one long method name pushing every later column out of alignment makes the
    # whole table unreadable.
    mwidth = max([len(r["method"]) for r in rows] + [len("method")])
    header = (f"  {'stream':{width}s} {'method':{mwidth}s} "
              f"{'mapped/used':>15s} {'':{BAR_WIDTH}s} {'cov':>7s} "
              f"{'enum':>7s}  {'equivalent':>10s} {'relatedto':>9s} "
              f"{'unmatched':>9s}")
    print(header, file=sys.stderr)
    print("  " + "-" * (len(header) - 2), file=sys.stderr)
    for r in rows:
        if r["used_in_data"] != "":
            pair = f"{r['mapped_used']:,}/{r['used_in_data']:,}"
            cov = f"{r['coverage_pct']:.2f}%"
        else:
            pair, cov = f"{r['mapped']:,}/-", ""
        print(f"  {r['stream']:{width}s} {r['method']:{mwidth}s} {pair:>15s} "
              f"{bar(r)} {cov:>7s} {r['enumerated_total']:>7,}  "
              f"{r['equivalent']:>10,} {r['relatedto']:>9,} "
              f"{r['unmatched']:>9,}", file=sys.stderr)
    print("  " + "-" * (len(header) - 2), file=sys.stderr)
    for i, (label, mapped, total, pct) in enumerate(totals(rows)):
        indent = "  " if i else ""
        print(f"  {indent}{label:{width + mwidth - len(indent)}s}"
              f"{mapped:>8,}/{total:<8,} {'':{BAR_WIDTH}s} {pct:>6.2f}%",
              file=sys.stderr)


def print_occurrences(buckets):
    """The element-level headline: what share of the DATA the maps resolve.

    TWO TABLES, split on occurrence_kind — a dictionary element's percentage
    is dictionary reachability, not data volume, and listing the two together
    invites a comparison that means nothing. See occurrences.element_summary.
    """
    summary = occurrences.element_summary(buckets)
    width = max([len(element) for element, *_ in summary] + [len("element")])

    def table(rows, heading, chance_label, note=None):
        if not rows:
            return
        any_blocked = any(achievable != total
                          for _, _, total, _, achievable, _, _ in rows)
        extra = f"{'achievable':>11s}" if any_blocked else ""
        print(f"\n  {heading:{width}s} {'occurrences mapped':>22s} "
              f"{'cov':>7s}  {chance_label:>15s}{extra}", file=sys.stderr)
        print("  " + "-" * (width + 49 + len(extra)), file=sys.stderr)
        for element, mapped, total, pct, achievable, achievable_pct, _ in rows:
            tail = ""
            if any_blocked:
                tail = (f"{achievable_pct:>10.2f}%" if achievable != total
                        else f"{'—':>11s}")
            print(f"  {element:{width}s} {mapped:>10,}/{total:<11,} "
                  f"{pct:>6.2f}%  {100 - pct:>14.2f}%{tail}", file=sys.stderr)
        if note:
            print(f"  {note}", file=sys.stderr)

    table([r for r in summary if r[6] == occurrences.EVENTS],
          "element", "unmapped chance")
    table([r for r in summary if r[6] == occurrences.DICTIONARY],
          "dictionary element", "unreachable",
          note="^ deduplicated resources: one row per distinct entry, so these "
               "are DICTIONARY counts, not data volume — not comparable with "
               "the table above. See reference-occurrences.csv for the "
               "volume-weighted view.")


def codesearch_table(blocks):
    """The second HTML table: what code-search proposed, what the gate refused.

    The coverage table above it can only say a code went unmapped. This says
    the proposal existed, scored 0.75, and was a broader concept — which is the
    difference between "no candidate" and "a candidate this threshold
    declined", and the only form in which "should the threshold be lower?" is a
    question a reader can actually answer.
    """
    streams = [b for b in blocks if b.get("codesearch")]
    if not streams:
        return ""
    statuses = {s for b in streams for s in b["codesearch"].get("status", {})}
    status_cols = ([s for s in STATUS_ORDER if s in statuses]
                   + sorted(statuses - set(STATUS_ORDER)))
    rungs = sorted({r for b in streams
                    for r in b["codesearch"].get("near_threshold", {})},
                   key=float)
    width = 2 + len(status_cols) + len(rungs) + 3

    def cls(index, base):
        return f"{base} sep" if index == 0 else base

    def misses(search):
        rejected = search.get("near_misses", [])
        if not rejected:
            return ""
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

    def row(block):
        search = block["codesearch"]
        confidence = search.get("confidence", {})
        spread = (f'{confidence["min"]:.2f} / {confidence["median"]:.2f} / '
                  f'{confidence["max"]:.2f}' if confidence else "")
        return (
            "<tr>"
            f"<td>{html.escape(block['stream'])}</td>"
            f"<td class='n'>{search.get('confidence_threshold', '')}</td>"
            + "".join(f"<td class='{cls(i, 'n')}'>"
                      f"{search.get('status', {}).get(s, 0):,}</td>"
                      for i, s in enumerate(status_cols))
            + "".join(f"<td class='{cls(i, 'n rung')}'>"
                      f"{search.get('near_threshold', {}).get(r, '')}</td>"
                      for i, r in enumerate(rungs))
            + f"<td class='n sep'>{spread}</td>"
            "</tr>") + misses(search)

    head = ("<tr><th>stream</th><th class='n'>threshold</th>"
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
{"".join(row(b) for b in streams)}
</table>
"""


def occurrence_section(elements, buckets, counts):
    """Per bound element: the buckets, and the head of the distribution with
    each code's status. This is where the two percentages diverging becomes
    legible: read down the most frequent codes and see which of them nothing
    resolves."""
    if not buckets:
        return ""
    rows_by_element = {}
    for row in buckets:
        rows_by_element.setdefault(row["element"], []).append(row)
    by_element = {e["element"]: e for e in elements}

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
        if entry["bucket"] in (occurrences.UNRESOLVED, occurrences.NO_MAP,
                               occurrences.NO_STREAM):
            # The source system names WHICH population is behind the gap, which
            # is the first thing anyone reading a backlog row wants.
            return (f'{label} <span class="dim">'
                    f'{html.escape(entry["system"].rsplit("/", 1)[-1])}</span>')
        return label

    def top_table(section):
        entries = section.get("top", [])
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
        if achievable == total:
            return ""
        blocked = total - achievable
        return (f'<tr><td>&nbsp;&nbsp;achievable</td>'
                f'<td class="n">{mapped:,}&thinsp;/&thinsp;{achievable:,}</td>'
                f'<td class="n">{achievable_pct:.2f}%</td>'
                f'<td class="dim">excluding {blocked:,} occurrence(s) in '
                f'streams blocked upstream, which no code system could have '
                f'covered</td></tr>')

    blocks = []
    for (element, mapped, total, pct, achievable, achievable_pct,
         kind) in occurrences.element_summary(buckets):
        section = by_element.get(element, {})
        legend = "".join(
            f'<span class="key"><span class="swatch" '
            f'style="background:{BUCKET_COLORS[b]}"></span>'
            f"{BUCKET_LABELS[b]}</span>" for b in occurrences.BUCKETS)
        if not section.get("has_conceptmap"):
            map_note = ('<tr><td>map</td><td class="n">&mdash;</td>'
                        '<td class="n"></td><td class="dim">no ConceptMap for '
                        'this element yet, so nothing here can resolve — but '
                        'the buckets still separate the codes a stream already '
                        'answers for (<em>no map for this element</em>) from '
                        'the ones no stream declares (<em>no stream yet</em>), '
                        'because those are two different jobs</td></tr>')
        else:
            map_note = ""
        if kind == occurrences.DICTIONARY:
            occ_label = "dictionary entries"
            occ_note = ('<span class="dim">&rarr; deduplicated resource: one '
                        'row per distinct entry, so this is how much of the '
                        'DICTIONARY <code>$translate</code> resolves, not how '
                        'much data. The volume-weighted figure lives in '
                        '<code>reference-occurrences.csv</code>, which counts '
                        'these codes once per referring resource.</span>')
        else:
            occ_label = "occurrences"
            occ_note = (f'<span class="dim">&rarr; a data point here has a '
                        f'<strong>{100 - pct:.2f}%</strong> chance of carrying '
                        f'an unresolvable code</span>')
        blocks.append(f"""
<h3>{html.escape(element)}{' <span class="dim">(dictionary)</span>'
                           if kind == occurrences.DICTIONARY else ''}</h3>
<table class="pair">
{map_note}
<tr><td>{occ_label}</td><td class="n">{mapped:,}&thinsp;/&thinsp;{total:,}</td>
<td class="n">{pct:.2f}%</td>
<td>{occ_note}</td></tr>
{achievable_row(mapped, total, achievable, achievable_pct)}
</table>
{stacked(rows_by_element.get(element, []), total) if total else ""}
<p class="legend">{legend}</p>
{top_table(section)}
""")

    summary = counts.summary if counts else {}
    tables = ", ".join(
        f"{name} v{info['delta_version']}"
        for name, info in sorted(summary.get("tables", {}).items())
        if "delta_version" in info)
    return f"""
<h2>Occurrence-weighted coverage, per bound element</h2>
<p>Every figure in the stream table counts each source code once. These count
it as often as it occurs in the warehouse, which is the difference between
&ldquo;how much of the dictionary did we map&rdquo; and &ldquo;how likely is a
data point to carry a code <code>$translate</code> cannot resolve&rdquo;. The
two diverging is the finding: a stream can map three quarters of its codes and
a small fraction of its rows.</p>
<p><em>declined</em> is a stream that considered a code and said no, with its
reason in <code>unmapped-&lt;stream&gt;.csv</code> — the only bucket here that is
a judgement rather than a gap. The three greys are all backlog, kept apart
because they have three different fixes: <em>unresolved in its stream</em> wants
a row added to a curated table (<code>make generate-all-tables</code>);
<em>no map for this element</em> wants a <code>build_*_cm_vs.py</code>, the
answers already existing in a stream that no ConceptMap here serves; <em>no
stream yet</em> wants a declaration in <code>lib/streams.py</code>, and is the
only one where nothing is mapped anywhere. <em>in no bound ValueSet</em> is a
code the data carries that no bound ValueSet admits, and under a required
binding that is a defect, so it should be empty.</p>
<p class="dim">Counted on {html.escape(summary.get('host', '?'))} at
{html.escape(summary.get('generated', '?'))} from
<code>{html.escape(summary.get('warehouse', '?'))}</code>{f' ({html.escape(tables)})' if tables else ''}.
See <code>occurrences/README.md</code>.</p>
{"".join(blocks)}
"""


def write_html(rows, blocks, elements, buckets, counts, out_dir):
    """Self-contained table + stacked bars. A view, not a deliverable."""
    weighted = any(r["used_in_data"] != "" for r in rows)

    def stacked(row):
        total = row["enumerated_total"]
        if not total:
            return ""
        parts = []
        for key in ("equivalent", "relatedto", "unmatched"):
            share = 100 * row[key] / total
            if share:
                parts.append(
                    f'<div class="seg" style="width:{share:.2f}%;'
                    f'background:{COLORS[key]}" title="{key}: {row[key]:,}">'
                    f'</div>')
        return f'<div class="bar">{"".join(parts)}</div>'

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
            tail = url.rstrip("/").rsplit("/", 1)[-1]
            label = f"#{tail}" if tail.isdigit() else url
            link = f' <a href="{html.escape(url)}">{html.escape(label)}</a>'
        return (f'<li id="fn{n}">'
                f'<a class="back" href="#ref{n}">&#8593;</a> '
                f'<strong>{html.escape(row["stream"])}</strong> — '
                f'{html.escape(row["_note"])}{link}</li>')

    notes_html = (f'<ol class="notes">{"".join(note_item(r) for r in noted)}</ol>'
                  if noted else "")

    def used_cells(r):
        if not weighted:
            return ""
        if r["used_in_data"] == "":
            return ("<td class='n sep'></td><td class='n'></td>"
                    "<td class='n'></td>")
        return (f"<td class='n sep'>{r['mapped_used']:,}"
                f"&thinsp;/&thinsp;{r['used_in_data']:,}</td>"
                f"<td class='n'>{r['coverage_pct']:.2f}%</td>"
                f"<td class='n'>{r['occurrence_coverage_pct']:.2f}%</td>")

    cells = "".join(
        "<tr>"
        f"<td>{html.escape(r['stream'])}{note_marker(r)}</td>"
        f"<td>{html.escape(r['method'])}</td>"
        f"<td>{html.escape(r['target_systems'])}</td>"
        f"<td>{html.escape(r['consumed_by'])}</td>"
        f"<td class='n'>{r['mapped']:,}/{r['enumerated_total']:,}</td>"
        + used_cells(r) +
        f"<td class='bar-cell'>{stacked(r)}</td>"
        f"<td class='n'>{r['equivalent']:,}</td>"
        f"<td class='n'>{r['relatedto']:,}</td>"
        f"<td class='n'>{r['unmatched']:,}</td>"
        f"<td class='n'>{r['confidence_threshold']}</td>"
        f"<td class='n'>{r['confidence_median']}</td>"
        "</tr>"
        for r in rows)
    summary = totals(rows)
    # notation + identity only — the two resolvers the sentence below names.
    # Not `!= "table"`, which would quietly fold `declared` and `unstreamed`
    # populations into a count described as deterministic transforms.
    algorithmic = sum(r["enumerated_total"] for r in rows
                      if r["method"] in ("notation", "identity"))
    source_total = sum(r["enumerated_total"] for r in rows)
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
    occurrence_html = occurrence_section(elements, buckets, counts)
    used_head = ('<th class="n sep">mapped/used</th><th class="n">cov</th>'
                 '<th class="n">occ cov</th>' if weighted else '')
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
  td.bar-cell {{ min-width: 12rem; }}
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
  table.pair td:first-child {{ color: #495057; width: 9rem; }}
  table.pair td.n {{ width: 9rem; }}
  p.legend {{ margin: .5rem 0 0; }}
  sup.fn {{ font-size: .7em; margin-left: .15rem; }}
  sup.fn a {{ color: #c92a2a; text-decoration: none; font-weight: 600; }}
  ol.notes {{ max-width: 52rem; margin: .8rem 0 0; padding-left: 1.4rem;
              color: #495057; font-size: .92em; }}
  ol.notes li {{ margin-bottom: .5rem; line-height: 1.5; }}
  ol.notes a.back {{ text-decoration: none; color: #868e96;
                     margin-right: .25rem; }}
  table.top {{ margin: .4rem 0 1rem; }}
  table.top td {{ padding: .2rem .6rem; }}
  table.top tr.miss td {{ background: #fff5f5; }}
</style>
<h1>MIMIC mapping statistics, per stream</h1>
<p>Derived from <code>output/stream-report.json</code>, written by
<code>build_stream_reports.py</code> — one row per stream, however many
ConceptMaps consume it. The committed CSV next to this file is the citable
version. <em>mapped/used</em> scores each stream over the codes the warehouse
actually records anywhere; the enumeration column is the full dictionary the
stream declares. {legend}</p>
<h2 class="first">Overall coverage</h2>
<p>Split by method, because the total is not a quality measure: the notation
and identity streams are mapped by deterministic transforms that cannot fail,
and at {algorithmic:,} of {source_total:,} enumerated source codes they set the
total almost by themselves. The <em>code-search / curated table</em> line is
the one the rest of this page is about.</p>
<table class="summary">
{summary_rows}
</table>
<h2>Per stream</h2>
<table>
<tr><th>stream</th><th>method</th><th>targets</th><th>consumed by</th>
<th class="n">mapped/enum</th>
{used_head}
<th>equivalence</th>
<th class="n">equivalent</th><th class="n">relatedto</th>
<th class="n">unmatched</th><th class="n">threshold</th>
<th class="n">median conf</th></tr>
{cells}
</table>
{notes_html}
{occurrence_html}
{codesearch_table(blocks)}
"""
    path = out_dir / "mapping-statistics.html"
    path.write_text(page)
    return path


def load_buckets(out_dir):
    path = out_dir / "occurrence-buckets.csv"
    if not path.is_file():
        return []
    with open(path, newline="") as fh:
        return [{**row, "codes": int(row["codes"]),
                 "occurrences": int(row["occurrences"]),
                 "share_pct": float(row["share_pct"])}
                for row in csv.DictReader(fh)]


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out-dir", type=Path, default=paths.OUTPUT,
                    help=f"where stream-report.json is (default: {paths.OUTPUT})")
    ap.add_argument("--occurrences-dir", type=Path, default=paths.OCCURRENCES)
    ap.add_argument("--quiet", action="store_true",
                    help="write the files, skip the terminal table")
    args = ap.parse_args()

    report = load_report(args.out_dir)
    blocks = report["streams"]
    rows = flatten(blocks)
    buckets = load_buckets(args.out_dir)
    counts = occurrences.load(args.occurrences_dir)

    csv_path = write_csv(rows, args.out_dir)
    html_path = write_html(rows, blocks, report.get("elements", []), buckets,
                           counts, args.out_dir)
    if not args.quiet:
        print(f"== mapping statistics ({len(rows)} streams) ==",
              file=sys.stderr)
        print_table(rows)
        if buckets:
            print_occurrences(buckets)
    print(f"  wrote {csv_path.name}, {html_path.name}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
