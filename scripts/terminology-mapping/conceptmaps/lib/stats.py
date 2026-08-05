"""Per-stream statistics: enriching the tallies build_groups collected.

Tier A — coverage, equivalence split, unmapped-by-reason — is counted in
assemble.build_groups, the only place stream identity still exists. This module
adds Tier B, the generation-method numbers a thesis evaluation actually cites,
for the table-backed streams only:

  from the committed table's provenance columns (codesearch_confidence,
  codesearch_status — the columns lib/curated.py reads and discards):
      the confidence spread and the status breakdown, i.e. how many proposals
      were accepted, rejected below the threshold, dropped by the gate, or
      never offered;

  from the committed generation log (output/<stream>-generation-log.json):
      the settings that produced the table — constraint, template, threshold.

Both inputs are committed files, so `make mappings` stays offline and a build
from unchanged inputs stays byte-identical. A stream with no table (identity,
notation) simply carries no `codesearch` block; a table with no log gets the
provenance numbers and no settings — the log is optional, never required.
"""

import csv
import json
import statistics


def _log_path(table_path, out_dir):
    """conceptmaps/<stream>-<system>.csv -> output/<stream>-generation-log.json

    The naming rule (see the mapping-stream skill): a table is named for its
    stream plus its target system — d-items-snomed, micro-susc-loinc,
    <stream>-standard for mixed targets — and its log drops that last token.
    """
    base = table_path.stem.rsplit("-", 1)[0]
    return out_dir / f"{base}-generation-log.json"


def _provenance(table_path):
    """Confidence spread and status counts from a table's provenance columns."""
    with open(table_path, newline="") as fh:
        rows = list(csv.DictReader(fh))
    statuses = {}
    confidences = []
    for row in rows:
        status = (row.get("codesearch_status") or "").strip()
        if status:
            statuses[status] = statuses.get(status, 0) + 1
        conf = (row.get("codesearch_confidence") or "").strip()
        if conf:
            confidences.append(float(conf))
    prov = {}
    if statuses:
        prov["status"] = dict(sorted(statuses.items()))
    if confidences:
        prov["confidence"] = {
            "min": round(min(confidences), 3),
            "median": round(statistics.median(confidences), 3),
            "mean": round(statistics.mean(confidences), 3),
            "max": round(max(confidences), 3),
        }
    return prov


def _settings(log_path):
    """The generation settings, read from the committed log if there is one."""
    if not log_path.is_file():
        return {}
    log = json.loads(log_path.read_text())
    settings = {}
    # d-items logs say constraint_ecl, LOINC logs constraint_vcl; the report
    # does not care which language the constraint was written in.
    for key in ("constraint_ecl", "constraint_vcl"):
        if key in log:
            settings["constraint"] = log[key]
            break
    for key in ("template", "confidence_threshold"):
        if key in log:
            settings[key] = log[key]
    return settings


def enrich(streams, sources, out_dir):
    """Add the codesearch block to every table-backed stream, in place."""
    for stream, source in zip(streams, sources):
        if "table" not in source:
            continue
        block = _provenance(source["table"])
        block.update(_settings(_log_path(source["table"], out_dir)))
        if block:
            stream["codesearch"] = block
    return streams
