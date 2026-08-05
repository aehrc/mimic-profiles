#!/usr/bin/env python3
"""Publish the generated ConceptMap / ValueSet pairs to a terminology server.

Separate from the builders because they are offline by design: a builder is a
pure function of the committed inputs, and keeping the network out of it is what
makes it fast to re-run and its output reproducible. This is the one place that
writes to a server.

VALUE SETS GO FIRST. Each ConceptMap's `targetCanonical` names its value set, so
uploading the map first leaves a window where it points at something the server
does not have. Ordering costs nothing and closes it. (There is no transaction
bundle here — `upload()` is a plain PUT by id.)

Discovery is by glob: every ConceptMap in output/ is published together with the
value set its own targetCanonical names. Nothing is hardcoded, so a new
population is published by building it.

PUBLISHING ALL OF THEM IS THE DEFAULT, NOT THE ONLY OPTION. Upload is a plain
PUT by id, so a run replaces the server's copy of every map it touches with
whatever is in out_dir — including populations you did not rebuild and did not
mean to move. `--only` narrows a run to named populations, which is what you
want when publishing one new map onto a server other work already reads from.
It narrows *what is published*, never what is checked: verify_mappings.py still
runs over everything, because a broken map is broken whether or not this run
would have touched it.

Usage:
  uv run scripts/terminology-mapping/upload.py --insecure
  uv run scripts/terminology-mapping/upload.py --fhir-base https://host/fhir
  uv run scripts/terminology-mapping/upload.py --dry-run
  uv run scripts/terminology-mapping/upload.py --only observation-component
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import paths  # noqa: E402
from common.cli import add_common_args  # noqa: E402
from common.fhirclient import configure_tls, upload  # noqa: E402


def populations(out_dir):
    """{population name: ConceptMap url} from the reports each builder writes.

    Still discovery, not a registry: `<field>-report.json` is an artefact of the
    build, so a new population names itself here by being built. The name is the
    builder's own FIELD — the same one `verify_mappings.py` prints and the
    unmapped CSV is named after — so one vocabulary covers all three.
    """
    index = {}
    for path in sorted(out_dir.glob("*-report.json")):
        report = json.loads(path.read_text())
        if "field" in report and "conceptmap" in report:
            index[report["field"]] = report["conceptmap"]
    return index


def select(found, only, out_dir):
    """Keep only the named populations, or fail saying which names exist.

    Matched on the ConceptMap's url rather than on a filename, for the reason
    pairs() locates the value set through targetCanonical: a name resolves to a
    canonical, and the canonical picks the file.
    """
    index = populations(out_dir)
    names = [n.strip() for n in only.split(",") if n.strip()]
    # `--only ""` would otherwise select nothing and publish nothing, which
    # looks exactly like a successful run.
    if not names:
        sys.exit(f"  --only: no population named. Built populations: "
                 f"{', '.join(sorted(index)) or '(none)'}.")
    unknown = [n for n in names if n not in index]
    if unknown:
        sys.exit(f"  --only: no population named {', '.join(unknown)} in "
                 f"{out_dir}. Built populations: "
                 f"{', '.join(sorted(index)) or '(none)'}.")
    wanted = {index[n] for n in names}
    kept = [(vs, cm) for vs, cm in found
            if json.loads(cm.read_text())["url"] in wanted]
    # A report naming a map whose file is gone is stale, and silently publishing
    # nothing is the worst answer to "publish this one".
    if len(kept) != len(wanted):
        sys.exit(f"  --only: {len(wanted)} population(s) named, "
                 f"{len(kept)} ConceptMap file(s) found in {out_dir}. "
                 f"Re-run the builder.")
    return kept


def pairs(out_dir):
    """(valueset path, conceptmap path) for every map in out_dir, in upload order.

    The value set is located through the map's own targetCanonical rather than by
    a naming convention, so a renamed value set cannot be silently skipped.
    """
    found = []
    for cm_path in sorted(out_dir.glob("ConceptMap-*.json")):
        conceptmap = json.loads(cm_path.read_text())
        target = conceptmap.get("targetCanonical")
        if not target:
            sys.exit(f"  {cm_path.name} has no targetCanonical — cannot tell "
                     f"which ValueSet to publish with it.")
        vs_path = out_dir / f"ValueSet-{target.rsplit('/', 1)[-1]}.json"
        if not vs_path.is_file():
            sys.exit(f"  {cm_path.name} points at {target}, but {vs_path.name} "
                     f"is not in {out_dir}. Run the builder first.")
        found.append((vs_path, cm_path))
    if not found:
        sys.exit(f"no ConceptMap-*.json in {out_dir} — run the builders first")
    return found


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_common_args(ap)
    ap.add_argument("--dry-run", action="store_true",
                    help="list what would be published, contact no server")
    ap.add_argument("--only", metavar="NAME[,NAME...]",
                    help="publish only these populations, named as the builders "
                         "name them (see the *-report.json files, or the "
                         "`populations:` line verify_mappings.py prints). "
                         "Default: every ConceptMap in --out-dir")
    args = ap.parse_args()

    found = pairs(args.out_dir)
    # `is not None`, not truthiness: `--only ""` names no population, and
    # treating that as "publish everything" is the opposite of what was asked.
    if args.only is not None:
        found = select(found, args.only, args.out_dir)
    print(f"{len(found)} population(s) in {args.out_dir}")
    for vs_path, cm_path in found:
        print(f"  {vs_path.name}  then  {cm_path.name}")

    if args.dry_run:
        print("\n  --dry-run: nothing published")
        return 0

    configure_tls(args.ca_bundle, args.insecure)
    if not args.fhir_base:
        sys.exit("  no --fhir-base and ONTOSERVER_URL unset — nowhere to publish.")

    print(f"\npublishing to {args.fhir_base}")
    for vs_path, cm_path in found:
        for path in (vs_path, cm_path):
            upload(json.loads(path.read_text()), args.fhir_base)
    print(f"\npublished {len(found) * 2} resource(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
