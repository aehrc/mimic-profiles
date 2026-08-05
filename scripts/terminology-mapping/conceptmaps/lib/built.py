"""The built standard CodeSystems, and resolving a code into a release.

Answers come from the CodeSystems in output/ that stage 1 wrote and uploaded, so
the files and the server hold the same content. Reading them locally costs
nothing, which is what keeps the builders offline and instant.

Each code is mapped into the EARLIEST release containing it, because
`group.targetVersion` is the only place R4 lets a target release be recorded —
there is no version on group.element.target.
"""

import datetime
import json
import sys

from .canonical import MIMIC_BASE
from .notation import concept_properties


def load_built(out_dir):
    """(url, version) -> {code: (display, properties)}, from every built release."""
    built = {}
    for path in sorted(out_dir.glob("CodeSystem-*.json")):
        cs = json.loads(path.read_text())
        # Skip MIMIC's own CodeSystems if they ever land here; only standard
        # releases are mapping targets.
        if cs["url"].startswith(MIMIC_BASE):
            continue
        built[(cs["url"], cs["version"])] = {
            c["code"]: (c.get("display", ""), concept_properties(c))
            for c in cs["concept"]
        }
        print(f"  loaded {path.name}: {cs['url']} v{cs['version']}, "
              f"{len(cs['concept']):,} concepts", file=sys.stderr)
    if not built:
        sys.exit(f"no CodeSystem-*.json in {out_dir} — run `make terminology` first")
    return built


def releases_of(built, system):
    """Every built release of a system, oldest first."""
    return sorted(v for (url, v) in built if url == system)


def find(built, tgt, official):
    """Earliest release of tgt['system'] holding `official`, honouring the
    target's kind filter and predicate. Returns (version, display) or None."""
    for version in releases_of(built, tgt["system"]):
        entry = built[(tgt["system"], version)].get(official)
        if entry is None:
            continue
        display, props = entry
        if tgt["kind"] and props.get("kind") != tgt["kind"]:
            continue
        if tgt["predicate"] and not tgt["predicate"](official, props):
            continue
        return version, display
    return None


def default_date(out_dir, extra_paths=()):
    """Newest mtime among this population's inputs, as a date.

    NOT today's date: these artefacts are committed, so a build from unchanged
    inputs must produce a byte-identical file. Dating them 'now' would churn the
    diff every day and make a real change indistinguishable from a re-run.

    Scoped to one population's inputs plus the built CodeSystems, where the
    single-file version considered every population's inputs at once. That was
    the only thing it could do with one script building both maps, and it meant
    editing a diagnosis input moved the date on the procedure map. In practice
    the built CodeSystems are the newest input, so both spellings agree.
    """
    inputs = list(out_dir.glob("CodeSystem-*.json")) + list(extra_paths)
    newest = max(p.stat().st_mtime for p in inputs) if inputs else 0
    return datetime.datetime.fromtimestamp(
        newest, datetime.timezone.utc).date().isoformat()
