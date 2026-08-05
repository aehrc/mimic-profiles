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
            for status, count in search.get("status", {}).items():
                row[f"status_{status}"] = count
            for reason, count in stream["unmapped_by_reason"].items():
                row[f"reason_{reason}"] = count
            rows.append(row)
    return rows


def columns_for(rows):
    """Fixed columns plus whatever status_/reason_ columns the data has."""
    dynamic = sorted({k for row in rows for k in row} - set(FIXED_COLUMNS))
    return FIXED_COLUMNS + dynamic


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


def write_html(rows, out_dir):
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
  td.n {{ text-align: right; font-variant-numeric: tabular-nums; }}
  td.bar-cell {{ min-width: 16rem; }}
  .bar {{ display: flex; height: 1rem; width: 100%; background: #f1f3f5;
          border-radius: 2px; overflow: hidden; }}
  .key {{ margin-right: 1.2rem; }}
  .swatch {{ display: inline-block; width: .8rem; height: .8rem;
             border-radius: 2px; margin-right: .35rem;
             vertical-align: -.05rem; }}
  p {{ color: #495057; }}
</style>
<h1>MIMIC mapping statistics, per stream</h1>
<p>Derived from the <code>by_stream</code> arrays of every
<code>&lt;field&gt;-report.json</code> in <code>output/</code>. Regenerated by
<code>build_statistics.py</code>; the committed CSV next to this file is the
citable version. {legend}</p>
<table>
<tr><th>field</th><th>stream</th><th>method</th><th>targets</th>
<th>mapped</th><th>coverage</th><th>equivalence</th><th>equivalent</th>
<th>relatedto</th><th>unmatched</th><th>threshold</th><th>median conf</th></tr>
{cells}
</table>
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
    html_path = write_html(rows, args.out_dir)
    if not args.quiet:
        print(f"== mapping statistics ({len(rows)} streams across "
              f"{len(reports)} fields) ==", file=sys.stderr)
        print_table(rows)
    print(f"  wrote {csv_path.name}, {html_path.name}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
