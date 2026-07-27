"""Apply a merged-profile terminology facade to FHIR resources whose sub-type
StructureDefinitions were collapsed into a single Delta table during data
preprocessing.

Background: preprocessing merges several MIMIC Observation sub-resources
(labevents, chartevents, vital-signs, ...) into one `Observation` resource
because Pathling requires a single resource type. Each sub-resource carried its
own `meta.profile` (a distinct StructureDefinition binding one ValueSet at
`Observation.code`). After the merge the table carries N distinct profiles, and
`code_mapping._resolve_profile` — which needs exactly one profile to anchor the
find-code binding — fails.

The merged StructureDefinition and its grouping ValueSet are NOT generated or
uploaded by this script. They are authored and published as ordinary IG
content (FSH) in the mimic-profiles repo — see
`input/fsh/SD_MimicObservationMerged.fsh` and
`input/fsh/VS_MimicObservationMerged.fsh` for the Observation example —
because this script has no business writing to the velonto terminology
server; that publication is the IG maintainer's responsibility via the IG's
own build/publish pipeline. This script only ever reads from the terminology
server (to verify what's already published, or to document what a merge
would need) and writes to the local Delta table.

This script has four modes:

  document   Read-only. Discover the sub-type profiles present in the data
             for --resource, resolve each one's `<Resource>.code` binding
             ValueSet from the terminology server, and write a JSON artifact
             (plus a suggested FSH draft) describing what the equivalent of
             `SD_Mimic<Resource>Merged.fsh` / `VS_Mimic<Resource>Merged.fsh`
             would need to contain for that resource. This is the discovery
             step for resources other than Observation — it never writes to
             the terminology server or to Delta; it only documents what a
             human then authors by hand in FSH. If --resource is omitted and
             --data is a warehouse root, every `<Resource>.parquet` table
             directly under it is swept in one run; resources whose data
             carries fewer than 2 distinct profiles (nothing to merge) are
             reported but skipped, no artifact written.

  data-map   Overwrite `meta.profile` on the merged Delta table so every row
             that carried one of the sub-type profiles now carries the single
             merged StructureDefinition URL (as published by the IG). In
             place; --dry-run reports the matched-row count and a before
             sample without writing. Runs identically whether --data points
             at local demo data or a full-MIMIC table on an isolated HPC node
             (no network access needed — this mode never talks to a FHIR
             server). If --resource is omitted and --data is a warehouse
             root, every `<Resource>.parquet` table directly under it is
             swept in one run, same as `document`.

  verify     Probe the data: print a small sample of `meta.profile` and, for
             each distinct profile present, resolve its StructureDefinition on
             the terminology server and print the `<Resource>.code` binding
             ValueSet (and whether that ValueSet itself resolves). Read-only,
             print-only — no writes. Run after `data-map` to confirm the rows
             now point at the merged StructureDefinition and that it binds
             `<Resource>.code` on the server as expected.

  import     Read-only w.r.t. Delta — never touches Spark/the local
             warehouse. Meant to run from a separate, network-connected
             machine after `data-map` has already remapped the data in place
             on the (possibly network-isolated) HPC node. Discovers which
             resources need importing by scanning the subfolders of
             --out-dir (the artifacts/ tree a prior `document` run wrote —
             one subfolder per resource that actually needed merging), builds
             a single FHIR `$import` request (inputFormat=Parquet,
             saveMode=overwrite, one input entry per discovered resource at
             `<--import-base-url>/<Resource>.parquet`), POSTs it to
             --pathling-url with `Prefer: respond-async`, and polls the
             status URL until the job completes. --dry-run prints the built
             request without POSTing.

The merged URLs are a pure function of (--base-url, --resource); --base-url
still defaults to the felix.masters scratch namespace rather than the IG's
real canonical (http://mimic.mit.edu/fhir/mimic) — a deliberate reminder that
this merged-profile facade is local tooling, not something published back to
the upstream MIMIC IG.

Example:
  # Sweep every resource in the warehouse at once.
  uv run python scripts/merged_profile_provisioning/provision.py \
    --mode document \
    --data /path/to/spark-warehouse \
    --out-dir scripts/merged_profile_provisioning/artifacts

  # Or just one resource.
  uv run python scripts/merged_profile_provisioning/provision.py \
    --resource Condition --mode document \
    --data /path/to/spark-warehouse/Condition.parquet \
    --out-dir scripts/merged_profile_provisioning/artifacts/Condition

  uv run python scripts/merged_profile_provisioning/provision.py \
    --resource Observation --mode data-map \
    --data /path/to/spark-warehouse/Observation.parquet \
    --dry-run

  # From a network-connected machine, after data-map ran on the HPC node:
  uv run python scripts/merged_profile_provisioning/provision.py \
    --mode import \
    --out-dir scripts/merged_profile_provisioning/artifacts \
    --import-base-url s3a://my-bucket/mimic-warehouse \
    --token "$PATHLING_ACCESS_TOKEN"
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import httpx

# Driver memory must be set before the Spark JVM launches; in local/client mode
# it cannot be changed via SparkConf after the gateway starts. Set it here (before
# any Pathling/Spark import triggers the gateway) as a safety net for large tables.
os.environ.setdefault("PYSPARK_SUBMIT_ARGS", "--driver-memory 12g pyspark-shell")

_DEFAULT_BASE_URL = "https://felix.masters/fhir"
_DEFAULT_TERM_SERVER = "https://velonto.dw.csiro.au/fhir"
_DEFAULT_PATHLING_URL = "https://pathling.dw.csiro.au/fhir/"
_HTTP_TIMEOUT = httpx.Timeout(connect=10.0, read=120.0, write=120.0, pool=10.0)

# $import data is already Pathling-schema Parquet (the merged Delta table
# itself) — no NDJSON conversion needed.
_IMPORT_FORMAT = "application/vnd.apache.parquet"
# Full-MIMIC imports may run long; polling has no natural stopping point of
# its own, so bound it generously rather than not at all.
_IMPORT_POLL_TIMEOUT = 5 * 3600.0

# `document` mode's job is to help hand-author FSH for the real IG, so its
# suggested names/ids follow the IG's own canonical and naming convention
# (mimic-<resource>-*), independent of --base-url (which stays the
# felix.masters scratch namespace used by data-map/verify).
_IG_CANONICAL = "http://mimic.mit.edu/fhir/mimic"


# --------------------------------------------------------------------------- #
# Naming — merged URLs are a pure function of (base_url, resource).
# --------------------------------------------------------------------------- #
def _grouping_vs_url(base_url: str, resource: str) -> str:
    return f"{base_url.rstrip('/')}/ValueSet/{resource.lower()}-merged-code"


def _merged_sd_url(base_url: str, resource: str) -> str:
    return f"{base_url.rstrip('/')}/StructureDefinition/{resource.lower()}-merged"


def _suggested_fsh_names(resource: str) -> dict[str, str]:
    """The FSH item names/ids `document` mode suggests, matching this IG's
    existing convention for the Observation sub-types (e.g.
    `mimic-observation-labevents`)."""
    lower = resource.lower()
    return {
        "profile_name": f"Mimic{resource}Merged",
        "profile_id": f"mimic-{lower}-merged",
        "valueset_name": f"Mimic{resource}MergedCode",
        "valueset_id": f"mimic-{lower}-merged-code",
    }


# --------------------------------------------------------------------------- #
# Spark / Delta
# --------------------------------------------------------------------------- #
def _resolve_table_path(data: str, resource: str) -> str:
    """`--data` may be the specific Delta table OR the warehouse root. A Delta
    table has a `_delta_log/`; a warehouse root holds one `<Resource>.parquet`
    table per resource type."""
    p = Path(data)
    if (p / "_delta_log").is_dir():
        return str(p)
    for candidate in (p / f"{resource}.parquet", p / resource):
        if (candidate / "_delta_log").is_dir():
            return str(candidate)
    raise FileNotFoundError(
        f"--data {data!r} is neither a Delta table nor a warehouse root containing "
        f"{resource}.parquet (looked for a _delta_log/ dir)"
    )


def _list_resource_tables(data: str) -> list[str]:
    """Every `<Resource>.parquet` Delta table directly under a warehouse root
    (resource name = directory name with the `.parquet` suffix stripped).
    Used by `document` mode to sweep all resources in one run when --resource
    is omitted. Non-FHIR-resource directories in a warehouse (e.g. views like
    `patient_sofa`) simply won't end in `.parquet` with a `_delta_log/`, so
    they're naturally skipped."""
    root = Path(data)
    resources = []
    for child in sorted(root.iterdir()):
        if child.is_dir() and child.name.endswith(".parquet") and (child / "_delta_log").is_dir():
            resources.append(child.name[: -len(".parquet")])
    return resources


