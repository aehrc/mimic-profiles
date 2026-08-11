"""What a build found: the per-stream worklists and the per-map report.

The worklist is per STREAM, because its audience is whoever fixes a mapping
table and tables are per stream — the per-field worklists this replaces listed
the same shared-table gaps once per consuming element. One CSV per stream,
always written by build_stream_reports.py — an empty file is a meaningful
result, not a missing one.

The per-map report (<field>-report.json) carries what is genuinely per
ConceptMap: canonicals, element, totals over the map's groups. The per-stream
numbers that used to ride along as `by_stream` live in output/stream-report.json
now, written once per stream instead of once per consuming map.
"""

import csv
import json
from collections import Counter

UNMAPPED_COLUMNS = ["stream", "source_system", "mimic_code", "mimic_display",
                    "expected_code", "expected_system", "reason", "comment"]


def write_unmapped(stream_name, unmapped, out_dir):
    """One CSV per stream — the worklist, with each gap's reason and comment."""
    path = out_dir / f"unmapped-{stream_name}.csv"
    with open(path, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=UNMAPPED_COLUMNS, restval="")
        writer.writeheader()
        writer.writerows(unmapped)
    return path


def core(conceptmap, unmapped):
    """The keys every population reports, whatever its method was."""
    mapped, by_target, by_equivalence, by_source = 0, Counter(), Counter(), Counter()
    for group in conceptmap["group"]:
        for element in group["element"]:
            for concept in element.get("target", []):
                equivalence = concept.get("equivalence", "")
                by_equivalence[equivalence] += 1
                if concept.get("code"):
                    mapped += 1
                    by_source[group["source"]] += 1
                    key = group["target"]
                    if group.get("targetVersion"):
                        key += f"|{group['targetVersion']}"
                    by_target[key] += 1
    return {
        "source_total": mapped + len(unmapped),
        "mapped": mapped,
        "unmapped": len(unmapped),
        "by_source": [{"system": s, "mapped": n}
                      for s, n in sorted(by_source.items())],
        # Mappings, not distinct target codes: several source codes can share a
        # target, so this exceeds target_valueset_codes wherever they do.
        "by_target_system": [{"system": s, "mappings": n}
                             for s, n in sorted(by_target.items())],
        "by_equivalence": dict(sorted(by_equivalence.items())),
        "unmapped_by_reason": dict(sorted(Counter(
            r["reason"] for r in unmapped).items())),
    }


def write_report(field_key, element, conceptmap, valueset, unmapped, out_dir,
                 streams=None, extras=None):
    """<field>-report.json: the common core, plus whatever else this map has to
    say. `streams` names the streams the map consumed, so upload.py's ONLY=
    resolution and a reader can walk from a map to its streams' reports."""
    report = {
        "field": field_key,
        "element": element,
        "conceptmap": conceptmap["url"],
        "valueset": valueset["url"],
        "version": conceptmap["version"],
        "date": conceptmap["date"],
        "streams": streams or [],
        **core(conceptmap, unmapped),
        "target_valueset_codes": sum(
            len(i["concept"]) for i in valueset["compose"]["include"]),
        "extras": extras or {},
    }
    path = out_dir / f"{field_key}-report.json"
    path.write_text(json.dumps(report, indent=1) + "\n")
    return path, report
