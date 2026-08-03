Version distribution: 17,532 codes pin to 2016, 668 to 2017, 129 to 2018, 78 to 2019, and 43 to 2024 — so ~95% were in the original release and each later year adds a small tail of newer codes. Zero unmapped.

  1. You run the check with the merged VS:
  python3 check_icd_codes.py --system both --insecure \
      --valueset http://mimic.mit.edu/fhir/mimic/ValueSet/mimic-diagnosis
  This populates both sections of display-map.json with pinned versions (ICD-9 → 2012). Watch unmapped-icd9.csv — if it's non-empty we refine convert_icd9 before proceeding.

  2. You run the migration — no further changes needed now. It reads both map sections, rewrites both MIMIC systems' codings in one pass, drift-guards per system, and reports per-system/per-version counts. The dry-run just verified the behaviour: with the ICD-9 map section still empty it fails
  loudly and tells you to regenerate or restrict --systems icd10; with --systems icd10 it behaves exactly as the version that already passed on the demo dataset (ICD-9 codings pass through untouched). Once your check run fills the ICD-9 section, the same dry-run will show 0389 → 038.9, V4501
  → V45.01, E8500 → E850.0, all version: 2012. Worth re-running the demo-dataset migration as a rehearsal before the node.

  3. Then the IG update, which at minimum means: switch the Condition.code binding in SD_MimicCondition.fsh from $MimicDiagnosisIcd to the new mimic-diagnosis VS, add the new ValueSet resource to the IG, and decide the fate of the now-unreferenced custom artifacts (mimic-diagnosis-icd, and the
  two custom CodeSystems — retire vs. keep for provenance/mapping documentation). Happy to plan that step in detail when you get there.

  One ordering nuance: do step 3 only after step 2 has actually run on the node, not just the demo — until then the real data still carries the custom systems and the IG would be ahead of the data it describes.

  # False flags

  Some codes in mimic are labeled with icd9 when they are icd10 codes, they will be relabeled (point to icd-1-cm instead of icd-9-cm in this migration)
  The check_icd_codes.py checks that and marks them as "to be moved" in the generated display_map

  original_code,dotted_code,valid,version,official_display,mimic_display,message
I509,I50.9,False,,,"Heart failure, unspecified",Unknown code 'I50.9' in the CodeSystem 'http://hl7.org/fhir/sid/icd-9-cm' version '2012'
J45901,J45.901,False,,,Unspecified asthma with (acute) exacerbation,Unknown code 'J45.901' in the CodeSystem 'http://hl7.org/fhir/sid/icd-9-cm' version '2012'
O8612,O86.12,False,,,Endometritis following delivery,Unknown code 'O86.12' in the CodeSystem 'http://hl7.org/fhir/sid/icd-9-cm' version '2012'
R270,R27.0,False,,,"Ataxia, unspecified",Unknown code 'R27.0' in the CodeSystem 'http://hl7.org/fhir/sid/icd-9-cm' version '2012'
S01312A,S01.312A,False,,,"Laceration without foreign body of left ear, init encntr",Unknown code 'S01.312A' in the CodeSystem 'http://hl7.org/fhir/sid/icd-9-cm' version '2012'
W01190A,W01.190A,False,,,"Fall same lev from slip/trip w strike agnst furniture, init",Unknown code 'W01.190A' in the CodeSystem 'http://hl7.org/fhir/sid/icd-9-cm' version '2012'

Migration report from FULL mimic on fhir data:
```json
{
  "data": "./spark_warehouse",
  "output": "./modified_condition",
  "format": "delta",
  "systems": [
    "icd10",
    "icd9"
  ],
  "condition_rows": 5655376,
  "distinct_source_codes_in_data": {
    "http://mimic.mit.edu/fhir/mimic/CodeSystem/mimic-diagnosis-icd10": 18190,
    "http://mimic.mit.edu/fhir/mimic/CodeSystem/mimic-diagnosis-icd9": 9379
  },
  "codings_on_source_systems_before": {
    "http://mimic.mit.edu/fhir/mimic/CodeSystem/mimic-diagnosis-icd10": 2445484,
    "http://mimic.mit.edu/fhir/mimic/CodeSystem/mimic-diagnosis-icd9": 3209892
  },
  "codings_on_target_systems_after": {
    "http://hl7.org/fhir/sid/icd-10-cm": 2445489,
    "http://hl7.org/fhir/sid/icd-9-cm": 3209887
  },
  "codings_per_pinned_version": {
    "http://hl7.org/fhir/sid/icd-10-cm": {
      "2016": 2392914,
      "2017": 37818,
      "2018": 11392,
      "2019": 2864,
      "2024": 501
    },
    "http://hl7.org/fhir/sid/icd-9-cm": {
      "2012": 3209887
    }
  },
  "residual_source_system_codings": {
    "http://mimic.mit.edu/fhir/mimic/CodeSystem/mimic-diagnosis-icd10": 0,
    "http://mimic.mit.edu/fhir/mimic/CodeSystem/mimic-diagnosis-icd9": 0
  },
  "ok": true
}
```

