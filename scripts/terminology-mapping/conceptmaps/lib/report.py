"""What a build found: the unmapped CSV and the per-population report.

The report is the deliverable alongside the artefacts. Its core keys are the same
for every population so one coverage table can be assembled across all of them;
`extras` is free-form so a population can record what only it knows (the ICU
table's code-search confidence spread, say) without every other builder having
to invent the same field.

The unmapped CSV keeps its full schema. Until this refactor two scripts wrote
this file with different columns — the ConceptMap builder wrote the rich version
and the ValueSet builder overwrote it with a five-column one, so `expected_code`,
`expected_system` and `comment` were lost on every full build. `comment` is
where a table's per-code reason for declining lives, which made it the most
valuable column and the one that never survived.
"""

import csv
import json
from collections import Counter

UNMAPPED_COLUMNS = ["field", "source_system", "mimic_code", "mimic_display",
                    "expected_code", "expected_system", "reason", "comment"]


def write_unmapped(field_key, unmapped, out_dir):
    """One CSV per population, always written — an empty file is a meaningful
    result, not a missing one."""
    path = out_dir / f"unmapped-{field_key}.csv"
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
                 by_stream=None, extras=None):
    """<field>-report.json: the common core, plus whatever else this population
    has to say.

    `by_stream` is the per-SOURCES-entry breakdown from assemble.build_groups
    (enriched by lib/stats.py) — the same numbers as the core, but per stream
    rather than per map, which the map itself cannot yield because streams
    sharing a (source, target) pair merge into one R4 group. It is what
    build_statistics.py flattens into output/mapping-statistics.csv.
    """
    report = {
        "field": field_key,
        "element": element,
        "conceptmap": conceptmap["url"],
        "valueset": valueset["url"],
        "version": conceptmap["version"],
        "date": conceptmap["date"],
        **core(conceptmap, unmapped),
        "by_stream": by_stream or [],
        "target_valueset_codes": sum(
            len(i["concept"]) for i in valueset["compose"]["include"]),
        "extras": extras or {},
    }
    path = out_dir / f"{field_key}-report.json"
    path.write_text(json.dumps(report, indent=1) + "\n")
    return path, report
