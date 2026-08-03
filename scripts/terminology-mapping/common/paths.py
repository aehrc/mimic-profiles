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
