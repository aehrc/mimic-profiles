"""Projecting the enumerated target ValueSet out of the ConceptMap.

The value set IS the map's `targetCanonical`, so deriving it from that map's
target side makes "member of the value set" and "reachable by $translate" the
same set by construction. There is no second source of truth and no mapping rule
is applied here.

Built in the same pass as the map, which is why there is no scaffold ValueSet any
more. The scaffold existed only because the map was written in one stage and the
value set derived from it in a later one, so at map-writing time the
`targetCanonical` pointed at nothing. Nothing else ever read it.

`unmatched` targets are skipped: they carry no code — only the system that was
searched — and exist to record that a source code was considered and deliberately
not mapped. Including them would put a codeless entry in the value set. The
codeless check is what excludes them; their group does name a target system, so a
group-level check could not.

`targetVersion` is absent for groups mapping into systems this repo does not
build (SNOMED). That flows through to a compose.include with no `version`, which
is how "whatever release the server holds" is spelled.
"""

from collections import defaultdict

from .canonical import PUBLISHER


def project(conceptmap, meta, date, version):
    """The enumerated ValueSet for a ConceptMap's target side."""
    buckets = defaultdict(dict)   # (system, version) -> {code: display}
    for group in conceptmap["group"]:
        if not group.get("target"):
            continue
        for element in group["element"]:
            for concept in element.get("target", []):
                if not concept.get("code"):
                    continue
                buckets[(group["target"], group.get("targetVersion"))][
                    concept["code"]] = concept.get("display", "")

    includes = []
    for system, release in sorted(buckets, key=lambda k: (k[0], k[1] or "")):
        concepts = buckets[(system, release)]
        include = {"system": system}
        if release:
            include["version"] = release
        include["concept"] = [{"code": c, "display": d} if d else {"code": c}
                              for c, d in sorted(concepts.items())]
        includes.append(include)

    url = meta["target_valueset"]
    identifier = url.rsplit("/", 1)[-1]
    return {
        "resourceType": "ValueSet",
        "id": identifier,
        "url": url,
        "version": version,
        "name": "".join(p.capitalize() for p in identifier.split("-")),
        "title": meta["target_title"],
        "status": "active",
        "experimental": False,
        "date": date,
        "publisher": PUBLISHER,
        "description": meta["target_description"],
        "compose": {"include": includes},
    }
