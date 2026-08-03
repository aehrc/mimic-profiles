https://www.cms.gov/medicare/coding-billing/icd-10-codes/icd-9-cm-diagnosis-procedure-codes-abbreviated-and-full-code-titles
https://archive.cdc.gov/www_cdc_gov/nchs/icd/icd9cm.htm

# terminology-mapping

Everything that turns raw ICD release files into FHIR terminology resources, and
those resources into the ConceptMaps and ValueSets MIMIC's coded fields resolve
through. Absorbed the former `scripts/terminology-build/` and
`scripts/icd-migration/` — this is the only home now.

## The flow

Five stages. Stages 1–4 are local and offline; stage 5 is the only one that needs
a decision from you.

```
  ┌─ 1 ─ per (system, release) ──────────────────────────────────────┐
  │  sources/  ──build──►  output/CodeSystem-*.json  ──upload──►     │
  │                                                    $lookup       │
  └──────────────────────────┬───────────────────────────────────────┘
  ┌─ 2 ─────────────────────▼────────────────────────────────────────┐
  │  scaffold ValueSet: "every code in the built releases", ~1 KB     │
  └──────────────────────────┬───────────────────────────────────────┘
  ┌─ 3 ─ per bound field ────▼───────────────────────────────────────┐
  │  ConceptMap   source: mimic-*-icd    target: the stage-2 scaffold │
  │  each code pinned to the EARLIEST release containing it           │
  │  ***  THE ONLY PLACE MAPPING RULES LIVE  ***                      │
  └──────────────────────────┬───────────────────────────────────────┘
  ┌─ 4 ─ per bound field ────▼───────────────────────────────────────┐
  │  for every code in the MIMIC ValueSet:                            │
  │      translate it through the ConceptMap                          │
  │      hit  ──► write (system, version, code) into the new VS       │
  │      miss ──► write a row into unmapped-<field>.csv               │
  │  the result REPLACES the stage-2 scaffold at the same URL         │
  └──────────────────────────┬───────────────────────────────────────┘
             ── you read the unmapped CSV ──
  ┌─ 5 ─────────────────────▼────────────────────────────────────────┐
  │  publish ConceptMaps + ValueSets — refused while anything is      │
  │  unmapped, unless you pass --allow-unmapped                       │
  └──────────────────────────────────────────────────────────────────┘
```

Two ConceptMaps and two ValueSets, one per bound field, so a consumer starting
from a bound element resolves exactly one map:

| Bound element | Bound ValueSet | ConceptMap | Target ValueSet |
|---|---|---|---|
| `Condition.code` | `mimic-diagnosis-icd` | `mimic-diagnosis-icd-to-sid` | `mimic-diagnosis` |
| `Procedure.code` | `mimic-procedure-icd` | `mimic-procedure-icd-to-sid` | `mimic-procedure` |

### Why stage 2 exists

A chicken-and-egg: the ConceptMap needs a `targetCanonical` to point at, but the
real target ValueSet is derived *from* the ConceptMap in stage 4. The scaffold is
that URL's first tenant — a bare `compose.include` of `{system, version}` meaning
"every code in these releases". Deliberately **not** enumerated: a 1:1 enumeration
of the built CodeSystems is ~700,000 concepts, while the scaffold is about 1 KB.
Stage 4 overwrites it at the same canonical URL. Nothing should ever expand it,
and it is gitignored.

### The one rule about rules

**`conceptmaps/build_conceptmap.py` is the only place a mapping rule may live.**
Every consumer — the ValueSet builder, the verifier, anything downstream — reads
the generated ConceptMap and never re-derives a mapping. This is not stylistic:
the dot-insertion rules were previously reimplemented in three scripts that
drifted apart, and the coverage checker and the published map disagreed as a
result. If you find yourself writing `code[:3] + "." + code[3:]` anywhere else in
this repo, that is the bug.

Future mapping rules more complex than dot insertion go in that same file, and
everything downstream gets them for free.

