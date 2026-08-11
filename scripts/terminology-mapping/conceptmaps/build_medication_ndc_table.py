#!/usr/bin/env python3
"""Generate conceptmaps/medication-ndc-standard.csv — MIMIC NDC -> RxNorm.

The first generator in this repo that calls NO model. code-search is not a
fallback here, it is absent: both tiers are deterministic lookups, and a code
either resolves through one of them or is declared unmapped. There is no
threshold, no constraint to tune and no confidence column, because nothing is
ever scored.

That makes this stream unlike every sibling, and the reason is the input. NDC is
not a label — it is a package identifier, and RxNorm publishes the mapping from
it as a property. Sending an 11-digit number to a semantic search service would
be paying a model to do a dictionary lookup it cannot do.

TWO TIERS, and the second is free.

    ndc-property        RxNorm 20231106's own NDC property, asked in reverse.
    display-name-table  the MIMIC label attached to the NDC, joined against the
                        already-committed medication-name-standard.csv.

Measured on an 80-code sample (seed 20260810: the 40 codes with the most
referring prescriptions, plus 40 uniform at random over the rest):

    ndc-property        55/80 codes   ~67.9% of the 11,000,655 referring
                                      prescriptions, projected
    display-name-table  52/80         63.5%, measured over all 5,732 codes
    union               71/80 (88.8%)

Neither tier alone is worth building; together they are. The overlap is large
but the residuals barely intersect, which is what makes the union 20 points
better than either side.

ASKING THE PROPERTY IN REVERSE. RxNorm's NDC property hangs off the RxCUI —
`$lookup` on a concept returns the NDCs it covers, which is the wrong direction
for this stream. Ontoserver answers the reverse as an ordinary compose filter:

    {"system": rxnorm, "filter": [{"property": "NDC", "op": "=", "value": ndc}]}

so no reverse index has to be built, committed or kept in step with a release.
Bulk retrieval was tried first and does not work — `$expand` with
`property=NDC` returns empty `property` arrays for RxNorm on velonto — but at
0.08 s per call the per-code form costs about seven minutes serially for the
whole population, and it has the better property anyway: it asks only about
codes MIMIC actually has.

AMBIGUITY GUARD, the same shape as the term index's. An NDC reaching more than
one RxCUI is DECLINED, never tie-broken. Measured: zero collisions in 55 hits,
which is what an NDC is supposed to guarantee — one package, one product. If
that ever stops holding, a release has changed something this repo should look
at rather than silently resolve.

SBD IS IN SCOPE HERE, and is excluded from the sibling name stream. That looks
like a contradiction and is not. build_medication_name_table.py drops branded
drug products because a model asked about the string `Fluticasone-Salmeterol
Diskus (500/50)` will confidently attach a brand the record never stated —
brand invention, measured at 7 wrong targets over the A/B set. Nothing is
invented here: the brand comes from the NDC, which IS the manufacturer's own
package identifier, and dropping SBD would mean answering a branded package with
a deliberately less specific concept. Of the 55 sampled hits, 34 are SCD and 21
SBD, so the exclusion would cost 38% of the tier.

WHERE THE TIERS DISAGREE, THE NDC WINS. On the 36 sampled codes where both
fire they returned a different RxCUI every single time, which sounds alarming
and mostly is not: the NDC tier lands on the packaged product and the display
tier on the ingredient or brand, so `Ondansetron` gives 1740467 `ondansetron
4 MG in 2 ML Injection` against 26225 `ondansetron`. One is a specialisation of
the other and the specific one is better.

The tier order also rescues the codes whose MIMIC label is not a drug name at
all, and there are many: `LR` -> lactated Ringers, `D5 1/2NS` -> dextrose 5% /
sodium chloride 0.45%, `Insulin Pump (Self Administering Med)` -> HumaLOG. The
display tier cannot reach any of those, and together they carry over 470,000
referring prescriptions.

THE COST OF THAT DECISION, stated because it is real. Where MIMIC's own
label and the NDC disagree about the SUBSTANCE rather than the specificity, this
rule follows RxNorm and overrides the label. The clearest case in the sample:

    00088222033   MIMIC label  'Toujeo SoloStar'    insulin glargine 300 U/mL
                  RxNorm       285018 Lantus        insulin glargine 100 U/mL
                  160,595 referring prescriptions

Checked directly rather than inferred: RxNorm 20231106 does list that NDC under
Lantus, and lists no NDC at all for 1604545, the 300 U/mL concept. Labeler 00088
is Sanofi and the 2220 product segment is Lantus SoloStar, so the likelier
reading is that MIMIC paired a Lantus package code with the drug name `Toujeo
SoloStar` — i.e. this map is right and the warehouse label is wrong. That is not
provable from a terminology server alone, and a consumer who needs to know which
of the two MIMIC meant should read `display_rxcui` on the row, which records
what the label would have given.

Both candidates are therefore written to every row where both exist, mapped or
not, so the disagreements are greppable in the committed file rather than
discarded at generation time:

    grep -v '^.*,,' medication-ndc-standard.csv | awk -F, '$9 && $10 && $9!=$10'

NO --append. The sibling generators have it because a model-backed run over a
shared table is expensive and its committed rows are worth carrying. Neither
holds here: the whole population regenerates in about seven minutes, and one
field reads this table. Adding append would add the settings-drift failure mode
assert_same_settings exists to catch, for no saving.

THE DISPLAY TIER DERIVES FROM ANOTHER COMMITTED TABLE, which is a staleness
risk nothing else in this repo has. If medication-name-standard.csv is
regenerated and this table is not, rows here keep answers that file no longer
gives. The generation log records that table's sha256 for exactly that reason —
a tripwire, the same one the term index manifest carries.

NOT PART OF `make mappings`: it needs the network and WRITES a build input.
Determinism lives in the split — this runs by hand, its output is committed, and
the build reads the committed CSV and never a server.

Usage:
  uv run .../build_medication_ndc_table.py --insecure
  uv run .../build_medication_ndc_table.py --only 00088222033 --insecure
"""

