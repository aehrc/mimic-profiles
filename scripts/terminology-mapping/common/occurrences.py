"""Weighting the mapping statistics by how much data each code carries.

Coverage over CODES answers "how much of the dictionary did we map". This module
adds coverage over OCCURRENCES, which answers "how likely is a data point I meet
to carry a code $translate cannot resolve" — and the two diverging is the
finding: 76% of the datetimeevents items mapped but 14% of the rows means the
items nurses touch every shift are the unmapped ones.

Everything here is offline. The counts come from a committed artifact extracted
once on the HPC node (occurrences/code-occurrences.csv, see its README); this
module joins them to the field reports and the IG's own enumerations, and
recomputes no mapping.

Three things are produced, in ascending order of how much they claim:

  per stream   the report's coverage_pct, re-weighted. Same numerator and
               denominator as the code count, each code counted as often as it
               occurs.

  per element  every occurrence of the element partitioned five ways —
               MAPPED, DECLINED (a built stream considered it and said no, with
               a reason on record), BLOCKED (a built stream that maps nothing
               because the obstacle is outside terminology — an ETL or
               modelling defect), NO_STREAM (a bound population nobody has
               built yet: labevents, chartevents), NOT_IN_ENUMERATION (a code in
               the data that no bound ValueSet admits, which under a required
               binding is an ETL or binding defect). The last three are kept
               apart from DECLINED on purpose: only DECLINED is a judgement this
               repo would defend, and reporting a 1,622-code backlog or a
               mis-modelled column as if it were one would misrepresent both.

               BLOCKED is also what makes the element's coverage reportable two
               ways — against every occurrence, and against the occurrences a
               code system could ever have covered. See element_summary.

  top N        the most frequent codes with their status, which is where the
               divergence between the two percentages becomes readable: you look
               down the head of the distribution and see which heavy hitters are
               unmapped.

The stream -> code-set join reads the IG resource named in each stream's
`source_file` (added in lib/assemble.py). Attribution is by code membership, not
by source system: mimic-d-items serves three populations, so only the
enumerations can say which stream a given d-item belongs to.
"""

import csv
import hashlib
import json
import sys
from collections import defaultdict

from common import paths

CSV_NAME = "code-occurrences.csv"
SUMMARY_NAME = "occurrence-summary.json"
REGISTRY_NAME = "elements.json"

MAPPED = "mapped"
DECLINED = "declined"
# A stream that is built and complete but maps nothing, because the reason its
# codes cannot be mapped sits OUTSIDE terminology — an ETL or modelling defect
# this repo cannot fix from here. Split out of DECLINED deliberately: that
# bucket means "a stream considered this code and said no", which is a
# judgement about terminology and the only one this repo would defend. A code
# that was never a candidate for a code system is a different fact, and folding
# the two together would both overstate what was judged and make an element's
# coverage look like a mapping failure when it is a data-model one.
BLOCKED = "blocked-upstream"
# Kept in step with lib/assemble.py by hand rather than imported: this module is
# read by the HPC-node side too, which has no conceptmaps/ package on its path.
NOT_OBSERVED = "not-observed-in-data"
NO_STREAM = "no-stream-yet"
NOT_IN_ENUMERATION = "not-in-enumeration"
BUCKETS = (MAPPED, DECLINED, BLOCKED, NO_STREAM, NOT_IN_ENUMERATION)

# The IG resources every enumeration is read from. Both directories, because the
# MIMIC CodeSystems ship in input/resources/ while the FSH-authored ValueSets
# are built into fsh-generated/ — the same split lib/igsource.py handles.
_REPO = paths.ROOT.parent.parent
_RESOURCE_DIRS = (_REPO / "input" / "resources",
                  _REPO / "fsh-generated" / "resources")


def warn(msg):
    print(f"  occurrences: {msg}", file=sys.stderr)


# --------------------------------------------------------------------------- #
# The artifact.
# --------------------------------------------------------------------------- #

class Counts:
    """The committed occurrence counts, keyed (element, system, code)."""

    def __init__(self, rows, summary, registry):
        self.summary = summary
        self.registry = {e["element"]: e for e in registry["elements"]}
        self.by_element = defaultdict(dict)     # element -> (sys, code) -> n
        self.displays = defaultdict(dict)       # element -> (sys, code) -> str
        for row in rows:
            key = (row["system"], row["code"])
            self.by_element[row["element"]][key] = int(row["occurrences"])
            self.displays[row["element"]][key] = row["display"]

    def has(self, element):
        """Was this element extracted at all?

        A code absent from an EXTRACTED element occurs zero times — the
        extraction is data-driven and therefore complete for what it covered. An
        element that was never extracted is a different thing entirely, and must
        not be reported as an element with no data.
        """
        return element in self.by_element

    def total(self, element):
        return sum(self.by_element[element].values())

    def get(self, element, system, code):
        return self.by_element[element].get((system, code), 0)


