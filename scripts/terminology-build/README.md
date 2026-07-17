# terminology-build

Builds FHIR R4 CodeSystem resources for ICD-9-CM (2012) and ICD-10-CM (2016–2019),
plus a `mimic-diagnosis` ValueSet covering the code systems used by MIMIC diagnosis
data, for loading into Ontoserver.

Merged from the former standalone `update-mimic-terminology` repo (plain copy, no
history) as part of unifying all MIMIC-on-FHIR modifications in this repo.

## Scripts

| Script | Output |
|---|---|
| `build_icd9cm_codesystem.py` | `output/CodeSystem-icd-9-cm-2012.json`, `output/ValueSet-mimic-diagnosis.json` |
| `build_icd10cm_codesystem.py` | `output/CodeSystem-icd-10-cm-<year>.json` for each year |

Both scripts write to `output/` and can optionally upload the resources to an
Ontoserver instance.

## Source data layout (not committed)

The raw ICD source distributions are **gitignored** — download them yourself and lay
them out as follows, relative to this directory (or point `--base-dir` / `--rtf`
elsewhere):

```
2012_icd9/
  Dtab12.rtf                    # required: CDC FY2012 "Disease Tabular" RTF
  CMS29_DESC_LONG_DX*.txt       # optional: CMS v29 long descriptions
2016/
  icd10cm_order_2016.txt        # required: CMS code-descriptions-in-tabular-order file
  .../icd10cm_tabular_*.xml     # optional: full tabular XML (any subfolder)
2017/  … same pattern …
2018/  … same pattern …
2019/  … same pattern …
```

Notes:

- The ICD-10-CM order file is matched by glob `*order*<year>*.txt`, so the exact
  filename from the CMS download works as-is.
- The tabular XML is discovered anywhere inside the year folder via `rglob("*.xml")`,
  so the CMS zip can be extracted directly into the year folder (folder names inside
  vary by year, e.g. `ICD10CM_FY2016_ Full_ XML/`, `2019 Table and Index/`).
- ICD-9-CM RTF parsing uses the pure-Python `striprtf` package (pinned in the repo's
  `pyproject.toml`), so all builds are cross-platform. The output was verified
  byte-identical to the previous macOS `textutil`-based conversion.

Sources:

- ICD-10-CM: https://www.cms.gov/medicare/coding-billing/icd-10-codes (yearly
  "Code Descriptions in Tabular Order" and "Code Tables and Index" downloads)
- ICD-9-CM 2012: CDC/CMS FY2012 (v29) distribution

## Usage

Run from the repo root with the uv-managed environment:

```sh
uv run scripts/terminology-build/build_icd10cm_codesystem.py   # builds all years into output/
uv run scripts/terminology-build/build_icd9cm_codesystem.py    # builds ICD-9-CM + the ValueSet
```

See `--help` on each script for options (`--base-dir`, `--out-dir`, upload flags).

## Output

`output/ValueSet-mimic-diagnosis.json` (small) is committed. The generated
CodeSystems (~36 MB each) are **not committed** — they are attached as assets to
the GitHub release for the IG version they belong to. To use them without
rebuilding, download from the release; to rebuild, follow the source-data layout
above.