## Running it

```sh
make verify-inputs        # do my ICD sources match input-manifest.json?
make update-manifest      # re-pin them after adding or changing a release

make terminology          # stage 1, build only
make deploy-terminology   # stage 1, build + upload + $lookup smoke tests

make mappings             # stages 2-4 then verify — the everyday command
make verify-mappings      # the checks on their own

make upload-mappings                         # stage 5, refuses while codes are unmapped
make upload-mappings ARGS=--allow-unmapped   # ... once you have reviewed the CSV
```

`make mappings` is what you run while iterating: no network, a few seconds,
because stage 4 reads the ConceptMap from disk instead of calling `$translate`.
Drop `--offline` from `build_final_valueset.py` to exercise the deployed map
instead — it then calls `ConceptMap/$translate` per code and cross-checks every
answer against the local file.

Uploads go to `$ONTOSERVER_URL`. velonto needs `--insecure` (or `--ca-bundle`);
every build script shares `--out-dir`, `--fhir-base`, `--no-upload`,
`--ca-bundle`, `--insecure`. See `--help`.

Publication is a plain `PUT` by resource id, which fully replaces the previous
copy. Nothing is deleted first — CodeSystem releases deliberately share one
canonical URL and differ only by `version`, so a delete-by-url would take the
siblings with it.

### How unmapped codes are recorded

A code MIMIC uses that has no counterpart in any built release is recorded in
**two** places, and `verify_mappings.py` fails if they disagree:

- `unmapped-<field>.csv` — your worklist.
- the ConceptMap itself, as an element whose target has
  `equivalence: "unmatched"` and **no code**, in a group with no `target`
  system, carrying a comment saying which code was expected and why it is
  absent. This makes "considered, and there is deliberately no target" a
  machine-readable fact rather than a silent omission.

Note this is *not* `ConceptMap.group.unmapped`. That element is a fallback
**rule**, not a list — its modes are `provided` (echo the source code back),
`fixed` (send everything to one code) and `other-map`. `provided` would make
`$translate` return `0095` as though it were a valid ICD-9-CM code, i.e. answer
confidently with something fabricated. A reported gap beats a silent wrong
answer.

### The refine loop

Stage 4 always writes `unmapped-<field>.csv`, empty or not. The goal is empty.
When it isn't, the fix is almost always a **missing input**, not a missing
judgement — build the release that has the code:

```sh
ls scripts/terminology-mapping/sources/icd10pcs/      # which years do I have?
make terminology ICD10PCS_YEARS="2016 2017 2018"      # build the missing one
make mappings                                          # re-check
```

## Layout

```
sources/            external release files, gitignored; per code system, per year
  icd9/{2012,2014}/  icd10cm/{2016..2019,2024}/  icd10pcs/{2016,2018,2019,2020}/
common/             shared helpers (TLS, HTTP, upload + $lookup smoke test, CLI)
terminology/        stage 1 — source files -> CodeSystem, one folder per system
  icd9/  icd10cm/  icd10pcs/
valuesets/          stages 2 and 4
  build_scaffold_valueset.py    build_final_valueset.py
conceptmaps/        stage 3 — the only place mapping rules live
  build_conceptmap.py
verify/             the checks, and stage 5's gate
  verify_mappings.py
output/             every generated resource, flat, ResourceType-id.json
input-manifest.json sha256 of every input that influences a generated resource
```

A code system's folder is keyed by its **canonical URL**, not by its source files.
That is why ICD-9-CM diagnoses and procedures share one folder and produce one
CodeSystem: THO assigns both to `http://hl7.org/fhir/sid/icd-9-cm`, so a `Coding`
cannot distinguish them and the server can only resolve that URI to one resource.
They are separated by a `kind` property instead.

## Code systems