def load(occ_dir=None):
    """The committed counts, or None if they have not been extracted yet.

    The CSV is verified against the sha256 in the summary. A hand-edited or
    half-transferred file must not silently become a number in a thesis table,
    and the alternative — trusting whatever bytes are on disk — has no way to
    tell the difference.
    """
    occ_dir = occ_dir or paths.OCCURRENCES
    csv_path = occ_dir / CSV_NAME
    summary_path = occ_dir / SUMMARY_NAME
    registry_path = occ_dir / REGISTRY_NAME
    if not csv_path.is_file():
        return None
    if not summary_path.is_file():
        warn(f"{CSV_NAME} present but {SUMMARY_NAME} is not — skipping the "
             f"occurrence view, because nothing identifies what was counted")
        return None

    summary = json.loads(summary_path.read_text())
    expected = summary.get("csv_sha256")
    actual = hashlib.sha256(csv_path.read_bytes()).hexdigest()
    if expected and expected != actual:
        warn(f"{CSV_NAME} does not match csv_sha256 in {SUMMARY_NAME} — "
             f"skipping the occurrence view.\n"
             f"    expected {expected}\n    actual   {actual}")
        return None

    with open(csv_path, newline="") as fh:
        rows = list(csv.DictReader(fh))
    registry = json.loads(registry_path.read_text())
    return Counts(rows, summary, registry)


# --------------------------------------------------------------------------- #
# Reading enumerations out of the IG.
# --------------------------------------------------------------------------- #

def _resource_index():
    """{canonical url: resource} over both IG resource directories."""
    index = {}
    for directory in _RESOURCE_DIRS:
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("*.json")):
            try:
                resource = json.loads(path.read_text())
            except ValueError:
                continue
            if isinstance(resource, dict) and "url" in resource:
                index.setdefault(resource["url"], resource)
    return index


def _codesystem_concepts(resource, prefix=""):
    """(code, display) for a CodeSystem, descending nested concepts.

    MIMIC's are flat, but a hierarchy would otherwise be silently truncated to
    its top level, which reads as a coverage gap that isn't one.
    """
    for concept in resource.get("concept", []):
        yield concept["code"], concept.get("display", "")
        yield from _codesystem_concepts(concept, prefix)


def expand(url, index, seen=None):
    """{(system, code): display} for a ValueSet, offline.

    Handles the three shapes this IG uses: a grouping ValueSet referencing
    others, an enumerating include (`system` + `concept`), and a bare include
    naming a system alone — which means the whole CodeSystem, so the CodeSystem
    is the enumeration. Anything else (a filter, an exclude) is warned about
    rather than silently approximated: a wrong enumeration produces plausible
    percentages with nothing to catch them.
    """
    seen = seen if seen is not None else set()
    if url in seen:
        return {}
    seen.add(url)

    resource = index.get(url)
    if resource is None:
        warn(f"{url} not found in input/resources/ or fsh-generated/ — "
             f"treating its codes as outside every enumeration")
        return {}
    if resource.get("resourceType") == "CodeSystem":
        return {(resource["url"], code): display
                for code, display in _codesystem_concepts(resource)}

    concepts = {}
    compose = resource.get("compose", {})
    if compose.get("exclude"):
        warn(f"{url} has compose.exclude, which is not applied here")
    for include in compose.get("include", []):
        for nested in include.get("valueSet", []):
            concepts.update(expand(nested, index, seen))
        system = include.get("system")
        if not system:
            continue
        if include.get("filter"):
            warn(f"{url} filters {system}, which is not applied here")
        if include.get("concept"):
            for concept in include["concept"]:
                concepts[(system, concept["code"])] = concept.get("display", "")
        else:
            # Bare include: the whole CodeSystem. Resolve it by system url,
            # which is also its canonical url for every system in this IG.
            system_resource = index.get(system)
            if system_resource is None:
                warn(f"{url} includes all of {system}, which is not in the IG "
                     f"resources — its codes cannot be enumerated")
                continue
            for code, display in _codesystem_concepts(system_resource):
                concepts[(system, code)] = display
    return concepts


