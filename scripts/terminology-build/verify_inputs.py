#!/usr/bin/env python3
"""Verify the raw ICD source files against input-manifest.json.

Confirms the files under $ICD_SOURCE_DIR (or --base-dir) are byte-identical to
the ones the committed CodeSystems were generated from, so a rebuild that
diverges can be blamed on code, not data.

Usage:
  uv run scripts/terminology-build/verify_inputs.py
  uv run scripts/terminology-build/verify_inputs.py --base-dir /path/to/icd-sources
"""

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

MANIFEST = Path(__file__).parent / "input-manifest.json"


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base-dir", type=Path,
                    default=Path(os.environ.get("ICD_SOURCE_DIR",
                                                Path(__file__).parent)),
                    help="directory containing the ICD source folders "
                         "(default: $ICD_SOURCE_DIR)")
    args = ap.parse_args()

    manifest = json.loads(MANIFEST.read_text())
    failures = 0
    for entry in manifest["files"]:
        path = args.base_dir / entry["path"]
        if not path.is_file():
            print(f"MISSING  {entry['path']}")
            failures += 1
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != entry["sha256"]:
            print(f"MISMATCH {entry['path']}\n"
                  f"  expected sha256 {entry['sha256']}\n"
                  f"  actual   sha256 {digest}")
            failures += 1
        else:
            print(f"ok       {entry['path']}")
    if failures:
        sys.exit(f"{failures} of {len(manifest['files'])} input files "
                 f"missing or changed")
    print(f"all {len(manifest['files'])} input files verified")


if __name__ == "__main__":
    main()
