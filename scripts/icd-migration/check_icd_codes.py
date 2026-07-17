#!/usr/bin/env python3
"""Batch-check MIMIC diagnosis ICD codes against a terminology server.

Stdlib only. Reads the custom CodeSystems from input/resources/, converts each
dot-less MIMIC code to proper ICD-10-CM / ICD-9-CM form, validates every
converted code via CodeSystem/$validate-code, and produces:

  - scripts/icd-migration/validation-icd10.csv   (all codes, one row each)
  - scripts/icd-migration/validation-icd9.csv
  - scripts/icd-migration/unmapped-icd10.csv     (only codes that failed)
  - scripts/icd-migration/unmapped-icd9.csv
  - scripts/icd-migration/display-map.json       (original code -> dotted code
                                                  + official display + first
                                                  valid release version; input
                                                  for the pyspark migration
                                                  script)

Usage:
  python3 check_icd_codes.py [--endpoint URL] [--system icd10|icd9|both] [--workers N]
"""
import argparse
import csv
import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

NETWORK_ERROR = "NETWORK-ERROR"
RETRIES = 4  # transient-failure retries per request, with exponential backoff

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
RESOURCES = os.path.join(REPO, "input", "resources")
OUT_DIR = os.path.dirname(os.path.abspath(__file__))

DEFAULT_ENDPOINT = os.environ.get("ONTOSERVER_URL")

SYSTEMS = {
    "icd10": {
        "source": os.path.join(RESOURCES, "CodeSystem-mimic-diagnosis-icd10.json"),
        "target_url": "http://hl7.org/fhir/sid/icd-10-cm",
    },
    "icd9": {
        "source": os.path.join(RESOURCES, "CodeSystem-mimic-diagnosis-icd9.json"),
        "target_url": "http://hl7.org/fhir/sid/icd-9-cm",
    },
}


# ---------------------------------------------------------------------------
# Conversion rules (single source of truth — reuse in the migration script)
# ---------------------------------------------------------------------------
def convert_icd10(code):
    """ICD-10-CM: dot after the 3rd character, only when length > 3."""
    code = code.strip()
    if len(code) > 3:
        return code[:3] + "." + code[3:]
    return code


def convert_icd9(code):
    """ICD-9-CM diagnosis: E-codes dot after the 4th character (E8500 -> E850.0);
    numeric and V-codes dot after the 3rd (20500 -> 205.00, V4501 -> V45.01)."""
    code = code.strip()
    if code.startswith(("E", "e")):
        if len(code) > 4:
            return code[:4] + "." + code[4:]
        return code
    if len(code) > 3:
        return code[:3] + "." + code[3:]
    return code


CONVERTERS = {"icd10": convert_icd10, "icd9": convert_icd9}


# ---------------------------------------------------------------------------
# Terminology server
# ---------------------------------------------------------------------------
SSL_CONTEXT = None  # set in main() when --insecure is passed


def fetch_valueset_versions(endpoint, valueset, system_url):
    """Return the code system versions pinned in the value set's compose for
    system_url, sorted ascending. Ontoserver's ValueSet/$validate-code only
    checks a version-less coding against ONE version of a system even when the
    compose pins several (observed on Ontoserver 6.27), so callers must retry
    with each pinned version via systemVersion."""
    params = urllib.parse.urlencode({"url": valueset, "_elements": "compose"})
    url = "{}/ValueSet?{}".format(endpoint.rstrip("/"), params)
    req = urllib.request.Request(url, headers={"Accept": "application/fhir+json"})
    with urllib.request.urlopen(req, timeout=30, context=SSL_CONTEXT) as resp:
        bundle = json.load(resp)
    if not bundle.get("entry"):
        raise SystemExit("value set not found on server: {}".format(valueset))
    vs = bundle["entry"][0]["resource"]
    versions = [inc.get("version")
                for inc in vs.get("compose", {}).get("include", [])
                if inc.get("system") == system_url]
    # Probe earliest release first so the pinned version is deterministically
    # the first release containing the code, regardless of compose order.
    return sorted(v for v in versions if v) or [None]


