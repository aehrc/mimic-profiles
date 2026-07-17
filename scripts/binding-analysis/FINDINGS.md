# Binding Analysis — Findings & Proposed Changes (Step-4 Working Document)

Status: **all decisions D1–D4 resolved (2026-07-10)** — see Open Decisions section for each resolution; ready for step 4 (apply edits → build → validate).
Produced 2026-07-10 from the full pipeline run: 131 candidate elements scanned
(`work-items.json`), full-data distinct extraction on the HPC node
(`distinct-codes.ndjson`, 38,102 distinct codes, 0 errors), offline coverage
cross-check (`binding-report.{json,md}`), and live Ontoserver validation of the
external-terminology fields. See `RUNBOOK.md` (repo root) for the overall pipeline.

## Results overview (11 populated elements of 131 candidates; 120 had no data)

| Element | Profile | Verdict | Evidence |
|---|---|---|---|
| MedicationAdministration.medication[x] | mimic-medication-administration-icu | **bind** → `mimic-medication` | 100% of 324 distinct / 9.0M rows |
| MedicationDispense.medication[x] | mimic-medication-dispense | **bind** → `mimic-medication` | 100% of 9,372 distinct / 12.7M rows |
| MedicationRequest.medication[x] | mimic-medication-request | **bind** → `mimic-medication` | 100% of 2,890 distinct / 1.9M rows |
| Observation.value[x] | mimic-observation-micro-susc | **bind** → `mimic-micro-interpretation` | 100% of 4 distinct / 1.1M rows |
| MedicationAdministration.medication[x] | mimic-medication-administration | **repair→bind** | `mimic-medication` covers 5,810/5,811 distinct, 99.9966% of 27.7M rows; sole gap: `v3-NullFlavor#UNK` (931 rows) |
| Encounter.priority | mimic-encounter | **bind external** → `v3-ActPriority` | R/EL/EM/UR all valid (Ontoserver-confirmed); existing example binding → upgrade to required |
| Location.physicalType | mimic-location | **bind external** → `location-physical-type` | `wa` valid; example → required |
| Organization.type | mimic-organization | **bind external** → `organization-type` | `prov` valid; example → required |
| Observation.value[x] | mimic-observation-micro-test | **bind external** → `v3-NullFlavor` | MSK (129,756) + NI (3,046) valid; currently unbound. VS is broad (17 codes) — tighter extensional {MSK, NI} VS possible |
| MedicationStatement.medication[x] | mimic-medication-statement-ed | **no binding — new VS needed** | systems `mimic-medication-etc`, `mimic-medication-gsn`, `hl7.org/fhir/sid/ndc` fully disjoint from `mimic-medication` (0% coverage, 19,691 distinct) |
| Observation.component.code | mimic-observation-vital-signs | **no binding — VS repair possible** | BP LOINCs `8480-6`, `8462-4` missing from `mimic-observation-type-vital`/`-ed` (both enumerate explicit LOINCs) |

Methodology notes:
- Coverage gate: candidate VS must cover all *MIMIC* systems observed; external
  system tails count as missing codes (deliberate relaxation — a strict all-systems
  gate would have misfiled admin-hosp as no-binding over the single UNK code).
- Counts (`n`) are per Coding occurrence, from the full MIMIC-on-FHIR Delta data,
  partitioned by `meta.profile`.

## Proposed FSH/JSON changes (step 4, not yet applied)

Ready-to-paste, pending decisions below:

```fsh
// SD_MimicMedicationAdministrationICU.fsh
* medication[x] from $MimicMedicationCodes (required)
// SD_MimicMedicationDispense.fsh
* medication[x] from $MimicMedicationCodes (required)
// SD_MimicMedicationRequest.fsh
* medication[x] from $MimicMedicationCodes (required)
// SD_MimicMedicationAdministration.fsh  (D2: wrapper VS, see below)
* medication[x] from http://mimic.mit.edu/fhir/mimic/ValueSet/mimic-medication-with-unknown (required)
// SD_MimicObservationMicroSusc.fsh (no alias exists for this VS)
* value[x] from http://mimic.mit.edu/fhir/mimic/ValueSet/mimic-micro-interpretation (required)
// SD_MimicEncounter.fsh
* priority from http://terminology.hl7.org/ValueSet/v3-ActPriority (required)
// SD_MimicLocation.fsh
* physicalType from http://hl7.org/fhir/ValueSet/location-physical-type (required)
// SD_MimicOrganization.fsh
* type from http://hl7.org/fhir/ValueSet/organization-type (required)
// SD_MimicObservationMicroTest.fsh — bind ONLY the CodeableConcept choice.
// value[x] also allows free-text string, and R4 bindings apply to string-typed
// elements too; a required binding on value[x] would invalidate every narrative result.
* valueCodeableConcept from http://terminology.hl7.org/ValueSet/v3-NullFlavor (required)
```

Plus (D2, resolved): new wrapper ValueSet `mimic-medication-with-unknown`
(compose: include valueSet `mimic-medication` + include `v3-NullFlavor#UNK`),
bound required on `mimic-medication-administration` only. The shared
`mimic-medication` VS stays untouched, so dispense/request/ICU still reject UNK
(an UNK there would signal an ETL regression).

FSH note: binding on the choice element `medication[x]` (constrained `only
CodeableConcept`) is valid FSH and matches the SDs' existing spelling.

## Open decisions (answer these to unblock step 4)

- **D1 — RESOLVED (2026-07-10)**: apply all 8 required bindings. Micro-test uses
  the standard `v3-NullFlavor` VS (not a local {MSK, NI} VS) and binds
  `valueCodeableConcept` specifically, not `value[x]`, so free-text string
  results stay valid.