| Script | Canonical URL | Output |
|---|---|---|
| `terminology/icd9/build_icd9cm_codesystem.py` | `http://hl7.org/fhir/sid/icd-9-cm` | `CodeSystem-icd-9-cm-2012.json` |
| `terminology/icd10cm/build_icd10cm_codesystem.py` | `http://hl7.org/fhir/sid/icd-10-cm` | `CodeSystem-icd-10-cm-<year>.json` |
| `terminology/icd10pcs/build_icd10pcs_codesystem.py` | `http://www.cms.gov/Medicare/Coding/ICD10` | `CodeSystem-icd-10-pcs-<year>.json` |

Every builder takes release years as positional arguments and shares the same
flags (`--base-dir`, `--out-dir`, `--fhir-base`, `--no-upload`, `--ca-bundle`,
`--insecure`). Which years get built comes from `ICD10_YEARS` /
`ICD10PCS_YEARS` in the `Makefile`.

Note that ICD-10-PCS is **not** under `hl7.org/fhir/sid/` the way the other two
are, and THO's own `icd10PCS` entry is a `content: not-present` stub with no
properties or filters — there is no upstream resource to copy from.

### ICD-9-CM carries both volumes in one resource

`CodeSystem-icd-9-cm-2012.json` holds Volumes 1-2 (diagnosis, `Dtab12.rtf`) and
Volume 3 (procedure, `Ptab12.RTF`) side by side, because THO lists ICD-9-CM
twice under the one canonical URL and they differ only in OID — `...6.103` for
diagnoses, `...6.104` for procedures. Both are carried as `identifier`, and a
`kind` property (`diagnosis` | `procedure`) is the only thing separating the two
trees. Two resources is not an option: `url` + `version` is the CodeSystem's
identity, so the second upload would be rejected as a conflict.

The merge is safe because the **dotted** forms are disjoint — diagnosis codes
have three characters before the dot (or a V/E prefix), procedure codes two —
and the builder asserts that rather than trusting it. The **dot-less** forms are
not: `4019` is both `401.9` (essential hypertension, one of the most common
codes in MIMIC) and `40.19`. Nothing in the string recovers the dot; only the
originating MIMIC table does. That is why the CMS long-description files are
applied per volume and never to a merged code list, and why any dot-less lookup
keyed on this URL must also carry `kind`.

Procedure expansion mirrors the diagnosis side — the tabular lists neither the
fourth digits of sections 38 and 77-80 (a `[0-9]` bracket under each covered
subcategory) nor those of sections 90-91 (no brackets; every subcategory takes
every digit the block defines). A subcategory with no bracket under a
bracket-using block takes no fourth digit at all and is a leaf in its own right,
which is what keeps `80.6` from being wrongly split into `80.60`-`80.69`. The
build verifies the expanded leaf set against `CMS29_DESC_LONG_SG.txt`, which is
authoritative for which procedure codes exist; it currently matches exactly
(3,877), and 3,738 of the generated displays are byte-identical to CMS before
the long descriptions are even applied.

### ICD-10-PCS is not shaped like ICD-10-CM

PCS codes are exactly seven characters, all of them billable, with no dots and no
category codes — so there is no `billable` property and no dot insertion. What it
has instead is a positional hierarchy, which the builder materialises as five
tiers:

| Tier | Chars | Count (FY2018) | Source |
|---|---|---|---|
| Section | 1 | 17 | tables XML, axis 1 |
| Body system | 2 | 109 | tables XML, axis 2 |
| Table | 3 | 873 | **CMS**, the flag-0 rows of the order file |
| Body part | 4 | 11,630 | tables XML, axis 4 |
| Code | 7 | 78,705 | order file, flag 1 |

Only the 7-character leaves are valid codes. Every shorter concept carries the
standard `notSelectable` property. **ValueSets built over this CodeSystem must
contain leaves only** — consumers are not obliged to honour `notSelectable`, and
at least one (the `code-search` service) ignores it entirely, so a grouper left in
a ValueSet will eventually be returned as an answer.