def validate_code(endpoint, system_url, code, valueset=None, version=None):
    """Validate a code. Against ValueSet/$validate-code when a value set URL is
    given (with systemVersion when version is set), otherwise against
    CodeSystem/$validate-code (the server's default version of the system).
    Returns (valid, display, message)."""
    if valueset:
        query = {"url": valueset, "system": system_url, "code": code}
        if version:
            query["systemVersion"] = version
        params = urllib.parse.urlencode(query)
        url = "{}/ValueSet/$validate-code?{}".format(endpoint.rstrip("/"), params)
    else:
        params = urllib.parse.urlencode({"url": system_url, "code": code})
        url = "{}/CodeSystem/$validate-code?{}".format(endpoint.rstrip("/"), params)
    req = urllib.request.Request(url, headers={"Accept": "application/fhir+json"})
    body = None
    for attempt in range(RETRIES + 1):
        try:
            with urllib.request.urlopen(req, timeout=30, context=SSL_CONTEXT) as resp:
                body = json.load(resp)
            break
        except urllib.error.HTTPError as e:
            # An HTTP response IS an answer (usually an OperationOutcome for an
            # unknown code/system) — no retry.
            try:
                body = json.load(e)
            except Exception:
                return False, "", "HTTP {}".format(e.code)
            if body.get("resourceType") == "OperationOutcome":
                issues = "; ".join(
                    i.get("diagnostics") or i.get("details", {}).get("text", "")
                    for i in body.get("issue", [])
                )
                return False, "", issues or "HTTP {}".format(e.code)
            return False, "", "HTTP {}".format(e.code)
        except (urllib.error.URLError, OSError) as e:
            # DNS failure, connection reset, timeout, ... — transient; retry
            # with backoff, then report distinctly (NOT as an invalid code).
            if attempt == RETRIES:
                return False, "", "{}: {}".format(NETWORK_ERROR, e)
            time.sleep(2 ** attempt)

    result, display, message = False, "", ""
    for p in body.get("parameter", []):
        name = p.get("name")
        if name == "result":
            result = bool(p.get("valueBoolean"))
        elif name == "display":
            display = p.get("valueString", "")
        elif name == "message":
            message = p.get("valueString", "")
    return result, display, message