# Flow through the app

```
 ┌─ your app: config, in-repo, version-pinned ───────────────────────────────┐
 │   FHIRPath context        →  ConceptMap canonical @ version               │
 │     Condition.code        →  .../fhir/ConceptMap/                         │
 │                                mimic-diagnosis-icd-to-sid  @ 1.0.0        │
 │                                                                           │
 │   ✗ no runtime StructureDefinition read — velonto's conformance is        │
 │     from the pre-revert IG and would hand back the TARGET VS as if it     │
 │     were the source. Bindings come from the pinned IG package, if at all. │
 └───────────┬───────────────────────────────────────────────────────────────┘
             │  (1) GET ConceptMap?url=<canonical>&version=1.0.0&_summary=true
             │      ✓ url is unique      ✗ source-uri is many-to-one
             ▼
 ┌─ velonto (shared, mutable) ───────────────────────────────────────────────┐
 │  ConceptMap/mimic-diagnosis-icd-to-sid                                    │
 │    sourceCanonical → .../mimic/ValueSet/mimic-diagnosis-icd   (MIT's)     │
 │    targetCanonical → .../fhir/ValueSet/mimic-diagnosis        (yours)     │
 │                                                                           │
 │  _summary=true → 1.3 KB, keeps both scope fields, drops group (5.8 MB)    │
 └───────────┬───────────────────────────────────────────────────────────────┘
             │  (2) assert sourceCanonical == expected, then read targetCanonical
             ▼
 (3)  searchable ValueSet — real ICD, is-a hierarchy, six releases unioned
        http://fhnaumann.github.io/mimic-profiles/fhir/ValueSet/mimic-diagnosis
             │
             │  (4) code-search(free text, that VS)
             ▼
        "heart failure"  ──►  I50.9  (icd-10-cm)
             │
             │  (5) ConceptMap/$translate  reverse=true
             │        url=<canonical>  system=icd-10-cm  code=I50.9
             │        ✗ no version — codes pin to their EARLIEST release
             │        ✗ no targetsystem — see below
             ▼
 (6)  every match, not .first()
        mimic-diagnosis-icd10 | I509
        mimic-diagnosis-icd9  | I509    ← 6 codes MIMIC misfiled as icd9;
             │                            pinning targetsystem drops these
             │  (7) OR them into the filter
             ▼
 (8)  Condition?code=<sys-icd10>|I509,<sys-icd9>|I509

 ── accepted failure ──────────────────────────────────────────────────────
 (4) can return a valid ICD code absent from MIMIC (or an ancestor like
 I50). (5) then returns result:false → empty filter. Accepted for now.
 Fix if it bites: expand descendant-of <code> ∩ codes-present-in-MIMIC,
 reverse-translate each. Needs an enumerated ~28k-code VS you don't have.
```

## Why the shape is what it is

**(0) No runtime binding lookup.** A shared mutable server is the wrong source of
truth for "what shape is the data I'm querying". Bindings are a property of the
dataset version. If read at runtime, app behaviour changes silently whenever
someone re-publishes conformance resources — and velonto has been sitting on the
pre-revert IG, which would return the target VS as if it were the source: dotted
ICD codes filtered against dot-less MIMIC data, zero rows, no error. If bindings
are ever needed, take them from the pinned IG package (`kindlab.fhir.mimic`,
sushi's `output/package.tgz`) — not by vendoring StructureDefinitions, and not
over the wire.

**(1) Pin by `url`, not `source-uri`.** `url` is a globally unique identifier;
`source-uri` is many-to-one and on a shared server returns every map declaring
that `sourceCanonical` — other versions of ours, plus anything a colleague
uploads. Config pins *identity*; the map stays the source of truth for its own
target VS, so retargeting it needs no app release. `source-uri` is still the right
tool for interactively *finding* a map. Note Ontoserver 6.x implements only
`source-uri`, not R4's `source` — plain `source` is HTTP 400 not-supported.

**(5) Drop `version`.** A code is mapped into the *earliest* release containing
it, so a Coding stamped `version=2024` won't match a code filed in the 2016 group.

**(5) Drop `targetsystem`.** Verified live: `I50.9` reverse-translates to *both*
`mimic-diagnosis-icd10|I509` and `mimic-diagnosis-icd9|I509`. Pinning
`targetsystem` to the era you'd guess from the ICD system returns one clean match
and silently drops the other. Keep it as a deliberate narrowing tool only.

## TODO

- Re-publish the reverted conformance resources to velonto. It currently
  advertises bindings that contradict the data — a hazard for anyone else using
  that server, independent of what this app does.