Two cross-checks the builder relies on: the order file's 78,705 flag-1 codes equal
the cross-product of every `pcsRow`'s axes in the tables XML, and its 873 flag-0
headers equal the number of `pcsTable` elements.

Designations come from the alphabetic index — the clinical vernacular
("Abdominohysterectomy", "Aqueduct of Sylvius") that appears nowhere in the
generated displays. The index targets the 4-character tier, so by default those
terms are also propagated down to the leaves, since consumers typically expand a
leaf-only ValueSet and would never see them otherwise. That propagation is what
takes the resource from 39 MB to 85 MB; `--no-propagate` turns it off.

Root-operation definitions (817 of the 873 tables have one; the rest are imaging
and other sections where character 3 is not an Operation) land on the 3-character
tier as `concept.definition`.

## Two ways a dot-less code lies to you

MIMIC stores every ICD code without dots, and that form is genuinely ambiguous.
Both mechanisms below are load-bearing, and the verifier checks them.

**1. `kind` — which volume is this?** Covered above: `4019` is both diagnosis
`401.9` and procedure `40.19`, so each bound field matches only its own volume.

**2. No cross-target fallback for procedures.** Diagnosis sources fall back from
ICD-9-CM to ICD-10-CM when a code misses, which is how the six codes MIMIC filed
under `icd_version` 9 that are really ICD-10-CM (`I509`, `J45901`, `O8612`,
`R270`, `S01312A`, `W01190A`) are found. Applying the same fallback to procedures
is actively harmful: **64 of MIMIC's 2,544 ICD-9 procedure codes are verbatim
valid 4-character ICD-10-PCS body-part groupers.** MIMIC procedure `0095` means
ICD-9 `00.95`, but as a raw string it matches PCS `0095` *"Subarachnoid Space,
Intracranial"* — an anatomical structure, not a procedure. Worse, it would map
silently and the unmapped report would then read zero. Procedure sources
therefore have exactly one target each, and PCS matches only 7-character leaves.

## What the verifier checks

`verify/verify_mappings.py` re-derives nothing. It reads the generated artefacts
and checks properties of them:

1. **Coverage** — every MIMIC code is either mapped or listed in the unmapped CSV.
   Nothing may be silently absent from both.
2. **ValueSet == ConceptMap target side** — the VS is the map's `targetCanonical`,
   so "member of the value set" and "reachable by `$translate`" must be the same
   set. Drift means the two were built from different inputs.
3. **Only releases built here** — a shared terminology server can hold releases
   this repo has no source for; pinning a code into one produces an artefact that
   cannot be reproduced or redistributed.
4. **No PCS grouper mappings** — the collision above, checked explicitly rather
   than trusted to stay correct.

Checks 2–4 are correctness bugs, and `--allow-unmapped` does not relax them.

## Source data layout (not committed)

The raw distributions are gitignored — download them and lay them out under
`sources/` as above, or point `$ICD_SOURCE_DIR` elsewhere. Order files are matched
by glob (`*order*<year>*.txt`) and XML by `rglob`, so CMS zips can be extracted
into the year folder as-is regardless of the folder names inside.

Verify what you have matches what the committed resources were built from:

```sh
uv run scripts/terminology-mapping/verify_inputs.py
```

Sources:

- ICD-10-CM and ICD-10-PCS: <https://www.cms.gov/medicare/coding-billing/icd-10-codes>
- ICD-9-CM 2012: CDC/CMS FY2012 (v29) distribution. Two zips: the CDC tabular
  RTFs (`Dtab12.rtf`, `Ptab12.RTF`) and the CMS long descriptions, which ship
  `CMS29_DESC_LONG_DX` and `CMS29_DESC_LONG_SG` together (DX = Volumes 1-2,
  SG = Volume 3). Both description files are optional — without them the
  contextless tabular titles are used, so `003.29` stays `"Other"` instead of
  `"Other localized salmonella infections"`.