def check_system(key, endpoint, workers, valueset=None):
    cfg = SYSTEMS[key]
    with open(cfg["source"]) as f:
        cs = json.load(f)
    convert = CONVERTERS[key]
    versions = [None]
    if valueset:
        versions = fetch_valueset_versions(endpoint, valueset, cfg["target_url"])
        if versions == [None]:
            print("[{}] WARNING: {} pins no versions of {} — falling back to "
                  "CodeSystem/$validate-code (no version will be recorded).".format(
                      key, valueset, cfg["target_url"]))
            valueset = None
        else:
            print("[{}] validating against {} (pinned versions: {})".format(
                key, valueset, ", ".join(versions)))
    concepts = [(c["code"], c.get("display", "")) for c in cs.get("concept", [])]
    print("[{}] {} concepts loaded from {}".format(
        key, len(concepts), os.path.basename(cfg["source"])))

    rows = []
    unknown_system = False

    def task(item):
        original, mimic_display = item
        dotted = convert(original)
        valid, display, message, matched_version = False, "", "", None
        network_error = None
        for version in versions:
            valid, display, message = validate_code(
                endpoint, cfg["target_url"], dotted, valueset, version)
            if valid:
                break
            if message.startswith(NETWORK_ERROR):
                network_error = message
        if valid:
            matched_version = version
        elif network_error:
            # At least one version probe never reached the server, so
            # "invalid" cannot be trusted — surface the network error instead.
            message = network_error
        return {
            "original_code": original,
            "dotted_code": dotted,
            "valid": valid,
            "version": matched_version or "",
            "official_display": display,
            "mimic_display": mimic_display,
            "message": message,
        }

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = [ex.submit(task, item) for item in concepts]
        for i, fut in enumerate(as_completed(futures), 1):
            row = fut.result()
            rows.append(row)
            if "not found" in row["message"].lower() and cfg["target_url"] in row["message"]:
                unknown_system = True
            if i % 1000 == 0:
                print("[{}] {}/{} checked".format(key, i, len(concepts)))

    rows.sort(key=lambda r: r["original_code"])

    # Cross-system rescue: MIMIC's icd9 CodeSystem contains a handful of codes
    # that are actually ICD-10-CM (mis-filed icd_version in the source data,
    # e.g. I509, J45901). Re-validate icd9 failures against ICD-10-CM; hits are
    # relabeled — they stay keyed under icd-9-cm in the display map but carry a
    # per-entry "system" override so the migration writes them as ICD-10-CM.
    relabeled = set()
    if key == "icd9":
        icd10_url = SYSTEMS["icd10"]["target_url"]
        r_versions = [None]
        if valueset:
            r_versions = fetch_valueset_versions(endpoint, valueset, icd10_url)
        for row in rows:
            if row["valid"] or row["message"].startswith(NETWORK_ERROR):
                continue
            dotted = convert_icd10(row["original_code"])
            for version in r_versions:
                valid, display, _ = validate_code(
                    endpoint, icd10_url, dotted, valueset, version)
                if valid:
                    relabeled.add(row["original_code"])
                    row.update(valid=True, dotted_code=dotted, version=version or "",
                               official_display=display,
                               message="relabeled: valid ICD-10-CM code mis-filed "
                                       "in the MIMIC ICD-9 CodeSystem")
                    break
        if relabeled:
            print("[{}] rescued {} mis-filed ICD-10-CM code(s): {}".format(
                key, len(relabeled), ", ".join(sorted(relabeled))))

    fields = ["original_code", "dotted_code", "valid", "version",
              "official_display", "mimic_display", "message"]

    all_path = os.path.join(OUT_DIR, "validation-{}.csv".format(key))
    with open(all_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)

    unmapped = [r for r in rows if not r["valid"]]
    unmapped_path = os.path.join(OUT_DIR, "unmapped-{}.csv".format(key))
    with open(unmapped_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(unmapped)

    print("[{}] valid: {}/{}  unmapped: {}  -> {}".format(
        key, len(rows) - len(unmapped), len(rows), len(unmapped),
        os.path.relpath(unmapped_path, REPO)))
    network_failures = sum(1 for r in rows if r["message"].startswith(NETWORK_ERROR))
    if network_failures:
        raise SystemExit(
            "[{}] {} codes could not be checked due to network errors (see the "
            "csv files) — results are incomplete, display-map.json was NOT "
            "updated. Re-run when the connection is stable.".format(
                key, network_failures))
    if unknown_system:
        print("[{}] WARNING: server reported the code system {} as unknown — "
              "results reflect missing system content, not invalid codes.".format(
                  key, cfg["target_url"]))

    display_map = {}
    for r in rows:
        if not r["valid"]:
            continue
        entry = {"code": r["dotted_code"], "display": r["official_display"]}
        if r["version"]:
            entry["version"] = r["version"]
        if r["original_code"] in relabeled:
            entry["system"] = SYSTEMS["icd10"]["target_url"]
        display_map[r["original_code"]] = entry
    return rows, display_map


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--endpoint", default=DEFAULT_ENDPOINT,
                    help="FHIR terminology server base URL "
                         "(default: $ONTOSERVER_URL)")
    ap.add_argument("--system", choices=["icd10", "icd9", "both"], default="both")
    ap.add_argument("--workers", type=int, default=16)
    ap.add_argument("--insecure", action="store_true",
                    help="skip TLS certificate verification (self-signed cert in chain)")
    ap.add_argument("--valueset",
                    help="ValueSet URL to validate codes against instead of the "
                         "code system's server-default version, e.g. "
                         "http://mimic.mit.edu/fhir/mimic/ValueSet/mimic-diagnosis. "
                         "Applies to every checked system whose versions the "
                         "compose pins; systems it does not pin fall back to "
                         "CodeSystem/$validate-code.")
    args = ap.parse_args()

    if not args.endpoint:
        ap.error("a terminology server is required: pass --endpoint or set "
                 "ONTOSERVER_URL")

    if args.insecure:
        global SSL_CONTEXT
        SSL_CONTEXT = ssl.create_default_context()
        SSL_CONTEXT.check_hostname = False
        SSL_CONTEXT.verify_mode = ssl.CERT_NONE

    keys = ["icd10", "icd9"] if args.system == "both" else [args.system]
    display_maps = {}
    for key in keys:
        _, dmap = check_system(key, args.endpoint, args.workers, args.valueset)
        display_maps[SYSTEMS[key]["target_url"]] = dmap

    map_path = os.path.join(OUT_DIR, "display-map.json")
    existing = {}
    if os.path.exists(map_path) and args.system != "both":
        with open(map_path) as f:
            existing = json.load(f)
    existing.update(display_maps)
    with open(map_path, "w") as f:
        json.dump(existing, f, indent=1)
    print("display map written to", os.path.relpath(map_path, REPO))


if __name__ == "__main__":
    sys.exit(main())