def _build_spark():
    """`delta-spark` is not installed, so a hand-built SparkSession cannot read
    the Delta warehouse. Pathling bundles Delta and its JVM libraries, so we let
    `PathlingContext.create()` build the session and reuse `pc.spark` for the raw
    Delta read/write. (Passing a pre-existing session INTO Pathling would instead
    fail — the classpath dependency runs the other way.)"""
    from pathling import PathlingContext

    pc = PathlingContext.create()
    return pc.spark


def _discover_subtype_profiles(spark, data_path: str, exclude_urls: set[str]) -> list[str]:
    """The same logic as `_resolve_profile`'s query, run directly against Delta:
    the distinct non-null `meta.profile` values, minus any merged URL (so a
    re-run after `data-map` is a no-op rather than folding the facade into
    itself)."""
    from pyspark.sql import functions as F

    df = spark.read.format("delta").load(data_path)
    rows = (
        df.select(F.explode("meta.profile").alias("profile"))
        .where(F.col("profile").isNotNull())
        .distinct()
        .collect()
    )
    profiles = sorted({r["profile"] for r in rows} - exclude_urls)
    return profiles


# --------------------------------------------------------------------------- #
# Terminology server (read-only — used by `verify` only)
# --------------------------------------------------------------------------- #
class TermClient:
    def __init__(self, base_url: str, token: str | None, verify: bool = True) -> None:
        self._base = base_url.rstrip("/")
        headers = {"Accept": "application/fhir+json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self._http = httpx.Client(headers=headers, timeout=_HTTP_TIMEOUT, verify=verify)

    def _search_by_url(self, resource_type: str, url: str) -> dict[str, Any] | None:
        # `_summary=false` is required: the server otherwise returns SUBSETTED
        # resources with `differential`/`snapshot` (and thus the code binding) stripped.
        resp = self._http.get(f"{self._base}/{resource_type}", params={"url": url, "_summary": "false"})
        resp.raise_for_status()
        bundle = resp.json()
        for entry in bundle.get("entry", []) or []:
            resource = entry.get("resource")
            if resource and resource.get("url") == url:
                return resource
        # Fall back to the first entry if the server drops the version-less echo.
        entries = bundle.get("entry", []) or []
        return entries[0]["resource"] if entries else None

    def get_structure_definition(self, url: str) -> dict[str, Any]:
        sd = self._search_by_url("StructureDefinition", url)
        if sd is None:
            raise LookupError(f"StructureDefinition not found on term server: {url}")
        return sd

    def get_value_set(self, url: str) -> dict[str, Any]:
        vs = self._search_by_url("ValueSet", url.split("|", 1)[0])
        if vs is None:
            raise LookupError(f"ValueSet not found on term server: {url}")
        return vs


# Element candidates to try, in order, when looking for a merged resource's
# "the one coded element downstream code search cares about". `.code` covers
# most resource types; the Medication family has no `.code` element at all —
# they carry their code on the `medication[x]` CodeableConcept instead, and at
# least one MIMIC sub-type (mimic-medication-dispense-ed) narrows that further
# to `medication[x].coding` rather than binding the whole CodeableConcept.
# Tried automatically per profile, deepest-first-found wins per profile — no
# CLI flag needed. See `_code_binding_valueset` for why order here doesn't
# need to be "shallowest first": only `required`-strength bindings count, so
# an inherited/unconstrained FHIR-core `example` binding at a shallower path
# can never shadow a real MIMIC override at a deeper one.
_CODE_ELEMENT_CANDIDATES = ["code", "medication[x]", "medication[x].coding"]


def _code_binding_valueset(sd: dict[str, Any], candidate_paths: list[str]) -> tuple[str | None, str | None]:
    """The (matched element path, canonical ValueSet) for the first of
    `candidate_paths` (each already resource-qualified, e.g.
    `MedicationAdministration.medication[x]`) that has a `required`-strength
    binding in this StructureDefinition — snapshot first, then differential,
    candidates tried in the given order.

    Only `required` bindings count. A choice-type element like `medication[x]`
    always has a snapshot entry even when a profile doesn't constrain it —
    inherited straight from the base FHIR resource, at `example` strength,
    pointing at a generic (non-MIMIC) ValueSet. Accepting any-strength binding
    would treat that inherited placeholder as if it were a real MIMIC
    override; requiring `required` strength filters it out and lets a deeper
    candidate (e.g. `.coding`) actually carrying the MIMIC-specific binding be
    found instead."""
    for candidate_path in candidate_paths:
        for section in ("snapshot", "differential"):
            for element in sd.get(section, {}).get("element", []) or []:
                if element.get("path") != candidate_path:
                    continue
                binding = element.get("binding", {})
                if binding.get("strength") != "required":
                    continue
                vs = binding.get("valueSet")
                if vs:
                    return candidate_path, vs.split("|", 1)[0]
    return None, None


# --------------------------------------------------------------------------- #
# Modes
# --------------------------------------------------------------------------- #
def _write_document_artifacts(out_dir: str, resource: str, summary: dict[str, Any], fsh_draft: dict[str, str]) -> None:
    path = Path(out_dir)
    path.mkdir(parents=True, exist_ok=True)

    summary_fp = path / f"{resource}.summary.json"
    summary_fp.write_text(json.dumps(summary, indent=2))
    print(f"Wrote {summary_fp}")

    for suffix, content in fsh_draft.items():
        draft_fp = path / f"{resource}.{suffix}.suggested.fsh"
        draft_fp.write_text(content)
        print(f"Wrote {draft_fp}")


def _document_resource(spark, term: "TermClient", args: argparse.Namespace, resource: str) -> dict[str, Any]:
    """Read-only: discover the sub-type profiles behind a merged `resource`
    table and what each one binds its coded element to. Tries `.code` first,
    falling back automatically to `medication[x]` and then `medication[x].coding`
    (see `_CODE_ELEMENT_CANDIDATES`) — only `required`-strength bindings count,
    so an inherited/generic FHIR-core binding never masks a real deeper MIMIC
    override. No sub-types are excluded by name (e.g. no blanket "ED" filter —
    ED-sourced data legitimately belongs in some merges, e.g. Observation, and
    not others; that's a per-resource FSH-authoring decision, not something
    this script should guess). Returns a result dict with `status` one of:
      "empty"        no meta.profile values at all (bad path, or empty table)
      "single"       fewer than 2 distinct sub-type profiles — nothing to merge
      "documented"   2+ distinct sub-type profiles — summary + suggested FSH produced
    Never writes to the terminology server; never writes to Delta."""
    names = _suggested_fsh_names(resource)
    already_merged = {_merged_sd_url(args.base_url, resource), _grouping_vs_url(args.base_url, resource)}
    candidate_paths = [f"{resource}.{c}" for c in _CODE_ELEMENT_CANDIDATES]

    table_path = _resolve_table_path(args.data, resource)
    profiles = _discover_subtype_profiles(spark, table_path, already_merged)

    if not profiles:
        return {"resource": resource, "status": "empty", "sub_type_count": 0}
    if len(profiles) < 2:
        return {"resource": resource, "status": "single", "sub_type_count": len(profiles)}

    print(f"Discovered {len(profiles)} sub-type profile(s) for {resource}:")
    for p in profiles:
        print(f"  - {p}")

    entries: list[dict[str, Any]] = []
    kept_vs_urls: list[str] = []
    matched_elements: set[str] = set()
    for profile in profiles:
        entry: dict[str, Any] = {
            "structure_definition_url": profile,
            "code_binding_valueset": None,
            "code_element": None,
            "note": None,
        }
        try:
            sd = term.get_structure_definition(profile)
        except (LookupError, httpx.HTTPError) as e:
            entry["note"] = f"StructureDefinition did not resolve on {args.term_server}: {e}"
            print(f"WARNING: {profile} did not resolve — {e}", file=sys.stderr)
            entries.append(entry)
            continue
        matched_path, vs_url = _code_binding_valueset(sd, candidate_paths)
        if not vs_url:
            entry["note"] = f"no required-strength binding ValueSet found at any of {candidate_paths}"
            print(f"WARNING: {profile} has no required-strength binding at any of {candidate_paths}", file=sys.stderr)
            entries.append(entry)
            continue
        entry["code_binding_valueset"] = vs_url
        entry["code_element"] = matched_path
        kept_vs_urls.append(vs_url)
        matched_elements.add(matched_path[len(resource) + 1 :])
        entries.append(entry)

    # If sub-types disagree on binding depth (e.g. one binds the whole
    # CodeableConcept, another only `.coding` within it), report the deepest
    # — safe because a binding on a CodeableConcept also constrains its
    # `.coding` entries, so the deepest path is compatible with all of them —
    # but flag the disagreement explicitly rather than silently picking one.
    code_element = max(matched_elements, key=lambda e: e.count(".")) if matched_elements else _CODE_ELEMENT_CANDIDATES[0]
    code_path = f"{resource}.{code_element}"
    depth_mismatch = len(matched_elements) > 1

    print(f"Suggested profile:  {names['profile_name']} (Id: {names['profile_id']})")
    print(f"Suggested ValueSet: {names['valueset_name']} (Id: {names['valueset_id']})")
    print(f"{len(kept_vs_urls)}/{len(profiles)} sub-type profile(s) resolved a required-strength binding to union.")
    if depth_mismatch:
        print(
            f"NOTE: sub-type profiles bind at different depths ({sorted(matched_elements)}) — "
            f"using the deepest ({code_element}) for the suggested merge; review before committing.",
            file=sys.stderr,
        )

    summary = {
        "resource": resource,
        "term_server": args.term_server,
        "code_element": code_element,
        "code_element_depth_mismatch": sorted(matched_elements) if depth_mismatch else None,
        "sub_type_profiles": entries,
        "suggested_profile": {"name": names["profile_name"], "id": names["profile_id"]},
        "suggested_valueset": {
            "name": names["valueset_name"],
            "id": names["valueset_id"],
            "includes": kept_vs_urls,
        },
    }

    mismatch_warning = (
        f' WARNING: sub-type profiles bind at different depths ({sorted(matched_elements)}); '
        f"this suggested `{code_element}` binding is a best guess (deepest wins) — verify."
        if depth_mismatch
        else ""
    )
    profile_fsh = (
        f"Profile:        {names['profile_name']}\n"
        f"Parent:         {resource}\n"
        f"Id:             {names['profile_id']}\n"
        f'Title:          "MIMIC {resource} (merged sub-types)"\n'
        f'Description:    "SUGGESTED DRAFT from `provision.py --mode document` — review before committing. '
        f"Facade profile for downstream pipelines that merge every MIMIC {resource} sub-type into a single "
        f'{resource} resource. Binds {code_path} to the union of all sub-type code ValueSets.{mismatch_warning}"\n\n'
        f"// binding to MIMIC terminology\n"
        f"* {code_element} from {names['valueset_name']}\n"
    )
    valueset_includes = "\n".join(f'* include codes from valueset "{vs}"' for vs in kept_vs_urls) or (
        "// no sub-type binding ValueSets resolved — nothing to include"
    )
    valueset_fsh = (
        f"ValueSet: {names['valueset_name']}\n"
        f"Id: {names['valueset_id']}\n"
        f'Title: "MIMIC {resource} code (merged sub-types)"\n'
        f'Description: "SUGGESTED DRAFT from `provision.py --mode document` — review before committing. '
        f"Union of the per-sub-type {code_path} binding ValueSets, for use by {names['profile_name']}. "
        f'Grouping ValueSet — references only, no own codes.{mismatch_warning}"\n\n'
        f"{valueset_includes}\n"
    )

    return {
        "resource": resource,
        "status": "documented",
        "sub_type_count": len(profiles),
        "summary": summary,
        "profile_fsh": profile_fsh,
        "valueset_fsh": valueset_fsh,
    }


def run_document(args: argparse.Namespace) -> int:
    """Orchestrates `_document_resource` over either a single --resource or,
    if omitted, every `<Resource>.parquet` table found under --data (which
    must then be a warehouse root)."""
    if args.resource:
        resources = [args.resource]
    else:
        resources = _list_resource_tables(args.data)
        if not resources:
            print(
                f"ERROR: no <Resource>.parquet Delta table found directly under {args.data!r}. "
                "Pass --resource explicitly if --data is a specific table rather than a warehouse root.",
                file=sys.stderr,
            )
            return 1
        print(f"Sweeping {len(resources)} resource table(s) under {args.data}: {', '.join(resources)}\n")

    spark = _build_spark()
    term = TermClient(args.term_server, args.token, verify=not args.insecure)
    results: list[dict[str, Any]] = []
    try:
        for resource in resources:
            print(f"=== {resource} ===")
            results.append(_document_resource(spark, term, args, resource))
            print()
    finally:
        spark.stop()

    print("Summary:")
    for r in results:
        print(f"  {r['resource']:<28} {r['status']:<10} distinct sub-type profiles={r['sub_type_count']}")

    documented = [r for r in results if r["status"] == "documented"]
    if not documented:
        print("\nNothing to document — no resource had 2+ distinct meta.profile values.")
        return 0

    if args.out_dir:
        for r in documented:
            out_dir = str(Path(args.out_dir) / r["resource"])
            _write_document_artifacts(out_dir, r["resource"], r["summary"], {"profile": r["profile_fsh"], "valueset": r["valueset_fsh"]})
    else:
        for r in documented:
            print(f"\n--- {r['resource']} summary JSON ---")
            print(json.dumps(r["summary"], indent=2))
            print(f"\n--- {r['resource']} suggested profile FSH ---")
            print(r["profile_fsh"])
            print(f"--- {r['resource']} suggested valueset FSH ---")
            print(r["valueset_fsh"])

    print(
        "\nNOTE: this is documentation only, not IG source. Hand-author the real "
        "SD_Mimic<Resource>Merged.fsh / VS_Mimic<Resource>Merged.fsh files (or reuse existing FSH names for "
        "the referenced ValueSets rather than the raw URLs above) before this ships in the IG."
    )
    return 0


def _data_map_resource(spark, args: argparse.Namespace, resource: str) -> dict[str, Any]:
    """Runs the meta.profile remap for one resource table. Returns a summary
    dict with `status` one of: "empty" (nothing to remap), "dry-run",
    "remapped"."""
    merged_sd_url = _merged_sd_url(args.base_url, resource)
    grouping_url = _grouping_vs_url(args.base_url, resource)
    table_path = _resolve_table_path(args.data, resource)

    profiles = _discover_subtype_profiles(spark, table_path, {merged_sd_url, grouping_url})
    if not profiles:
        print(
            f"No sub-type profiles to remap in {table_path} "
            f"(already merged, or empty). Nothing to do.",
            file=sys.stderr,
        )
        return {"resource": resource, "status": "empty", "matched": 0}

    print(f"Remapping meta.profile -> {merged_sd_url}")
    print(f"Matching rows whose meta.profile intersects {len(profiles)} sub-type profile(s):")
    for p in profiles:
        print(f"  - {p}")

    # A targeted Delta UPDATE rewrites only the data files containing matched
    # rows (memory bounded by file size, not table size) and handles the
    # in-place transaction itself — no full read, no localCheckpoint, no
    # whole-table overwrite. `SET meta.profile` preserves the other meta fields.
    def _q(s: str) -> str:
        return s.replace("'", "''")

    profiles_sql = ", ".join(f"'{_q(p)}'" for p in profiles)
    cond_sql = f"arrays_overlap(meta.profile, array({profiles_sql}))"
    path_sql = table_path.replace("`", "``")

    matched = spark.sql(
        f"SELECT count(*) AS c FROM delta.`{path_sql}` WHERE {cond_sql}"
    ).collect()[0]["c"]
    print(f"\nMatched {matched} rows.")

    if args.dry_run:
        print("\nBefore sample (meta.profile of matched rows):")
        spark.sql(
            f"SELECT meta.profile FROM delta.`{path_sql}` WHERE {cond_sql}"
        ).show(5, truncate=False)
        print("DRY RUN: nothing written.")
        return {"resource": resource, "status": "dry-run", "matched": matched}

    spark.sql(
        f"UPDATE delta.`{path_sql}` "
        f"SET meta.profile = array('{_q(merged_sd_url)}') "
        f"WHERE {cond_sql}"
    )
    print(f"Remapped {matched} rows in place to {table_path}")
    return {"resource": resource, "status": "remapped", "matched": matched}


def run_data_map(args: argparse.Namespace) -> int:
    """Orchestrates `_data_map_resource` over either a single --resource or,
    if omitted, every `<Resource>.parquet` table found under --data (which
    must then be a warehouse root) — mirroring `run_document`'s sweep-all
    behavior."""
    if args.resource:
        resources = [args.resource]
    else:
        resources = _list_resource_tables(args.data)
        if not resources:
            print(
                f"ERROR: no <Resource>.parquet Delta table found directly under {args.data!r}. "
                "Pass --resource explicitly if --data is a specific table rather than a warehouse root.",
                file=sys.stderr,
            )
            return 1
        print(f"Sweeping {len(resources)} resource table(s) under {args.data}: {', '.join(resources)}\n")

    sweeping = len(resources) > 1
    spark = _build_spark()
    try:
        results = []
        for resource in resources:
            if sweeping:
                print(f"=== {resource} ===")
            results.append(_data_map_resource(spark, args, resource))
            if sweeping:
                print()
    finally:
        spark.stop()

    if sweeping:
        print("Summary:")
        for r in results:
            print(f"  {r['resource']:<28} {r['status']:<10} matched={r['matched']}")

    return 0


def run_verify(args: argparse.Namespace) -> int:
    candidate_paths = [f"{args.resource}.{c}" for c in _CODE_ELEMENT_CANDIDATES]

    table_path = _resolve_table_path(args.data, args.resource)
    spark = _build_spark()
    try:
        df = spark.read.format("delta").load(table_path)
        print(f"Sample of meta.profile (drives the {' / '.join(candidate_paths)} binding):")
        df.select("meta.profile").show(5, truncate=False)
        # No exclusions: verify wants to see the merged profile too.
        profiles = _discover_subtype_profiles(spark, table_path, set())
    finally:
        spark.stop()

    if not profiles:
        print(f"No meta.profile values found in {args.data}.")
        return 0

    print(f"{len(profiles)} distinct profile(s) in the data; resolving each on {args.term_server}:")
    term = TermClient(args.term_server, args.token, verify=not args.insecure)
    for profile in profiles:
        print(f"\n- profile: {profile}")
        try:
            sd = term.get_structure_definition(profile)
        except (LookupError, httpx.HTTPError) as e:
            print(f"    StructureDefinition did not resolve on server: {e}")
            continue
        matched_path, vs_url = _code_binding_valueset(sd, candidate_paths)
        if not vs_url:
            print(f"    StructureDefinition resolved but has no binding ValueSet at any of {candidate_paths}")
            continue
        print(f"    {matched_path} binds -> {vs_url}")
        try:
            vs = term.get_value_set(vs_url)
        except (LookupError, httpx.HTTPError) as e:
            print(f"    binding ValueSet did not resolve on server: {e}")
            continue
        includes = vs.get("compose", {}).get("include", []) or []
        print(f"    binding ValueSet resolves -> {vs.get('url')} ({len(includes)} compose.include entries)")
    return 0


def _discover_artifact_resources(out_dir: str) -> list[str]:
    """The resources `--mode import` should import: one per subfolder under
    --out-dir, matching exactly what `_write_document_artifacts` creates for
    each `document`-mode resource that had 2+ sub-type profiles to merge."""
    root = Path(out_dir)
    if not root.is_dir():
        raise FileNotFoundError(
            f"--out-dir {out_dir!r} does not exist. Run --mode document first to produce it."
        )
    return sorted(child.name for child in root.iterdir() if child.is_dir())


def _build_import_parameters(resources: list[str], import_base_url: str) -> dict[str, Any]:
    """A FHIR Parameters $import request: Parquet input, overwrite each
    resource type, one input entry per discovered resource at
    `<import_base_url>/<Resource>.parquet` (the same `<Resource>.parquet`
    warehouse convention `_resolve_table_path` uses locally)."""
    base = import_base_url.rstrip("/")
    parameters: list[dict[str, Any]] = [
        {"name": "inputFormat", "valueCoding": {"code": _IMPORT_FORMAT}},
        {"name": "saveMode", "valueCoding": {"code": "overwrite"}},
    ]
    for resource in resources:
        parameters.append(
            {
                "name": "input",
                "part": [
                    {"name": "resourceType", "valueCoding": {"code": resource}},
                    {"name": "url", "valueUrl": f"{base}/{resource}.parquet"},
                ],
            }
        )
    return {"resourceType": "Parameters", "parameter": parameters}


def _poll_import_job(http: httpx.Client, status_url: str, timeout: float) -> dict[str, Any]:
    """Poll the async job's status URL (per the FHIR Async Request Pattern)
    until it returns 200, backing off from 2s up to 30s between checks."""
    start = time.monotonic()
    interval = 2.0
    while time.monotonic() - start < timeout:
        resp = http.get(status_url)
        if resp.status_code == 200:
            return resp.json()
        if resp.status_code == 202:
            progress = resp.headers.get("X-Progress", "unknown")
            print(f"  in progress: {progress}")
            time.sleep(interval)
            interval = min(interval * 1.5, 30.0)
            continue
        resp.raise_for_status()
    raise TimeoutError(f"$import job timed out after {timeout} seconds (status URL: {status_url})")


def run_import(args: argparse.Namespace) -> int:
    """Never touches Spark/Delta. Normally reads the artifacts/ tree left by
    a prior `document` run to decide which resources to import; --resources
    overrides that discovery with an explicit list (e.g. when data-map ran
    standalone — such as directly against a warehouse root, skipping
    document — so no artifacts/ tree exists to read). Then drives Pathling's
    $import operation end to end (POST + async poll)."""
    if args.resources:
        resources = args.resources
        print(f"Using explicit --resources list ({len(resources)}): {', '.join(resources)}")
    else:
        resources = _discover_artifact_resources(args.out_dir)
        if not resources:
            print(
                f"No resource subfolders found under {args.out_dir!r} — nothing to import. "
                "Run --mode document first, or pass --resources explicitly.",
                file=sys.stderr,
            )
            return 1
        print(f"Discovered {len(resources)} resource(s) to import from {args.out_dir}: {', '.join(resources)}")
    parameters = _build_import_parameters(resources, args.import_base_url)
    import_url = f"{args.pathling_url.rstrip('/')}/$import"

    if args.dry_run:
        print(f"\nDRY RUN: would POST the following Parameters to {import_url}:")
        print(json.dumps(parameters, indent=2))
        return 0

    headers = {
        "Content-Type": "application/fhir+json",
        "Accept": "application/fhir+json",
        "Prefer": "respond-async",
    }
    if args.token:
        headers["Authorization"] = f"Bearer {args.token}"

    with httpx.Client(headers=headers, timeout=_HTTP_TIMEOUT, verify=not args.insecure) as http:
        print(f"\nPOSTing $import to {import_url}")
        resp = http.post(import_url, json=parameters)
        if resp.status_code != 202:
            resp.raise_for_status()
            print(f"Unexpected status {resp.status_code}: {resp.text}", file=sys.stderr)
            return 1

        status_url = resp.headers.get("Content-Location")
        if not status_url:
            print("Server returned 202 but no Content-Location header to poll.", file=sys.stderr)
            return 1

        print(f"Accepted. Polling {status_url}")
        result = _poll_import_job(http, status_url, timeout=_IMPORT_POLL_TIMEOUT)

    print("\nImport completed:")
    print(json.dumps(result, indent=2))
    return 0


def _parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Apply a merged-profile terminology facade to a merged FHIR resource's data.")
    p.add_argument(
        "--resource",
        default=None,
        help="FHIR resource type. Required for verify. Optional for document and data-map — if omitted, every "
        "<Resource>.parquet table under --data (a warehouse root) is swept in one run.",
    )
    p.add_argument("--mode", required=True, choices=["document", "data-map", "verify", "import"])
    p.add_argument(
        "--data",
        default=None,
        help="Path to the merged Delta table, OR the warehouse root (resolves <resource>.parquet under it; "
        "document mode without --resource requires the warehouse root). Required for document/data-map/verify; "
        "unused for --mode import (which never touches Spark/Delta).",
    )
    p.add_argument("--base-url", default=_DEFAULT_BASE_URL, help=f"Canonical namespace (default: {_DEFAULT_BASE_URL}).")
    p.add_argument("--term-server", default=_DEFAULT_TERM_SERVER, help=f"FHIR terminology base (default: {_DEFAULT_TERM_SERVER}).")
    p.add_argument(
        "--token",
        default=None,
        help="Optional bearer token: for the terminology server (document/verify), or for --pathling-url (import).",
    )
    p.add_argument("--dry-run", action="store_true", help="Print/report without writing or POSTing (data-map, import).")
    p.add_argument("--insecure", action="store_true", help="Skip TLS verification (self-signed server).")
    p.add_argument(
        "--out-dir",
        default=None,
        help="document mode: write each resource's summary JSON + suggested FSH drafts under <out-dir>/<Resource>/ "
        "instead of stdout (suggested: scripts/merged_profile_provisioning/artifacts). These are drafts for a "
        "human to review, not files consumed by the IG build. import mode: read that same <out-dir>/<Resource>/ "
        "tree to decide which resources to import (required for import; defaults to "
        "scripts/merged_profile_provisioning/artifacts next to this script if omitted).",
    )
    p.add_argument(
        "--pathling-url",
        default=_DEFAULT_PATHLING_URL,
        help=f"import mode only: Pathling FHIR endpoint to $import into (default: {_DEFAULT_PATHLING_URL}).",
    )
    p.add_argument(
        "--import-base-url",
        default=None,
        help="import mode only, required: warehouse root URL as Pathling's server sees it (e.g. "
        "s3a://bucket/mimic-warehouse or file:///shared/mimic-warehouse). Each discovered resource is imported "
        "from <import-base-url>/<Resource>.parquet.",
    )
    p.add_argument(
        "--resources",
        nargs="+",
        default=None,
        metavar="RESOURCE",
        help="import mode only: explicit list of resource types to import (e.g. --resources Condition Encounter "
        "Patient), overriding discovery from --out-dir. Use this when data-map already ran (e.g. swept a whole "
        "warehouse directly, or ran on an isolated node) without a matching document/artifacts/ run to read.",
    )
    args = p.parse_args(argv)
    if args.mode == "verify" and not args.resource:
        p.error(f"--resource is required for --mode {args.mode}")
    if args.mode != "import" and not args.data:
        p.error(f"--data is required for --mode {args.mode}")
    if args.mode == "import":
        if not args.import_base_url:
            p.error("--import-base-url is required for --mode import")
        if not args.resources and not args.out_dir:
            args.out_dir = str(Path(__file__).resolve().parent / "artifacts")
    return args


def main(argv: list[str]) -> int:
    args = _parse_args(argv)
    if args.mode == "document":
        return run_document(args)
    if args.mode == "verify":
        return run_verify(args)
    if args.mode == "import":
        return run_import(args)
    return run_data_map(args)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