def _stream_codes(source_file, source_system, index):
    """{(system, code): display} for one stream, from the file it named.

    `source_file` is a filename rather than a url, so it is resolved against the
    same two directories the index is built from. Restricted to the stream's own
    source system: a ValueSet may include several, and a stream is one.
    """
    for directory in _RESOURCE_DIRS:
        path = directory / source_file
        if path.is_file():
            resource = json.loads(path.read_text())
            if resource.get("resourceType") == "CodeSystem":
                return {(resource["url"], code): display
                        for code, display in _codesystem_concepts(resource)}
            return {key: display
                    for key, display in expand(resource["url"], index).items()
                    if key[0] == source_system}
    warn(f"{source_file} not found — its stream gets no occurrence numbers")
    return {}


# --------------------------------------------------------------------------- #
# Declined codes and mapping targets, from the files the builders wrote.
# --------------------------------------------------------------------------- #

def _declined(field_key, out_dir):
    """{(system, code)} the builders considered and deliberately left unmapped.

    NOT every row of the CSV. A stream declaring `observed_only` also writes a
    row for each code the bound ValueSet admits but the data never carries, so
    that a consumer meeting one is told the assumption rather than met with
    silence — see lib/assemble.py NOT_OBSERVED. Those were never considered and
    never declined: counting them here would report a code nobody looked at as a
    judgement this repo would defend, which is precisely the distinction the
    DECLINED bucket exists to preserve.

    They cannot move the occurrence arithmetic either way, since a never-observed
    code occurs zero times by construction. What they would corrupt is the code
    COUNT and the cross-check against the report, and the check is worth keeping
    honest: it is what catches a builder and its CSV disagreeing.
    """
    path = out_dir / f"unmapped-{field_key}.csv"
    if not path.is_file():
        return set()
    with open(path, newline="") as fh:
        return {(row["source_system"], row["mimic_code"])
                for row in csv.DictReader(fh)
                if row.get("reason") != NOT_OBSERVED}


def _targets(report, out_dir):
    """{(source system, code): "target_code"} from the field's ConceptMap.

    Only so the top-N table can name what a mapped code maps to. Absent or
    unreadable, the status column simply says "mapped".
    """
    url = report.get("conceptmap", "")
    path = out_dir / f"ConceptMap-{url.rsplit('/', 1)[-1]}.json"
    if not path.is_file():
        return {}
    conceptmap = json.loads(path.read_text())
    targets = {}
    for group in conceptmap.get("group", []):
        for element in group.get("element", []):
            for concept in element.get("target", []):
                if concept.get("code"):
                    targets[(group["source"], element["code"])] = concept["code"]
    return targets


# --------------------------------------------------------------------------- #
# The three views.
# --------------------------------------------------------------------------- #

