"""Minimal FHIR terminology-server client shared by the build scripts.

Extracted verbatim from build_icd9cm_codesystem.py / build_icd10cm_codesystem.py,
which had drifted apart (only the ICD-9 one had grown --ca-bundle support).
"""

import json
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

# Verify properly when a CA bundle is available (servers behind a corporate CA
# need one); fall back to the historical no-verify behaviour otherwise so
# existing invocations keep working. Replaced by configure_tls().
SSL_CONTEXT = ssl.create_default_context()
SSL_CONTEXT.check_hostname = False
SSL_CONTEXT.verify_mode = ssl.CERT_NONE


def configure_tls(ca_bundle: str | None, insecure: bool):
    global SSL_CONTEXT
    if insecure:
        print("  WARNING: TLS verification disabled (--insecure)")
        return
    if not ca_bundle:
        print("  WARNING: no --ca-bundle and SSL_CERT_FILE unset — TLS "
              "verification is OFF")
        return
    if not Path(ca_bundle).exists():
        sys.exit(f"--ca-bundle not found: {ca_bundle}")
    SSL_CONTEXT = ssl.create_default_context(cafile=ca_bundle)


def http(method, url, data=None):
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Accept": "application/fhir+json",
        **({"Content-Type": "application/fhir+json; charset=utf-8"} if data else {}),
    })
    with urllib.request.urlopen(req, context=SSL_CONTEXT, timeout=600) as resp:
        body = resp.read()
        return resp.status, json.loads(body) if body else None


def describe_http_error(exc):
    """The server's side of the story, which the bare traceback throws away.

    Ontoserver answers a rejected write with an OperationOutcome explaining
    what it disliked; without this every failure looks like an opaque 422.
    """
    raw = exc.read()
    try:
        outcome = json.loads(raw)
    except ValueError:
        return f"HTTP {exc.code}: {raw[:2000].decode(errors='replace')}"
    if outcome.get("resourceType") != "OperationOutcome":
        return f"HTTP {exc.code}: {raw[:2000].decode(errors='replace')}"
    lines = [f"HTTP {exc.code}:"]
    for issue in outcome.get("issue", []):
        text = (issue.get("diagnostics")
                or issue.get("details", {}).get("text", "")).strip()
        where = ", ".join(issue.get("expression", []))
        lines.append(f"    [{issue.get('severity')}/{issue.get('code')}] {text}"
                     + (f"  at {where}" if where else ""))
    return "\n".join(lines)


def put(resource, fhir_base):
    """PUT the resource, letting an HTTPError escape to the caller."""
    url = f"{fhir_base}/{resource['resourceType']}/{resource['id']}"
    body = json.dumps(resource).encode("utf-8")
    print(f"  PUT {url} ({len(body) / 1e6:.1f} MB) ...")
    status, _ = http("PUT", url, body)
    print(f"  -> HTTP {status}")


def upload(resource, fhir_base):
    """PUT the resource; a rejection is fatal, reported without a traceback."""
    try:
        put(resource, fhir_base)
    except urllib.error.HTTPError as exc:
        sys.exit(f"  UPLOAD FAILED: {describe_http_error(exc)}")


def smoke_test(fhir_base, system, version, codes):
    """$lookup each code, printing the resolved display. True if all resolved."""
    ok = True
    for code in codes:
        q = urllib.parse.urlencode(
            {"system": system, "version": version, "code": code})
        try:
            _, result = http("GET", f"{fhir_base}/CodeSystem/$lookup?{q}")
            display = next(p["valueString"] for p in result["parameter"]
                           if p["name"] == "display")
            print(f"  $lookup {code} -> {display}")
        except Exception as exc:  # noqa: BLE001
            print(f"  $lookup {code} FAILED: {exc}")
            ok = False
    return ok


def upload_and_verify(resource, fhir_base, system, version, codes):
    """Upload then smoke test. Exits non-zero on an HTTP error; returns ok."""
    try:
        put(resource, fhir_base)
        return smoke_test(fhir_base, system, version, codes)
    except urllib.error.HTTPError as exc:
        print(f"  UPLOAD FAILED: {describe_http_error(exc)}")
        return False
