"""Argument handling common to every CodeSystem/ValueSet build script."""

import os
from pathlib import Path

from . import paths
from .fhirclient import configure_tls

DEFAULT_FHIR_BASE = os.environ.get("ONTOSERVER_URL")
DEFAULT_CA_BUNDLE = (os.environ.get("SSL_CERT_FILE")
                     or os.environ.get("REQUESTS_CA_BUNDLE"))


def add_common_args(ap):
    ap.add_argument("--out-dir", type=Path, default=paths.OUTPUT,
                    help=f"where to write the resource (default: {paths.OUTPUT})")
    ap.add_argument("--fhir-base", default=DEFAULT_FHIR_BASE,
                    help="terminology server base URL (default: $ONTOSERVER_URL; "
                         "no upload when unset)")
    ap.add_argument("--no-upload", action="store_true", help="convert only")
    ap.add_argument("--ca-bundle", default=DEFAULT_CA_BUNDLE,
                    help="PEM bundle to verify the server's certificate chain "
                         "against, for servers behind a corporate CA (default: "
                         "$SSL_CERT_FILE, else $REQUESTS_CA_BUNDLE)")
    ap.add_argument("--insecure", action="store_true",
                    help="skip TLS verification entirely; prefer --ca-bundle")
    return ap


def resolve(args):
    """Apply the TLS settings and report whether uploads will happen."""
    configure_tls(args.ca_bundle, args.insecure)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    if args.no_upload:
        return False
    if not args.fhir_base:
        print("  skipping upload: no --fhir-base and ONTOSERVER_URL unset")
        return False
    return True