import argparse
import concurrent.futures
import csv
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.cli import add_common_args                            # noqa: E402
from common.fhirclient import configure_tls, http                 # noqa: E402
from common import paths                                          # noqa: E402
from conceptmaps.lib.builders import (describe_population,        # noqa: E402
                                      table_population)
from conceptmaps.lib.canonical import RXNORM, TABLE_DIR           # noqa: E402

OUT_CSV = TABLE_DIR / "medication-ndc-standard.csv"
LOG_JSON = paths.OUTPUT / "medication-ndc-generation-log.json"

# Tier 2's input. Committed, generated by build_medication_name_table.py, and
# read here rather than re-derived: two files asserting different RxNorm
# concepts for one MIMIC drug label is the exact failure lib/builders.py exists
# to prevent, and it would be invisible from either file alone.
NAME_TABLE = TABLE_DIR / "medication-name-standard.csv"

# The RxNorm release this table was built from, asserted against what the server
# echoes on every expansion. A silent release bump would change committed
# answers with no diff to explain them. NOT pinned into the map — see
# lib/canonical.py UNVERSIONED_SYSTEMS for why those are different claims.
RXNORM_VERSION = "20231106"

# The property RxNorm publishes the package mapping under. Named as a constant
# because it is the whole method: change this string and the stream is a
# different stream.
NDC_PROPERTY = "NDC"

CURATED_HEADER = [
    "mimic_code", "mimic_display",
    "target_system", "target_code", "target_display", "comment",
    # Provenance: read by lib/stats.py and discarded by the build. `method` is
    # constant here — there is only one — and kept so this table's rows are the
    # same shape as its siblings'. Both candidates are recorded on every row,
    # including the declined ones and including the rows where the two
    # disagreed, so any answer and any non-answer can be audited from the CSV
    # alone. See WHERE THE TIERS DISAGREE above.
    "method", "join_rung",
    "ndc_property_rxcui", "ndc_property_display",
    "display_rxcui", "display_source",
]


