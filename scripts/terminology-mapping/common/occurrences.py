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

  per element  every occurrence of the element partitioned seven ways —
               MAPPED, DECLINED (a built stream considered it and said no, with
               a reason on record), BLOCKED (a built stream that maps nothing
               because the obstacle is outside terminology — an ETL or
               modelling defect), UNRESOLVED (a declared stream owns the code
               but has no answer for it yet), NO_MAP (a stream resolved it, but
               this element has no ConceptMap to serve the answer), NO_STREAM (a
               bound population NO stream declares at all), NOT_IN_ENUMERATION
               (a code in the data that no bound ValueSet admits, which under a
               required binding is an ETL or binding defect). Everything after
               DECLINED is kept apart from it on purpose: only DECLINED is a
               judgement this repo would defend, and reporting a backlog or a
               mis-modelled column as if it were one would misrepresent both.

               The three backlog buckets are split because they have three
               different fixes and one used to hide inside another: before the
               split, MedicationDispense.medication[x] reported 14,240,367
               occurrences as `no-stream-yet` when only 1,550,601 of them had no
               stream — the other 12.7M were streams that resolve perfectly,
               waiting on a ConceptMap for that element. Extending a table, ADDING
               a builder and DECLARING a stream are three different jobs, so they
               are three different buckets.

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
# A declared stream owns this code and has no answer for it yet — no row in its
# curated table, or absent from every built release. A backlog INSIDE a stream,
# whose fix is extending that stream's table or building the missing release.
UNRESOLVED = "unresolved-in-stream"
# A stream resolved this code, but the element carrying it has no ConceptMap, so
# no $translate call can reach the answer. The fix is a builder, not a mapping:
# the dictionary work is already done. Split out of NO_STREAM because folding
# the two together made an element with no builder look like an element with no
# mappings, which is the opposite of the truth for four of the five populations
# behind MedicationDispense.medication[x].
NO_MAP = "no-map-for-element"
# No stream declares this population AT ALL. The deepest of the three backlogs
# and the only one invisible to the per-stream view until build_stream_reports
# synthesises a row for it — see lib/streams.undeclared().
NO_STREAM = "no-stream-yet"
# The unmapped-CSV reason written for a population no stream declares
# (lib/assemble.py NOT_BUILT). Deliberately the same string as the NO_STREAM
# bucket: the worklist row and the bucket state one fact, and giving it two
# names would invite a reader to think they differ.
NOT_BUILT = NO_STREAM
# A shared mapping table, generated for the codes one element observes, has no
# row for a code a WIDER element admits. Named separately from the other
# UNRESOLVED reason because it names its own fix — extend that table's
# generation population — but it is the same coverage fact, so it buckets the
# same way.
NO_TABLE_ROW = "no-row-in-curated-table"
NOT_IN_ENUMERATION = "not-in-enumeration"
# Ordered by how deep the gap is, which is the order the stacked bars read in.
BUCKETS = (MAPPED, DECLINED, BLOCKED, UNRESOLVED, NO_MAP, NO_STREAM,
           NOT_IN_ENUMERATION)

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


def registry(occ_dir=None):
    """{element: entry} from elements.json alone, counts or no counts.

    Separate from load() because the two answer different questions. load() is
    "what does the data contain", and is legitimately absent before an extraction
    run. This is "what elements are bound and to what", which is a property of
    the profiles and is available offline, always — so a builder may rely on it
    without acquiring a dependency on the HPC job having been run.
    """
    path = (occ_dir or paths.OCCURRENCES) / REGISTRY_NAME
    if not path.is_file():
        return {}
    return {e["element"]: e
            for e in json.loads(path.read_text())["elements"]}


def valueset_systems(url, index=None, seen=None):
    """Every code system a ValueSet's compose reaches, without enumerating codes.

    Deliberately not expand(): the caller wants to know WHICH ELEMENTS could
    carry a system, and for that a system-level answer is both sufficient and
    orders of magnitude cheaper than pulling 20,288 concepts out of five
    CodeSystems to then throw the codes away.
    """
    index = index if index is not None else _resource_index()
    seen = seen if seen is not None else set()
    if url in seen:
        return set()
    seen.add(url)
    resource = index.get(url)
    if resource is None:
        return set()
    if resource.get("resourceType") == "CodeSystem":
        return {resource["url"]}
    systems = set()
    for include in resource.get("compose", {}).get("include", []):
        if include.get("system"):
            systems.add(include["system"])
        for nested in include.get("valueSet", []):
            systems |= valueset_systems(nested, index, seen)
    return systems


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


REFERENCE_NAME = "reference-occurrences.csv"


def observed_anywhere(occ_dir=None, counts=None):
    """{(system, code)} observed on ANY bound element, or None without counts.

    The union-level fact the resolvers report `not-observed-in-data` against
    (see lib/assemble.py). None — not the empty set — when the artifact is
    absent: "nothing was ever counted" and "the count found nothing" are
    different statements, and only the second may change a reason.
    """
    counts = counts if counts is not None else load(occ_dir)
    if counts is None:
        return None
    return {key for per_element in counts.by_element.values()
            for key in per_element}


def reference_counts(occ_dir=None):
    """{(system, code): referring resources} from reference-occurrences.csv.

    The volume figure for codes reached through a Reference: each code counted
    once per REFERRING resource, which is what makes it comparable with the
    event elements' counts. This is the number a dictionary-kind element
    (Medication, deduplicated to one resource per drug tuple) contributes to a
    stream's occurrence totals — its own counts are dictionary size, and
    summing those with event counts would be a category error.

    Empty when the file is absent; callers must then leave dictionary volume
    out rather than substituting the dictionary counts.
    """
    path = (occ_dir or paths.OCCURRENCES) / REFERENCE_NAME
    if not path.is_file():
        return {}
    totals = defaultdict(int)
    with open(path, newline="") as fh:
        for row in csv.DictReader(fh):
            totals[(row["system"], row["code"])] += int(row["resources"])
    return dict(totals)


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


EVENTS = "events"
DICTIONARY = "dictionary"


def element_kind(element, reg=None):
    """`events` or `dictionary` for one element — see elements.json `keys`.

    An event element's occurrence count is data volume: one coding is one thing
    that happened to a patient. A dictionary element's is the size of the
    dictionary, because the resource is deduplicated — MIMIC mints one Medication
    per distinct drug tuple, so a code recorded on ten thousand prescriptions
    still occurs about once here.

    The distinction is not cosmetic. print_occurrences exists to answer "how
    likely is a data point to carry a code $translate cannot resolve", and a
    dictionary element cannot answer that question at all: putting its row in
    that table invites a reader to compare 29% of a drug list with 68% of
    461 million observations as though the two were the same measurement.
    """
    reg = reg if reg is not None else registry()
    return reg.get(element, {}).get("occurrence_kind", EVENTS)


def element_summary(buckets):
    """Per element: mapped, total, and the coverage figure reported TWO ways.

    [(element, mapped, total, pct, achievable_total, achievable_pct, kind)]

    `kind` is carried through rather than looked up by the caller so that every
    renderer of this table gets the events/dictionary split whether or not it
    remembered to ask for it. A row that silently claims to be volume is the one
    failure mode worth designing against here.

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

    reg = registry()
    out = []
    for element, value in sorted(per_element.items()):
        achievable = value["total"] - value["blocked"]
        out.append((element, value["mapped"], value["total"],
                    pct(value["mapped"], value["total"]),
                    achievable, pct(value["mapped"], achievable),
                    element_kind(element, reg)))
    return out
