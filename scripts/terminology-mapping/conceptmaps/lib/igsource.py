"""Reading source codes out of the IG's own CodeSystems and ValueSets.

Source codes are ALWAYS read from the IG, never written out in a builder. A
literal would drift from the profiles the map serves, and nothing would notice.
Every stage that needs to know "what is the source side" comes through
source_concepts, so no two of them can hold a private copy of it.
"""

import json
import sys

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


def source_paths(sources):
    """Every IG resource and table a declaration reads. Used for dating."""
    paths = [p for s in sources if (p := resource_path(s)).is_file()]
    # Mapping tables are inputs too: editing one is a real change to the map,
    # and the resource date has to move with it.
    paths += [s["table"] for s in sources
              if "table" in s and s["table"].is_file()]
    return paths