# --------------------------------------------------------------------------- #
# Tier 1: RxNorm's NDC property, asked in reverse.
# --------------------------------------------------------------------------- #

def lookup_ndc(fhir_base, ndc):
    """([(rxcui, display)], version) for the concepts carrying this NDC.

    No timeout argument: common/fhirclient.py's `http` owns it, and a second
    knob here would be one the transport ignores.

    An inline ValueSet rather than a canonical: there is no implicit-ValueSet
    syntax for "RxNorm filtered by a property value", and inventing a VCL for it
    would be a URL the server has to parse into this same compose anyway.

    Returns the server's echoed RxNorm version alongside, so the caller can fail
    closed on a release it did not expect. A miss echoes the version too, which
    is what makes the assertion cover the whole run rather than only the hits.
    """
    body = json.dumps({
        "resourceType": "Parameters",
        "parameter": [
            {"name": "valueSet", "resource": {
                "resourceType": "ValueSet",
                "compose": {"include": [{
                    "system": RXNORM,
                    "filter": [{"property": NDC_PROPERTY,
                                "op": "=", "value": ndc}]}]}}},
            # Above any plausible number of concepts per package. A truncated
            # expansion would look exactly like an unambiguous answer, which is
            # the one failure the ambiguity guard must not be blind to.
            {"name": "count", "valueInteger": 50},
        ]}).encode()
    status, got = http("POST", f"{fhir_base}/ValueSet/$expand", data=body)
    if status != 200 or not got or got.get("resourceType") != "ValueSet":
        raise RuntimeError(f"$expand failed for NDC {ndc}: HTTP {status}")
    expansion = got["expansion"]
    version = None
    for parameter in expansion.get("parameter", []):
        value = parameter.get("valueUri") or parameter.get("valueString") or ""
        if parameter.get("name") == "used-codesystem" and \
                value.startswith(f"{RXNORM}|"):
            version = value.split("|", 1)[1]
    return ([(c["code"], c.get("display", ""))
             for c in expansion.get("contains", [])], version)


# --------------------------------------------------------------------------- #
# Tier 2: the committed drug-name table, joined on the NDC's MIMIC label.
# --------------------------------------------------------------------------- #

def load_name_table():
    """{mimic label: row} for the committed rows that carry a target.

    Keyed on `mimic_code`, which for `mimic-medication-name` IS the label —
    that CodeSystem's codes are the drug-name strings themselves, which is what
    makes this join possible at all. Rows with no target are dropped rather than
    carried: a declined name is not an answer this tier can offer, and keeping
    it would only make the miss look like a different kind of miss.
    """
    if not NAME_TABLE.is_file():
        sys.exit(f"  {NAME_TABLE.name} is missing. Tier 2 reads it; generate "
                 f"it first with `make medication-name-table`.")
    with open(NAME_TABLE, newline="") as fh:
        return {row["mimic_code"]: row
                for row in csv.DictReader(fh) if row.get("target_code")}


def name_table_digest():
    """sha256 of the tier-2 input, for the log. See the docstring's tripwire."""
    return hashlib.sha256(NAME_TABLE.read_bytes()).hexdigest()


# --------------------------------------------------------------------------- #

