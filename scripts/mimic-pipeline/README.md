# MIMIC pipeline

Every modification applied to the MIMIC-on-FHIR data, as an ordered sequence of
steps. One script per step, named `step<N>_<what>.py`.

| # | Script | What it does |
|---|--------|--------------|
| 1 | `step1_ndjson_to_delta.py` | NDJSON distribution → one Delta table per FHIR resource type |

**Step 1 is the only step allowed to use the Pathling library directly** — it
creates the warehouse the server reads from, so there is no server to go
through yet. Every later step goes through the Pathling server's FHIR API.

## Step 1

```bash
uv run python step1_ndjson_to_delta.py \
    --source /Users/nau025/warehouses/mimic-iv-demo \
    --target /Users/nau025/warehouses/mimic-iv-demo/delta
```

MIMIC ships one file per profile flavour (`MimicObservationChartevents`,
`MimicMedicationAdministrationICU`, …) and Pathling stores one table per
resource type, so the demo's 30 files collapse into 13 tables. The resource
type is read from each file's first line rather than matched off the file name
— same `file_name_mapper` mechanism the Pathling MIMIC tutorial uses, without a
list of Mimic suffixes to maintain. The flavour survives on `meta.profile`,
which `../merged_profile_provisioning/` reads later.

The `.ndjson.gz` files are read in place, no decompression. Note that
Pathling's `extension` argument globs on the **last** extension segment only,
so it must be `gz` — passing `ndjson.gz` matches no files, and fails by writing
an empty warehouse rather than by raising.

The Pathling server serves whatever is mounted at
`/usr/share/warehouse/default`; check it matches `--target` with
`docker inspect pathling --format '{{json .Mounts}}'`.
