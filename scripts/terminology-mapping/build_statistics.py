#!/usr/bin/env python3
"""Flatten every <field>-report.json into one per-stream statistics table.

Three views of the same numbers, all derived, none hand-edited:

    output/mapping-statistics.csv    one row per stream across every field —
                                     the thesis interface. Committed.
    output/mapping-statistics.html   the same table plus stacked coverage
                                     bars, for looking at. Gitignored: a pure
                                     derived view, regenerate any time.
    the terminal table               printed on every run unless --quiet.

This script recomputes nothing. It reads the `by_stream` arrays the builders
wrote (see lib/report.py) and flattens them, which is what keeps a partial run
honest: `make observation` refreshes observation-report.json, every other
field's report is the committed one, and the CSV assembled from all of them is
complete and current. Offline, deterministic, byte-identical from unchanged
reports — `make mappings && git diff --exit-code` stays a valid test.

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

from common import paths

# The flat scalar columns. The nested Tier-B detail that does not flatten
# (confidence spread, constraint text, template) stays in the reports'
# by_stream entries; the CSV carries what a thesis table cites. Status and
# reason columns are appended dynamically from whatever the data contains, so
# a new generator status never needs a code change here.
FIXED_COLUMNS = ["field", "element", "stream", "source_system", "method",
                 "target_systems", "total", "mapped", "unmapped",
                 "coverage_pct", "equivalent", "relatedto", "unmatched",
                 "confidence_threshold", "confidence_median"]

BAR_WIDTH = 20

# equivalent / relatedto / unmatched, in the HTML bars and nowhere else.
COLORS = {"equivalent": "#2f9e44", "relatedto": "#1971c2",
          "unmatched": "#adb5bd"}

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
    """Fixed columns, the within_ rungs in numeric order, then whatever
    status_/reason_ columns the data has."""
    dynamic = {k for row in rows for k in row} - set(FIXED_COLUMNS)
    within = sorted((k for k in dynamic if k.startswith("within_")),
                    key=lambda k: float(k.split("_", 1)[1]))
    return FIXED_COLUMNS + within + sorted(dynamic - set(within))


def write_csv(rows, out_dir):
    path = out_dir / "mapping-statistics.csv"
    with open(path, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns_for(rows), restval="")
        writer.writeheader()
        writer.writerows(rows)
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


def write_html(rows, codesearch, out_dir):
    """Self-contained table + stacked bars. A view, not a deliverable."""
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

    cells = "".join(
        "<tr>"
        f"<td>{html.escape(r['field'])}</td>"
        f"<td>{html.escape(r['stream'])}</td>"
        f"<td>{html.escape(r['method'])}</td>"
        f"<td>{html.escape(r['target_systems'])}</td>"
        f"<td class='n'>{r['mapped']:,}/{r['total']:,}</td>"
        f"<td class='n'>{r['coverage_pct']:.1f}%</td>"
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
<h2>Per stream</h2>
<table>
<tr><th>field</th><th>stream</th><th>method</th><th>targets</th>
<th class="n">mapped</th><th class="n">coverage</th><th>equivalence</th>
<th class="n">equivalent</th><th class="n">relatedto</th>
<th class="n">unmatched</th><th class="n">threshold</th>
<th class="n">median conf</th></tr>
{cells}
</table>
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
    args = ap.parse_args()

    reports = load_reports(args.out_dir)
    rows = flatten(reports)
    if not rows:
        sys.exit("no <field>-report.json with a by_stream array found — "
                 "run a builder first (make mappings)")

    csv_path = write_csv(rows, args.out_dir)
    html_path = write_html(rows, codesearch_streams(reports), args.out_dir)
    if not args.quiet:
        print(f"== mapping statistics ({len(rows)} streams across "
              f"{len(reports)} fields) ==", file=sys.stderr)
        print_table(rows)
    print(f"  wrote {csv_path.name}, {html_path.name}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