def build_row(code, display, fhir_base, name_table):
    """One CSV row: tier 1, then tier 2, then a declared non-answer."""
    row = dict.fromkeys(CURATED_HEADER, "")
    row.update(mimic_code=code, mimic_display=display, method="lookup")

    targets, version = lookup_ndc(fhir_base, code)
    row["_version"] = version
    fallback = name_table.get(display)
    if fallback:
        # Recorded whether or not it is used, so a consumer can see what the
        # MIMIC label would have given. See WHERE THE TIERS DISAGREE.
        row["display_rxcui"] = fallback["target_code"]
        row["display_source"] = display

    if len(targets) == 1:
        rxcui, rx_display = targets[0]
        row.update(join_rung="ndc-property", target_system=RXNORM,
                   target_code=rxcui, target_display=rx_display,
                   ndc_property_rxcui=rxcui, ndc_property_display=rx_display,
                   comment=(
                       f"RxNorm {RXNORM_VERSION} lists this NDC on RxCUI "
                       f"{rxcui}. Package-level identity: the target names the "
                       f"product the package contains, including its brand "
                       f"where the NDC is a branded package."))
        return row

    if len(targets) > 1:
        # Declined, not tie-broken. See AMBIGUITY GUARD.
        named = ", ".join(f"{c} {d}" for c, d in sorted(targets)[:4])
        row["comment"] = (
            f"RxNorm {RXNORM_VERSION} lists this NDC on {len(targets)} "
            f"concepts ({named}). An NDC identifies one package of one "
            f"product, so this is a defect in the release rather than a choice "
            f"to make: declined rather than tie-broken.")
        return row

    if fallback:
        row.update(join_rung="display-name-table",
                   target_system=fallback.get("target_system", RXNORM),
                   target_code=fallback["target_code"],
                   target_display=fallback["target_display"],
                   comment=(
                       f"RxNorm {RXNORM_VERSION} lists no concept carrying "
                       f"this NDC. Mapped instead through the MIMIC label "
                       f"{display!r}, from the committed "
                       f"{NAME_TABLE.name} row for that label. This is an "
                       f"ingredient- or class-level generalisation, NOT the "
                       f"packaged product the NDC identifies."))
        return row

    row["comment"] = (
        f"RxNorm {RXNORM_VERSION} lists no concept carrying this NDC, and the "
        f"MIMIC label {display!r} has no mapped row in {NAME_TABLE.name}. Both "
        f"tiers were tried and neither answered. This is the intersection of "
        f"two gaps — a retired or repackaged NDC the release no longer carries, "
        f"whose label the drug-name stream also could not resolve — and not a "
        f"finding that the product has no RxNorm concept.")
    return row


# --------------------------------------------------------------------------- #

def ig_codes():
    """The observed source codes for every field that reads this table.

    One field today — Medication.code is the only element in the inventory the
    warehouse puts `mimic-medication-ndc` on, measured. Discovered rather than
    assumed anyway, because that is what stops a second field being added with
    its codes silently missing from the table.
    """
    return table_population(OUT_CSV)


def report(rows):
    print(f"\n  {len(rows):,} row(s)", file=sys.stderr)
    print("\n  join rung", file=sys.stderr)
    for rung, n in Counter(r["join_rung"] for r in rows
                           if r["join_rung"]).most_common():
        print(f"    {rung:20s} {n:>6,}", file=sys.stderr)
    print("\n  target system", file=sys.stderr)
    for system, n in Counter(r["target_system"] for r in rows
                             if r["target_code"]).most_common():
        print(f"    {system:50s} {n:>6,}", file=sys.stderr)

    # The number the disagreement policy rests on, printed every run so a
    # release bump that widens it cannot pass unnoticed. See the docstring.
    both = [r for r in rows if r["ndc_property_rxcui"] and r["display_rxcui"]]
    differ = [r for r in both
              if r["ndc_property_rxcui"] != r["display_rxcui"]]
    print(f"\n  both tiers had a candidate: {len(both):,}", file=sys.stderr)
    print(f"    of which they disagreed:  {len(differ):,}  "
          f"(NDC wins; `display_rxcui` records the other)", file=sys.stderr)

    mapped = sum(1 for r in rows if r["target_code"])
    print(f"\n  {mapped:,}/{len(rows):,} mapped "
          f"({100 * mapped / len(rows):.1f}%)", file=sys.stderr)


