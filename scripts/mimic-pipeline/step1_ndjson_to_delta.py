"""Step 1 — convert the MIMIC-on-FHIR NDJSON distribution to a Pathling Delta warehouse.

MIMIC ships one gzipped NDJSON file per profile flavour
(MimicObservationChartevents, MimicMedicationAdministrationICU, ...). Pathling
stores one Delta table per FHIR resource type, so the flavours are collapsed:
the demo dataset's 30 files become 13 tables.

Which resource type a file holds is read from the `resourceType` of its first
line, rather than matched off the file name as the Pathling MIMIC tutorial
does — same `file_name_mapper` mechanism, but no list of Mimic suffixes to
keep up to date, and no way for MimicMedicationMix -> Medication to go wrong.
The flavour is not lost; it stays on each resource's `meta.profile`.

This is the only step allowed to use the Pathling library directly, because it
creates the warehouse the server reads from. Later steps go through the server.

Usage:
  uv run python step1_ndjson_to_delta.py \
      --source /Users/nau025/warehouses/mimic-iv-demo \
      --target /Users/nau025/warehouses/mimic-iv-demo/delta
"""

import argparse
import gzip
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(line_buffering=True)


def resource_type_of(path: Path) -> str | None:
    """The `resourceType` of the first line of a (possibly gzipped) NDJSON file."""
    opener = gzip.open if path.name.endswith(".gz") else open
    with opener(path, "rt", encoding="utf-8") as fh:
        line = fh.readline().strip()
    return json.loads(line).get("resourceType") if line else None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--source", type=Path, required=True,
                        help="directory of Mimic*.ndjson.gz files")
    parser.add_argument("--target", type=Path, required=True,
                        help="Delta warehouse to write the tables into")
    # Pathling globs on the *last* extension segment only, so this is "gz", not
    # "ndjson.gz" — the compound form matches no files and silently yields an
    # empty warehouse. It still hands the mapper the fully stripped stem
    # ('MimicPatient'), so gzipped files are read in place, no decompression.
    parser.add_argument("--extension", default="gz",
                        help="last segment of the source file extension "
                             "(default: gz; use `ndjson` for uncompressed)")
    args = parser.parse_args()

    source, target = args.source.resolve(), args.target.resolve()
    suffix = f".{args.extension}"

    # Sniff every source file up front, so the mapper is a plain dict lookup.
    by_stem = {}
    for path in sorted(p for p in source.iterdir() if p.name.endswith(suffix)):
        resource_type = resource_type_of(path)
        if resource_type:
            by_stem[path.name.split(".")[0]] = [resource_type]
            print(f"  {path.name} → {resource_type}")
        else:
            print(f"  [warn] {path.name} is empty, skipping")
    if not by_stem:
        raise SystemExit(f"No *{suffix} files in {source}")

    from pathling import PathlingContext

    print(f"\nConverting {len(by_stem)} file(s) → {len(set(map(tuple, by_stem.values())))} "
          f"table(s) in {target} …")
    # Extensions must be on: the server encodes with them (EncodingConfiguration
    # defaults enableExtensions=true), so a warehouse written without them lacks
    # the _fid / _extension columns the server's analysis expects, and every
    # ViewDefinition fails with DELTA_SCHEMA_CHANGE_SINCE_ANALYSIS.
    pc = PathlingContext.create(
        enable_delta=True, enable_terminology=False, enable_extensions=True
    )

    # Pathling hands the mapper every entry in the directory with its extension
    # stripped, including the target warehouse when it is nested inside the
    # source. Anything unknown maps to no resource type, which excludes it.
    data = pc.read.ndjson(
        str(source),
        extension=args.extension,
        file_name_mapper=lambda name: by_stem.get(name.split(".")[0], []),
    )
    resolved = data.resource_types()
    if not resolved:
        raise SystemExit(f"Pathling matched no *{suffix} files in {source}")

    details = data.write.delta(str(target), save_mode="overwrite")

    print(f"\nWrote {len(details.file_infos)} table(s):")
    for info in sorted(details.file_infos, key=lambda fi: fi.fhir_resource_type):
        print(f"  {info.fhir_resource_type:28s} {info.absolute_url}")


if __name__ == "__main__":
    main()
