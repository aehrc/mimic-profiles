"""Which builders exist, and which populations a shared table has to cover.

Two consumers, and they need the same answer for different reasons:

  verify/verify_mappings.py   the populations to check, found by globbing rather
                              than by a registry — one builder script per bound
                              element, each owning its own declaration, so there
                              is nothing central to keep in step.
  a table generator           the population to GENERATE, which is not the same
                              as one field's population once a table is shared.

The second is why this module exists rather than the glob staying inside the
verifier. A mapping table is keyed by its SOURCE CodeSystem, not by the field
that reads it, and `mimic-medication-name` is bound to two elements:
MedicationRequest.medication[x] observes 2,888 of its codes and
MedicationAdministration.medication[x] observes 3,620, overlapping in 2,600. Two
tables over those overlapping sets is a way for this repo to publish two
different RxNorm concepts for one MIMIC drug name, in two ConceptMaps, with
nothing to notice — see lib/curated.py on what a table is checked against.

One table, generated over the UNION, removes that by construction. The union has
to be discovered rather than declared: a hand-kept list of "fields sharing this
table" is exactly the registry the glob exists to avoid, and the failure mode is
silent — a stream added to a second field, its codes missing from the table, and
every one of them landing in the unmapped CSV as `no-row-in-curated-table` while
the build stays green.
"""

import importlib
import sys
from pathlib import Path

from .igsource import partition_observed, source_concepts

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


def table_streams(table_path):
    """[(field, element, source)] for every stream declaring this table.

    Sorted by field, so a generator's population and its log are ordered by
    something stable rather than by filesystem order.
    """
    return [(field, meta["element"], source)
            for field, sources, meta in discover()
            for source in sources
            if source.get("table") == table_path]


def table_population(table_path):
    """{code: display} — the union of every population this table serves.

    Each stream contributes its own codes through the one reader, narrowed by
    its own `observed_only` against its own element, so a shared table covers
    exactly what the fields between them map and nothing else. Codes shared
    between fields appear once; their display comes from the IG and is the same
    string either way, which is what lib/curated.py's drift check rests on.

    A table no builder declares is fatal rather than an empty population: it
    means the generator writes a file nothing reads, which is the same class of
    silent uselessness as a stream whose codes never reach a table.
    """
    streams = table_streams(table_path)
    if not streams:
        sys.exit(f"  no builder declares {table_path.name}. A generator writes "
                 f"the table some SOURCES entry reads; add the entry first, or "
                 f"this run produces a file nothing will ever load.")

    population = {}
    for field, element, source in streams:
        observed, _ = partition_observed(
            source, element, list(source_concepts(source)))
        population.update(observed)
    return population


def describe_population(table_path):
    """Per-field counts for the union, for a generator to print before it runs.

    A shared table's row count matches no single field's population, so a run
    that only printed the total would look wrong to anyone holding one field's
    numbers in their head.
    """
    lines = []
    for field, element, source in table_streams(table_path):
        observed, _ = partition_observed(
            source, element, list(source_concepts(source)))
        lines.append((field, element, len(observed)))
    return lines