def main():
    ap = argparse.ArgumentParser(
        description=__doc__.split("\n\n")[0],
        formatter_class=argparse.RawDescriptionHelpFormatter)
    add_common_args(ap)
    ap.add_argument("--workers", type=int, default=8,
                    help="concurrent $expand calls (default: %(default)s)")
    ap.add_argument("--only", help="comma-separated MIMIC codes, for probing. "
                                   "REWRITES the table to just those rows")
    args = ap.parse_args()

    fhir_base = (args.fhir_base or "").rstrip("/")
    if not fhir_base:
        sys.exit("  no --fhir-base and $ONTOSERVER_URL unset.")
    configure_tls(args.ca_bundle, args.insecure)

    name_table = load_name_table()
    print(f"  tier 2: {len(name_table):,} mapped label(s) from "
          f"{NAME_TABLE.name}", file=sys.stderr)

    concepts = ig_codes()
    for element, count in describe_population(OUT_CSV):
        print(f"  {element:42s} {count:>6,} observed", file=sys.stderr)

    if args.only:
        wanted = {c.strip() for c in args.only.split(",")}
        concepts = {k: v for k, v in concepts.items() if k in wanted}
        if missing := wanted - set(concepts):
            sys.exit(f"  --only names code(s) not in the observed population: "
                     f"{sorted(missing)}")
        print(f"  WARNING: --only rewrites {OUT_CSV.name} to "
              f"{len(concepts)} row(s).", file=sys.stderr)

    rows, failed = [], []
    with concurrent.futures.ThreadPoolExecutor(args.workers) as pool:
        futures = {pool.submit(build_row, code, display, fhir_base,
                               name_table): code
                   for code, display in concepts.items()}
        for done, future in enumerate(
                concurrent.futures.as_completed(futures), 1):
            try:
                rows.append(future.result())
            except Exception as exc:                             # noqa: BLE001
                failed.append((futures[future], exc))
            print(f"    {done:,}/{len(futures):,}", end="\r", file=sys.stderr)

    if failed:
        # Refusing to write is the point: a table missing the rows whose calls
        # died is indistinguishable from one where the server said no.
        for code, exc in failed[:5]:
            print(f"    {code}: {exc}", file=sys.stderr)
        sys.exit(f"\n  {len(failed)} of {len(concepts)} call(s) failed. "
                 f"Refusing to write a table that would understate coverage.")

    # Fail closed on a release bump, and equally on a server that stopped
    # saying which release it used — an unasserted version is not a matching
    # one, and every committed answer here is a claim about a specific release.
    seen = {r.pop("_version") for r in rows}
    if seen != {RXNORM_VERSION}:
        sys.exit(f"\n  server used RxNorm {sorted(map(str, seen))}, this table "
                 f"is built against {RXNORM_VERSION}. Refusing to mix "
                 f"releases: re-pin RXNORM_VERSION deliberately and review the "
                 f"resulting diff.")

    rows.sort(key=lambda r: r["mimic_code"])
    with open(OUT_CSV, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=CURATED_HEADER, restval="")
        writer.writeheader()
        writer.writerows(rows)
    report(rows)
    print(f"  wrote {OUT_CSV.name}", file=sys.stderr)

    LOG_JSON.parent.mkdir(parents=True, exist_ok=True)
    LOG_JSON.write_text(json.dumps({
        "elements": [element for element, _ in
                     describe_population(OUT_CSV)],
        # No constraint, no template, no threshold: nothing is searched and
        # nothing is scored. lib/stats.py reads what is absent as absent, and
        # the stream's statistics row carries no confidence spread by design —
        # see the module docstring.
        "method": "deterministic-lookup",
        "ndc_property": NDC_PROPERTY,
        "rxnorm_version": RXNORM_VERSION,
        "tiers": ["ndc-property", "display-name-table"],
        "tier_precedence": (
            "ndc-property wins wherever it answers. The display tier is a "
            "generalisation through the MIMIC label and is used only where "
            "RxNorm carries no concept for the NDC."),
        # The staleness tripwire. Tier 2's answers are derived from this file,
        # so a regeneration of it that skips this table is a silent divergence.
        "name_table": {"file": NAME_TABLE.name,
                       "sha256": name_table_digest()},
        "rows": rows,
    }, indent=1) + "\n")
    print(f"  wrote {LOG_JSON.name}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
