"""Canonical locations inside scripts/terminology-mapping/.

Everything is derived from this file's own location so the scripts work
regardless of the current working directory.
"""

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# External release files, one folder per code system then per year. Overridable
# with $ICD_SOURCE_DIR for checkouts that keep the (large) sources elsewhere.
SOURCES = Path(os.environ.get("ICD_SOURCE_DIR", ROOT / "sources"))

# Generated FHIR resources, flat, named ResourceType-id.json.
OUTPUT = ROOT / "output"

# Per-code occurrence counts extracted once on the HPC node and committed. An
# OPTIONAL input: without it build_statistics.py reports code coverage alone.
# See occurrences/README.md.
OCCURRENCES = ROOT / "occurrences"
