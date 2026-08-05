"""The shared build: declaration in, four files out.

Every builder calls run() with its SOURCES and META. What it produces:

    ConceptMap-<id>.json                  the map
    ValueSet-<target id>.json             the enumerated target value set
    unmapped-<field>.csv                  what nothing could map, with reasons
    <field>-report.json                   coverage, comparable across populations

Offline by design. There is no --fhir-base and no network: a builder is a pure
function of the committed inputs, which is what makes it fast enough to re-run
while iterating and what makes a rebuild from unchanged inputs byte-identical.
Publishing is upload.py's job; the $translate round-trip against a deployed map
is verify's.
"""

import argparse
import json
import sys
from pathlib import Path

from common import paths

from .assemble import build_groups, unmatched_groups
from .built import default_date, load_built
from .canonical import CANONICAL_BASE, PUBLISHER
from .igsource import source_paths
from .project import project
from .report import write_report, write_unmapped
from .stats import enrich


def build_conceptmap(sources, meta, built, date, version):
    groups, unmapped, streams = build_groups(sources, meta["element"], built)
    groups += unmatched_groups(unmapped)
    resource = {
        "resourceType": "ConceptMap",
        "id": meta["id"],
        "url": f"{CANONICAL_BASE}/ConceptMap/{meta['id']}",
        "version": version,
        "name": meta["name"],
        "title": meta["title"],
        "status": "active",
        "experimental": False,
        "date": date,
        "publisher": PUBLISHER,
        "description": meta["description"],
        "purpose": meta["purpose"],
        "sourceCanonical": meta["source_valueset"],
        "targetCanonical": meta["target_valueset"],
        "group": groups,
    }
    if meta.get("copyright"):
        resource["copyright"] = meta["copyright"]
    return resource, unmapped, streams


def report_groups(resource):
    for group in resource["group"]:
        # Keyed on whether the elements carry a target CODE, not on whether the
        # group carries a targetVersion: identity and table groups are
        # versionless too, and they are mappings, not gaps.
        target = group["target"].rsplit("/", 1)[-1]
        version = group.get("targetVersion", "-")
        mapped = any(t.get("code") for e in group["element"]
                     for t in e.get("target", []))
        suffix = "" if mapped else "  unmatched"
        print(f"    {group['source'].rsplit('/', 1)[-1]:26s} -> "
              f"{target:12s} {version:6s}"
              f"{len(group['element']):>7,} element(s){suffix}",
              file=sys.stderr)


def run(field_key, sources, meta, version, extras=None):
    """Build and write everything for one bound element."""
    ap = argparse.ArgumentParser(
        description=meta.get("cli_description"),
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out-dir", type=Path, default=paths.OUTPUT,
                    help=f"where to write (default: {paths.OUTPUT})")
    ap.add_argument("--version", default=version,
                    help="resource version (default: %(default)s)")
    ap.add_argument("--date",
                    help="resource date (default: newest input mtime, so a "
                         "build from unchanged inputs stays byte-identical)")
    args = ap.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)

    date = args.date or default_date(args.out_dir, source_paths(sources))

    print(f"== {field_key} ({meta['element']}) ==", file=sys.stderr)
    print("loading built CodeSystems ...", file=sys.stderr)
    built = load_built(args.out_dir)

    conceptmap, unmapped, streams = build_conceptmap(
        sources, meta, built, date, args.version)
    enrich(streams, sources, args.out_dir)
    total = sum(len(g["element"]) for g in conceptmap["group"])
    print(f"\n  {conceptmap['url']}", file=sys.stderr)
    report_groups(conceptmap)

    cm_path = args.out_dir / f"ConceptMap-{meta['id']}.json"
    cm_path.write_text(json.dumps(conceptmap, indent=1) + "\n")
    print(f"  wrote {cm_path.name} ({cm_path.stat().st_size / 1e6:.1f} MB, "
          f"{len(conceptmap['group'])} groups, {total:,} elements)",
          file=sys.stderr)

    valueset = project(conceptmap, meta, date, args.version)
    vs_path = args.out_dir / f"ValueSet-{valueset['id']}.json"
    vs_path.write_text(json.dumps(valueset, indent=1) + "\n")
    distinct = sum(len(i["concept"]) for i in valueset["compose"]["include"])
    print(f"  wrote {vs_path.name} ({vs_path.stat().st_size / 1e6:.1f} MB, "
          f"{distinct:,} distinct target codes)", file=sys.stderr)
    for include in valueset["compose"]["include"]:
        print(f"    {include['system']} | "
              f"{include.get('version', '(unversioned)')}   "
              f"{len(include['concept']):,} codes", file=sys.stderr)

    csv_path = write_unmapped(field_key, unmapped, args.out_dir)
    if unmapped:
        print(f"  UNMAPPED: {len(unmapped)} code(s) -> {csv_path.name}",
              file=sys.stderr)
    else:
        print(f"  unmapped: none ({csv_path.name} is empty)", file=sys.stderr)

    report_path, _ = write_report(
        field_key, meta["element"], conceptmap, valueset, unmapped,
        args.out_dir, by_stream=streams,
        extras=extras(conceptmap, unmapped) if extras else None)
    print(f"  wrote {report_path.name}", file=sys.stderr)
    return 0