def analyse(reports, counts, out_dir, top_n=25):
    """(stream_stats, buckets, top) — everything build_statistics.py renders.

    stream_stats  {(field, stream): {...}} to merge into the per-stream rows
    buckets       [{element, bucket, codes, occurrences, share_pct}]
    top           {element: [{rank, code, display, occurrences, ...}]}
    """
    index = _resource_index()
    stream_stats = {}
    buckets = []
    top = {}

    # Every element that was counted, not every element that has a map. An
    # element with no ConceptMap yet — Specimen.type, both medication[x] — is
    # the case worth reporting: its buckets are entirely NO_STREAM, which states
    # the size of the backlog in rows. Skipping it would leave the biggest
    # unmapped populations invisible in the one view meant to rank them.
    by_element = {r["element"]: r for r in reports}
    for element in sorted(counts.by_element):
        report = by_element.get(element)
        field = report["field"] if report else None

        declined_codes = _declined(field, out_dir) if report else set()
        element_total = counts.total(element)

        # Per stream, and at the same time the element-level mapped/declined
        # sets — both are the same walk over the streams' enumerations.
        mapped_keys, declined_keys, blocked_keys = set(), set(), set()
        for stream in (report["by_stream"] if report else []):
            source_file = stream.get("source_file")
            if not source_file:
                warn(f"{field}/{stream['stream']} has no source_file — rebuild "
                     f"the field's report (see lib/assemble.py)")
                continue
            codes = _stream_codes(source_file, stream["source_system"], index)
            in_stream_declined = {k for k in codes if k in declined_codes}
            in_stream_mapped = set(codes) - in_stream_declined
            if stream.get("blocked_upstream"):
                # Its unmapped codes are blocked, not declined. Anything it DID
                # map still counts as mapped — the flag is about why the gap
                # exists, not a licence to ignore the stream's successes.
                blocked_keys |= in_stream_declined
            else:
                declined_keys |= in_stream_declined
            mapped_keys |= in_stream_mapped

            # The report counted the same thing from the other direction; a
            # disagreement means the enumeration and the map have drifted apart.
            if len(in_stream_declined) != stream["unmapped"]:
                warn(f"{field}/{stream['stream']}: {len(in_stream_declined)} "
                     f"declined codes found in the enumeration but the report "
                     f"says {stream['unmapped']}")

            occ = {k: counts.get(element, *k) for k in codes}
            total = sum(occ.values())
            mapped = sum(occ[k] for k in in_stream_mapped)
            stream_stats[(field, stream["stream"])] = {
                "occurrences_total": total,
                "occurrences_mapped": mapped,
                # Floored, not rounded, for the reason build_statistics.totals
                # floors: only a genuinely complete stream may display 100.
                "occurrence_coverage_pct": (int(10000 * mapped / total) / 100
                                            if total else 0.0),
                "codes_never_used": sum(1 for k in codes if not occ[k]),
                "declined_never_used": sum(1 for k in in_stream_declined
                                           if not occ[k]),
            }

        # Bucket every occurrence of the element.
        bound = {}
        for url in counts.registry.get(element, {}).get("bound_valuesets", []):
            bound.update(expand(url, index))

        tallies = {bucket: {"codes": 0, "occurrences": 0} for bucket in BUCKETS}
        classified = {}
        for key, n in counts.by_element[element].items():
            if key in mapped_keys:
                bucket = MAPPED
            elif key in blocked_keys:
                bucket = BLOCKED
            elif key in declined_keys:
                bucket = DECLINED
            elif key in bound:
                bucket = NO_STREAM
            else:
                bucket = NOT_IN_ENUMERATION
            classified[key] = bucket
            tallies[bucket]["codes"] += 1
            tallies[bucket]["occurrences"] += n

        for bucket in BUCKETS:
            tally = tallies[bucket]
            buckets.append({
                "element": element,
                "bucket": bucket,
                "codes": tally["codes"],
                "occurrences": tally["occurrences"],
                "share_pct": (round(100 * tally["occurrences"] / element_total, 2)
                              if element_total else 0.0),
            })

        # The head of the distribution, with what happened to each code.
        targets = _targets(report, out_dir) if report else {}
        ranked = sorted(counts.by_element[element].items(),
                        key=lambda kv: (-kv[1], kv[0]))[:top_n]
        top[element] = [{
            "rank": rank,
            "system": system,
            "code": code,
            "display": (counts.displays[element].get((system, code))
                        or bound.get((system, code), "")),
            "occurrences": n,
            "share_pct": (round(100 * n / element_total, 2)
                          if element_total else 0.0),
            "bucket": classified[(system, code)],
            "target": targets.get((system, code), ""),
        } for rank, ((system, code), n) in enumerate(ranked, 1)]

    return stream_stats, buckets, top


def element_summary(buckets):
    """Per element: mapped, total, and the coverage figure reported TWO ways.

    [(element, mapped, total, pct, achievable_total, achievable_pct)]

    The complement of the mapped share is the number this view exists for: the
    chance that a data point encountered in this element carries a code
    $translate cannot resolve.

    Why two denominators. An element can bind a population that terminology
    cannot serve at all, because the codes are not the kind of thing the target
    code system names — MedicationRequest.medication[x] carries 167,144
    occurrences of `IV therapy` and `TPN`, which are order flags rather than
    substances. Against every occurrence, that element reads 88.19%; against
    what a code system could ever have covered, 96.77%. Reporting only the
    first blames the mapping for a data-model defect; reporting only the second
    hides 8.9% of the element's traffic behind a denominator quietly chosen to
    flatter it. Both, always, and `blocked-upstream` is exactly the difference
    between them — so the second figure can never be moved except by declaring
    a stream blocked, in the builder, where a reviewer sees it.

    When nothing is blocked the two are identical, which is the common case and
    costs a reader nothing.
    """
    per_element = defaultdict(lambda: {"mapped": 0, "total": 0, "blocked": 0})
    for row in buckets:
        entry = per_element[row["element"]]
        entry["total"] += row["occurrences"]
        if row["bucket"] == MAPPED:
            entry["mapped"] += row["occurrences"]
        elif row["bucket"] == BLOCKED:
            entry["blocked"] += row["occurrences"]

    def pct(mapped, total):
        # Floored, not rounded: only a genuinely complete element may show 100.
        return int(10000 * mapped / total) / 100 if total else 0.0

    out = []
    for element, value in sorted(per_element.items()):
        achievable = value["total"] - value["blocked"]
        out.append((element, value["mapped"], value["total"],
                    pct(value["mapped"], value["total"]),
                    achievable, pct(value["mapped"], achievable)))
    return out