- **D2 — RESOLVED (2026-07-10)**: the 931 UNK rows are intentional upstream ETL
  output (null flavor for un-coded drugs), not a data error; the current profile
  was merely unbound. Fix via new wrapper VS `mimic-medication-with-unknown`
  (includes `mimic-medication` + `v3-NullFlavor#UNK`), bound `required` on
  admin-hosp only. Shared `mimic-medication` VS unchanged.
- **D3 — RESOLVED (2026-07-10)**: no merged `mimic-medication-ed` VS. Instead,
  **per-slice bindings** on the coding slices the SD already defines
  (`SD_MimicMedicationStatementED.fsh`), plus **closed slicing**:
  ```fsh
  * medicationCodeableConcept.coding ^slicing.rules = #closed   // was #open; only gsn/ndc/etc systems allowed
  * medicationCodeableConcept.coding[gsnCode] from $MimicMedicationGSN (required)      // VS already in IG
  * medicationCodeableConcept.coding[etccodeCode] from $MimicMedicationETC (required)  // VS already in IG
  // ndcCode slice: UNBOUND (option c) — system pinned to sid/ndc by the slice, code value unvalidated
  ```
  Rationale: per-slice validates each coding against its own system (a required
  binding on the whole CodeableConcept would pass if *any one* coding matched),
  reuses the two existing IG ValueSets, and sidesteps the text-only-row trap
  (`text` is 1..1 but ~68% of rows have no codings; a required CodeableConcept
  binding would invalidate them). No merged-VS binding on the CodeableConcept.
  - **NDC slice — option (c) chosen, (b) documented for later**: NDC
    (`http://hl7.org/fhir/sid/ndc`) is loaded on neither velonto.dw.csiro.au/fhir
    nor tx.ontoserver.csiro.au (verified 2026-07-10: CodeSystem search total=0,
    $lookup/$expand 404 on both), so a whole-system include (option a) is dead.
    **Option (b), deferred:** generate an extensional VS (e.g.
    `mimic-medication-ndc-observed`) enumerating the 9,312 observed codes — all
    clean 11-digit numerics, no junk — and bind it required on the slice.
    Ontoserver can expand/membership-check an enumerated compose without the
    CodeSystem (unknown-system warnings only, no display checks). Regenerable
    mechanically from `distinct-codes.ndjson` when a new MIMIC release lands.
    Chosen for now: **(c) leave the slice unbound** — closed slicing still
    enforces the system URI; code-level NDC validation adds little since no
    server can resolve NDC semantics anyway.
- **D4 — RESOLVED (2026-07-10)**: bind `component.code`, but via a **dedicated
  two-code ValueSet** rather than adding the BP child LOINCs to the shared
  `mimic-observation-type-vital` (that VS also binds top-level `Observation.code`;
  adding `8480-6`/`8462-4` there would let a bare top-level "systolic BP"
  Observation validate, which the data never contains — same shared-VS-pollution
  principle as D2/D3):
  ```fsh
  // VS_Valuesets.fsh
  ValueSet: MimicObservationComponentVital
  Id: mimic-observation-component-vital
  Title: "MIMIC-ED Observation Component Types Value Set"
  Description: "LOINC codes appearing in Observation.component.code of the vital-signs profile (BP panel children)."
  * $LNC#8480-6 "Systolic blood pressure"
  * $LNC#8462-4 "Diastolic blood pressure"

  // SD_MimicObservationVitalSigns.fsh
  * component.code from MimicObservationComponentVital (required)
  ```
  `mimic-observation-type-vital` and `-ed` stay untouched. Evidence: 3.98M
  component rows, exactly these two LOINCs, 100% clean.

## Consumer-side note (Felix's pipeline)

The downstream consumer merges profile-flavored NDJSON into plain resource types
(regex strips `Mimic…(ED|ICU|Chartevents|…)` from file names). Because bindings
differ per profile on the same element (e.g. `Observation.value[x]`: micro-susc →
`mimic-micro-interpretation` vs micro-test → `v3-NullFlavor`), **field→VS resolution
must key on `meta.profile`** (or source-file flavor), never resource type alone.
`binding-report.json` is the machine-readable artifact for this, including the
120 no-data elements and any that end up unbound.

Additional consumer findings from D3 (statement-ed / medrecon, 8.1M rows):
- Codings are **parallel, not alternative**: coded rows carry GSN + NDC (+ ETC)
  together (occurrence counts 2.587M vs 2.581M — they co-travel). Leaving the
  NDC slice unbound does NOT exclude rows from code-based matching; such rows
  still match via GSN/ETC. Only hypothetical NDC-only rows would be missed —
  count symmetry suggests ~none, but confirming needs a row-level co-occurrence
  query on the HPC data.
- NDC is semantically unusable for entity→code expansion regardless of binding:
  no server hosts the CodeSystem, no displays in the data. For entities like
  "antibiotic administration", **ETC (therapeutic classification) is the semantic
  axis**; GSN/NDC are product identifiers.
- **~68% of medrecon rows (~5.5M of 8.1M) have no codings at all** — only the
  mandatory free-text drug name. Any purely code-driven WHERE clause on this
  table silently drops two-thirds of it; a text-matching strategy (or accepted
  recall loss) is required regardless of bindings.

## Remaining steps after decisions

1. Apply FSH/JSON edits → `sushi` + `_genonce.sh` → `validator_cli` on the IG examples.
2. Spot-check 2–3 bindings via terminology server `$expand`.
3. Hand `output/package.tgz` (version `1.3.0-csiro.1`) to the terminology-server admin.
4. Upstream PR later: FSH diffs + this document + `binding-report.json` as evidence;
   expect debate on `required` vs `extensible` (MIMIC releases could add codes).
