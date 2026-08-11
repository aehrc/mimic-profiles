"""Which builders exist, and which population a table generator has to cover.

Two consumers, and they need the same answer for different reasons:

  verify/verify_mappings.py   the maps to check, found by globbing rather than
                              by a registry — one builder script per bound
                              element, each owning its own declaration, so
                              there is nothing central to keep in step.
  a table generator           the population to GENERATE for its stream.

A table belongs to a STREAM (lib/streams.py), and a stream is one population
however many ConceptMaps consume it — so a generator's population is simply the
stream's enumeration narrowed to the codes the warehouse actually uses, read
from the committed occurrence counts. The old version discovered a per-element
union by importing every builder; the registry makes that walk unnecessary,
because there is no per-element narrowing left to union over.
"""

import importlib
import sys
from pathlib import Path

from common import occurrences

from . import streams

BUILDERS = Path(__file__).resolve().parents[1]


def discover():
    """(field, sources, meta) for every builder script, sorted by field."""
    found = []
    for path in sorted(BUILDERS.glob("build_*_cm_vs.py")):
        module = importlib.import_module(f"conceptmaps.{path.stem}")
        missing = [a for a in ("FIELD", "SOURCES", "META")
                   if not hasattr(module, a)]
        if missing:
            sys.exit(f"{path.name} declares no {', '.join(missing)} — every "
                     f"builder must expose FIELD, SOURCES and META so this "
                     f"check can find its artefacts.")
        found.append((module.FIELD, module.SOURCES, module.META))
    if not found:
        sys.exit(f"no build_*_cm_vs.py in {BUILDERS}")
    return sorted(found)


def consumers():
    """{stream name: [field, ...]} — which maps consume each stream.

    Discovered from the builders rather than declared: a hand-kept consumer
    list is the registry the builder glob exists to avoid, and its failure
    mode is silent.
    """
    consuming = {}
    for field, sources, _ in discover():
        for source in sources:
            name = source.get("stream")
            if name:
                consuming.setdefault(name, []).append(field)
    return consuming


def _require_counts():
    counts = occurrences.load()
    if counts is None:
        sys.exit("  the occurrence counts are missing or fail their sha256 "
                 "check (see occurrences/README.md). A generator's population "
                 "is the codes the warehouse actually uses, and without the "
                 "counts there is nothing to narrow by — refusing to guess.")
    return counts


def table_population(table_path):
    """{code: display} — what the generator for this table has to cover.

    The stream's enumeration narrowed to the codes observed on ANY bound
    element. Narrowed at all because the alternative is sending thousands of
    never-used labels through a model-backed service to populate rows no
    $translate call can reach; narrowed by the UNION because the stream is one
    population however many elements consume it, and a per-element table is a
    way to publish two different concepts for one MIMIC code.
    """
    stream = streams.stream_for_table(table_path)
    observed = occurrences.observed_anywhere(counts=_require_counts())
    return {code: display
            for code, display in streams.enumeration(stream)
            if (stream["system"], code) in observed}


def describe_population(table_path):
    """[(element, count)] per element observing this stream's codes.

    For a generator to print before it runs: a stream's population matches no
    single element's numbers, so a run that only printed the total would look
    wrong to anyone holding one element's count in their head.
    """
    stream = streams.stream_for_table(table_path)
    counts = _require_counts()
    enumerated = dict(streams.enumeration(stream))
    lines = []
    for element in sorted(counts.by_element):
        n = sum(1 for (system, code) in counts.by_element[element]
                if system == stream["system"] and code in enumerated)
        if n:
            lines.append((element, n))
    return lines