ICD-9-CM RTF parsing uses the pure-Python `striprtf` package (pinned in the repo's
`pyproject.toml`), so all builds are cross-platform; the output was verified
byte-identical to the previous macOS `textutil`-based conversion.

## Output and reproducibility

Committed: `ConceptMap-*.json` and the two enumerated `ValueSet-*.json`. These
are the deliverables, and will eventually be released elsewhere.

Not committed: `CodeSystem-*.json` (36–85 MB each — attached as assets to the
GitHub release for the IG version they belong to; download from there to use them
without rebuilding) and the stage-2 scaffolds.

**Rebuilds from unchanged inputs are byte-identical.** `date` is derived from the
newest input mtime rather than from `now`, so a re-run never churns the diff and
`git diff` on a committed artefact always means a real change. `make mappings &&
git diff --exit-code` is a valid test.

## Canonical base — why these are not in the IG

The ConceptMaps and the ValueSets they target live under **our own** base:

```
http://fhnaumann.github.io/mimic-profiles/fhir/ConceptMap/mimic-diagnosis-icd-to-sid
http://fhnaumann.github.io/mimic-profiles/fhir/ValueSet/mimic-diagnosis
```

not under `http://mimic.mit.edu/fhir/mimic`, which belongs to the upstream IG's
publisher (KinD Lab). Minting new canonicals in someone else's namespace risks a
collision on a shared terminology server if upstream ever publishes at the same
URL. Referencing their canonicals is fine, and `sourceCanonical` deliberately
still points at their bound value sets.

The consequence is that these resources cannot live in `input/resources/`: the IG
publisher requires every resource it carries to have a url under the IG canonical.
They are uploaded straight to the terminology server instead, and nothing in
`input/fsh/` references them, so the IG build is unaffected.

## Consumer notes

A consumer starting from a bound element finds the right map without hardcoding
the pairing:

```
GET [base]/ConceptMap?source-uri=http://mimic.mit.edu/fhir/mimic/ValueSet/mimic-diagnosis-icd&_summary=true
```

- **Use `source-uri`, not `source`.** R4 defines both, but Ontoserver 6.x
  implements only `source-uri` — and matches it against `sourceCanonical`. Plain
  `source` returns `HTTP 400 not-supported`.
- **`_summary=true` is worth it.** The scope fields are summary elements and
  survive; `group` does not. That is ~1 KB instead of 8 MB. Fetch by id or pass
  `_summary=false` when you actually need `group.targetVersion`.
- **`$translate` does not return the release.** Ontoserver 6.27.3 does not echo
  `group.targetVersion` into the returned `Coding`. Codes present in only one
  release (the icd-10-cm 2024 tail, 43 codes) then fail `$validate-code` against
  the multi-version value set unless the version is restored from the map's group.
- **Drop `Coding.version` before reverse-translating.** A code is mapped into the
  *earliest* release containing it, so a coding stamped `version=2024` will not
  match a code filed in the 2016 group.
- **Omit `targetsystem` and OR every returned Coding into the filter.** The six
  relabeled codes mean an ICD-10-CM code can legitimately reverse-map to both
  `mimic-diagnosis-icd10|X` and `mimic-diagnosis-icd9|X`.

## Context: the reverted migration

In July 2026 `Condition.code` was rewritten onto the standard `icd-9-cm` /
`icd-10-cm` systems and the IG re-bound to a matching ValueSet. **That migration
was reverted.** `Condition.code` is bound to `mimic-diagnosis-icd` again (the
union of the custom `mimic-diagnosis-icd9` / `mimic-diagnosis-icd10` CodeSystems)
and the data carries MIMIC's dot-less codes; translation to the standard systems
is a **read-time** concern, done through the ConceptMaps built here (e.g. the
`translate()` calls in `scripts/mimic-pipeline/probe-view-dwd.json`), not by
rewriting stored resources. Only the profile re-binding and the data rewrite were
reverted, and neither lived here.
