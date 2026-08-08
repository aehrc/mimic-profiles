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
      the settings that produced the table — constraint, template, threshold;

  from both together, the near-threshold view: how far below the gate the
      rejected proposals actually landed, and what they were. A count of
      rejections says the gate fired; it does not say whether it fired on
      nonsense or on relevant-but-broader concepts, which is the only version
      of the question worth putting in front of a reader.

Both inputs are committed files, so `make mappings` stays offline and a build
from unchanged inputs stays byte-identical. A stream with no table (identity,
notation) simply carries no `codesearch` block; a table with no log gets the
provenance numbers and no settings — the log is optional, never required, and
without its threshold the near-threshold view is simply absent rather than
computed against a guessed gate.
"""

import csv
import json
import statistics

from .igsource import partition_observed, source_concepts

# Cumulative and inclusive: a proposal counts in every rung at least as wide as
# its distance below the gate, so `0.1` reads as "what a threshold lowered by
# 0.1 would have accepted" — including a proposal sitting exactly on that new
# line, which such a threshold does accept.
NEAR_RUNGS = (0.05, 0.1, 0.2, 0.3, 0.4)

# Confidences and thresholds are two-decimal, but float subtraction is not:
# 0.8 - 0.75 is 0.05000000000000004, which loses every proposal sitting exactly
# on a rung — 13 of them on datetimeevents alone.
GAP_PRECISION = 4


def _log_path(table_path, out_dir):
    """conceptmaps/<stream>-<system>.csv -> output/<stream>-generation-log.json

    The naming rule (see the mapping-stream skill): a table is named for its
    stream plus its target system — d-items-snomed, micro-susc-loinc,
    <stream>-standard for mixed targets — and its log drops that last token.
    """
    base = table_path.stem.rsplit("-", 1)[0]
    return out_dir / f"{base}-generation-log.json"


def _read(table_path):
    with open(table_path, newline="") as fh:
        return list(csv.DictReader(fh))


def _provenance(rows):
    """Confidence spread and status counts from a table's provenance columns."""
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


def _near_threshold(rows, threshold):
    """How far below the gate the rejected proposals landed, and what they were.

    `near_threshold` is the cumulative count per rung; `near_misses` is every
    rejection, listed. There is no cutoff on the list on purpose: a view whose
    argument is that 0.8 is an arbitrary line has no business drawing a second
    arbitrary line to decide which rejections a reader may inspect. It is ~113
    entries across every stream, and the ones furthest below the gate are
    exactly where a reader goes to confirm it is not uniformly over-strict.
    """
    if threshold is None:
        return {}
    counts = {_rung_key(rung): 0 for rung in NEAR_RUNGS}
    misses = []
    for row in rows:
        if (row.get("codesearch_status") or "").strip() != "below-threshold":
            continue
        confidence = (row.get("codesearch_confidence") or "").strip()
        if not confidence:
            continue
        gap = round(threshold - float(confidence), GAP_PRECISION)
        for rung in NEAR_RUNGS:
            if gap <= rung:
                counts[_rung_key(rung)] += 1
        misses.append({
            "mimic_code": row.get("mimic_code", ""),
            "mimic_display": row.get("mimic_display", ""),
            "proposed_code": row.get("codesearch_target", ""),
            "proposed_display": row.get("codesearch_display", ""),
            "confidence": float(confidence),
            "gap": gap,
            "reasoning": row.get("codesearch_reasoning", ""),
        })
    misses.sort(key=lambda m: (m["gap"], m["mimic_display"]))
    return {"near_threshold": counts, "near_misses": misses}


def _rung_key(rung):
    """0.05 -> "0.05", 0.1 -> "0.1" — a JSON object key, and the suffix of the
    `within_<rung>` column build_statistics.py flattens it into."""
    return f"{rung:g}"


def enrich(streams, sources, out_dir, element):
    """Add the codesearch block to every table-backed stream, in place.

    Rows are filtered to the stream's OWN population first. A table shared
    between two bound elements holds rows for both, and a confidence spread or
    status breakdown computed over all of them would describe neither field:
    `mimic-medication-name` alone would report MedicationRequest's numbers over
    MedicationAdministration's rows. For a table serving one field the filter is
    a no-op and every committed report stays byte-identical.
    """
    for stream, source in zip(streams, sources):
        if "table" not in source:
            continue
        population, _ = partition_observed(
            source, element, list(source_concepts(source)))
        mine = {code for code, _ in population}
        rows = [r for r in _read(source["table"]) if r["mimic_code"] in mine]
        settings = _settings(_log_path(source["table"], out_dir))
        block = _provenance(rows)
        block.update(settings)
        block.update(_near_threshold(rows, settings.get("confidence_threshold")))
        if block:
            stream["codesearch"] = block
    return streams
