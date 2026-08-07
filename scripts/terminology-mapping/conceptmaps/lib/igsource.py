"""Reading source codes out of the IG's own CodeSystems and ValueSets.

Source codes are ALWAYS read from the IG, never written out in a builder. A
literal would drift from the profiles the map serves, and nothing would notice.
Every stage that needs to know "what is the source side" comes through
source_concepts, so no two of them can hold a private copy of it.

That last sentence is also why `observed_only` lives here rather than in a
builder. A source may declare that only the codes the warehouse actually USES
are worth resolving; the split between "in the enumeration" and "in the data"
then has to be made in exactly one place, because build_groups and
verify_mappings both ask this module what the source side is. Two copies of the
rule would let the builder and the verifier disagree about the population — the
same drift that motivated one builder per field.

Note what `observed_only` does NOT do: it does not hide anything. The codes it
sets aside are still declared in the ConceptMap as `unmatched` elements with a
comment saying they were never observed, so a consumer translating one gets told
so rather than getting silence. All it changes is the COVERAGE DENOMINATOR — a
stream is scored on the population it set out to map.
"""

import json
import sys

from common import occurrences

from .canonical import FSH_GENERATED, RESOURCES


def resource_path(source):
    """The IG resource a source's codes come from.

    `file` names a MIMIC CodeSystem in input/resources/: the ValueSets bound
    over those are bare composes carrying no enumerated concepts, so the
    CodeSystem is the only enumeration there is.

    `valueset_file` names an IG ValueSet that does enumerate its concepts. Tried
    in input/resources/ first, then fsh-generated/resources/ for the
    FSH-authored ones.
    """
    if "file" in source:
        return RESOURCES / source["file"]
    name = source["valueset_file"]
    for directory in (RESOURCES, FSH_GENERATED):
        if (directory / name).is_file():
            return directory / name
    return FSH_GENERATED / name


def source_concepts(source):
    """(code, display) for every code a source contributes.

    A missing CodeSystem is a warning because input/resources/ ships with the
    IG and its absence means a partial checkout. A missing ValueSet is fatal:
    it is FSH-authored, so it is simply not built yet, and skipping it would
    quietly emit a map that drops every code in that population.
    """
    path = resource_path(source)
    if not path.is_file():
        if "valueset_file" in source:
            sys.exit(f"  {path} not found. It is FSH-authored — run `sushi .` "
                     f"first. Continuing without it would silently drop every "
                     f"{source['system']} code from the map.")
        print(f"  {path.name}: MISSING from input/resources/ — skipped",
              file=sys.stderr)
        return
    resource = json.loads(path.read_text())
    if resource.get("resourceType") == "ValueSet":
        for include in resource.get("compose", {}).get("include", []):
            if include.get("system") != source["system"]:
                continue
            for concept in include.get("concept", []):
                yield concept["code"], concept.get("display", "")
    else:
        for concept in resource.get("concept", []):
            yield concept["code"], concept.get("display", "")


def partition_observed(source, element, concepts):
    """Split `concepts` into (observed, never_observed) for an `observed_only` source.

    A source without the flag is returned whole — this is a no-op for every
    population that does not declare it, so no existing artefact moves.

    Every failure here is FATAL rather than a fall-back to the full enumeration.
    Silently mapping the whole thing would still produce a green build, a
    plausible ConceptMap and a coverage number computed over a different
    denominator than the one the stream declares — which is precisely the
    "looks right, means something else" outcome this repo refuses everywhere
    else. If the counts cannot be read, the right answer is to stop.
    """
    if not source.get("observed_only"):
        return concepts, []
    if not element:
        sys.exit("  observed_only needs the bound element to key the counts on, "
                 "and none was passed. Refusing to fall back to the full "
                 "enumeration: that would silently change the population the "
                 "stream is scored against.")

    counts = occurrences.load()
    if counts is None:
        sys.exit(f"  {source['system']} declares observed_only, but the "
                 f"occurrence counts are missing or fail their sha256 check. "
                 f"See occurrences/README.md. Refusing to guess at which codes "
                 f"the data uses.")
    if not counts.has(element):
        sys.exit(f"  {source['system']} declares observed_only for {element}, "
                 f"but that element was never extracted. A code absent from an "
                 f"extracted element occurs zero times; an element that was "
                 f"never counted says nothing at all, and the two must not be "
                 f"confused.")

    observed, never = [], []
    for code, display in concepts:
        (observed if counts.get(element, source["system"], code) else
         never).append((code, display))
    return observed, never


def source_paths(sources):
    """Every IG resource and table a declaration reads. Used for dating."""
    paths = [p for s in sources if (p := resource_path(s)).is_file()]
    # Mapping tables are inputs too: editing one is a real change to the map,
    # and the resource date has to move with it.
    paths += [s["table"] for s in sources
              if "table" in s and s["table"].is_file()]
    return paths
