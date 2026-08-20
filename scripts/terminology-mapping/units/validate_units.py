#!/usr/bin/env python3
"""Inventory every unit MIMIC records on Observation.valueQuantity, and ask
ucumate whether it is valid UCUM.

OFFLINE AND LOCAL. Unlike its two siblings this script does NOT run on an HPC
node and does not open a warehouse: the unit population was already extracted by
`valueshapes/extract_value_shapes.py` on the full 461M-row Delta warehouse and
committed as the `units` column of `observation-value-shapes.csv`. A third Spark
job over the same view would buy nothing that column does not already carry —
see "WHAT THIS CANNOT SEE" for the two things it genuinely does not.

WHY THIS EXISTS. `Observation.valueQuantity` is not a coded element, so nothing
in the ConceptMap pipeline looks at it, and no binding constrains it. But
`Quantity.code` is a coded field with a fixed system — `http://unitsofmeasure.org`
— and a value that is not valid UCUM there is wrong in the same way an
unresolvable `Observation.code` is wrong: a consumer that tries to convert,
compare or plot two Quantities has nothing to compute with. This is the
inventory a mimic-units -> UCUM mapping is built from, and the count of how much
data rides on each string.

WHICH STRING GETS VALIDATED. FHIR's Quantity carries two: `unit` is a human
display string and is unconstrained, `code` is the computable one and is the
field that must be UCUM. So when the two differ, the CODE is validated and the
`unit` is recorded beside it as the display it was shown under. When only one
string is known the script validates that one and says which field it stood for
in `validated_field`, because the two claims are not equally strong: an invalid
`code` is a defect, whereas an invalid `unit` with no code alongside it is a
Quantity that never made a UCUM claim at all.

WHAT THIS CANNOT SEE, and both need a re-run of the extractor to fix:

  - `Quantity.system` was selected in the extractor's view (`qty_system`) and
    then dropped before the aggregation, so this script cannot say whether the
    Quantities asserting a UCUM `code` also assert the UCUM system URI. A `code`
    under some other system is not a UCUM claim and must not be counted as one.
  - The committed encoding is lossy in one direction. The extractor writes
    `unit|code` only when a code exists AND differs from the unit, so a bare
    label means EITHER code == unit OR code is absent. Those are different
    facts — the first is a UCUM claim, the second is not — and rows here carry
    `code_known: no` to say so rather than guessing.

Neither is a reason to wait: 95 distinct strings over 182M occurrences is a
population small enough to read, and the validity verdict on the string does not
change when the system URI beside it becomes known.

OUTPUTS, both committed, both written to --out-dir:

  mimic-units-validation.csv     one row per distinct (element, unit, code):
                                 the verdict, the canonical form, the parser
                                 errors, how many Observation codes use it, how
                                 many occurrences ride on it, and up to three
                                 example Observation displays so a reader can
                                 tell what `N/A` or `+/-` was standing for
  unit-validation-summary.json   totals split by verdict over both distinct
                                 strings and occurrences, the ucumate version
                                 that judged them, and the sha256 of the input
                                 and the output

CANONICAL FORM IS RECORDED FOR THE VALID ONES because validity alone does not
say two strings mean the same thing: `ml` and `mL` are two spellings MIMIC uses
for one unit, on different Observation codes, and both are valid. The canonical
form is what makes that visible.

It takes BOTH columns to say it. `canonical_term` alone is a DIMENSION — nine
of MIMIC's units canonicalise to `g.m-3`, from `pg/mL` to `g/dL`, and calling
those a collision would be wrong by six orders of magnitude. A genuine
duplicate-spelling collision is the same `canonical_term` at the same
`canonical_magnitude`, and that is what the summary reports. Canonicalization
failures are recorded with their kind (arbitrary unit, [pH], parser error)
rather than as a blank, so an arbitrary unit like `[IU]` — valid UCUM, and
deliberately not convertible — is not mistaken for a defect.

Usage:
  uv run scripts/terminology-mapping/units/validate_units.py
  uv run scripts/terminology-mapping/units/validate_units.py --top 40
"""

import argparse
import collections
import csv
import hashlib
import importlib.metadata
import json
import os
import sys
from datetime import datetime, timezone

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
MAPPING_DIR = os.path.dirname(SCRIPT_DIR)

DEFAULT_SHAPES = os.path.join(MAPPING_DIR, "valueshapes",
                              "observation-value-shapes.csv")

VALIDATION_NAME = "mimic-units-validation.csv"
SUMMARY_NAME = "unit-validation-summary.json"

VALIDATION_COLUMNS = [
    "element", "unit", "code", "code_known",
    "validated_term", "validated_field", "status", "messages",
    "canonical_term", "canonical_magnitude", "canonical_status",
    "n_codes", "occurrences", "example_observations",
]

EXAMPLES_PER_UNIT = 3


def log(msg):
    print(msg, file=sys.stderr, flush=True)


# --------------------------------------------------------------------------- #
# Reading the committed extraction.
# --------------------------------------------------------------------------- #

def parse_units_cell(cell):
    """Decode one `units` cell into (unit, code, code_known, count) tuples.

    The extractor writes `label=count` entries joined by `;`, where label is
    `f"{unit}|{ucum}"` when a ucum code exists and differs from the unit, and
    the single surviving string otherwise. So `|` present means both fields are
    known and differ; `|` absent means one string, and which field it came from
    is NOT recoverable — hence code_known.

    rpartition on `=` rather than split, because a unit may contain `=` well
    before the count does; the count is always the last field.
    """
    for entry in cell.split(";"):
        if not entry:
            continue
        label, sep, count = entry.rpartition("=")
        if not sep or not count.isdigit():
            raise ValueError(f"malformed units entry: {entry!r}")
        unit, bar, code = label.partition("|")
        if bar:
            yield unit, code, True, int(count)
        else:
            yield label, "", False, int(count)


def read_inventory(path):
    """Aggregate the per-code `units` column into one entry per distinct unit.

    Occurrences sum across Observation codes, and `n_codes` counts how many
    distinct codes used the string — a unit on 209 codes and one on 1 are
    different mapping problems even at the same occurrence count.
    """
    occurrences = collections.Counter()
    n_codes = collections.Counter()
    examples = collections.defaultdict(list)

    with open(path, newline="") as fh:
        reader = csv.DictReader(fh)
        if "units" not in (reader.fieldnames or []):
            raise SystemExit(f"ERROR: {path} has no `units` column — is this "
                             f"observation-value-shapes.csv?")
        for row in reader:
            if not row["units"]:
                continue
            for unit, code, known, count in parse_units_cell(row["units"]):
                key = (row["element"], unit, code, known)
                occurrences[key] += count
                n_codes[key] += 1
                examples[key].append((count, row["display"] or row["code"]))

    return occurrences, n_codes, examples


# --------------------------------------------------------------------------- #
# Validation.
# --------------------------------------------------------------------------- #

def judge(svc, term):
    """(status, messages, canonical_status, canonical_term, magnitude).

    Canonicalization is only attempted on a term that validated: asking it of an
    unparseable string yields a parser error that says nothing the validation
    verdict did not already say, and would put two rows in the output for one
    defect.
    """
    from ucumate import (ValidationSuccess, CanonicalizationSuccess,
                         CanonicalizationFailedArbitraryUnit,
                         CanonicalizationFailedPHWithMass)

    result = svc.validate(term)
    if not isinstance(result, ValidationSuccess):
        return "invalid", "; ".join(result.messages), "", "", ""

    canonical = svc.canonicalize(term)
    if isinstance(canonical, CanonicalizationSuccess):
        return ("valid", "", "ok",
                canonical.canonical_term, canonical.magnitude)
    if isinstance(canonical, CanonicalizationFailedArbitraryUnit):
        # A valid UCUM unit that is deliberately not convertible — [IU], [GPL'U]
        # and friends. Not a defect: it is what an arbitrary unit IS.
        return ("valid", "", f"arbitrary-unit:{canonical.arbitrary_unit}",
                "", "")
    if isinstance(canonical, CanonicalizationFailedPHWithMass):
        return "valid", "", "ph-with-mass", "", ""
    return "valid", "", "parser-error", "", ""


def build_rows(occurrences, n_codes, examples, svc):
    rows = []
    for key, total in occurrences.items():
        element, unit, code, known = key
        # The code is the field that must be UCUM; fall back to the unit only
        # when no distinct code was recorded, and say which was judged.
        term = code if known else unit
        field = "code" if known else "unit-or-code"
        status, messages, canon_status, canon_term, magnitude = judge(svc, term)

        top = sorted(examples[key], key=lambda e: (-e[0], e[1]))
        seen, shown = set(), []
        for _, display in top:
            if display not in seen:
                seen.add(display)
                shown.append(display)
            if len(shown) == EXAMPLES_PER_UNIT:
                break

        rows.append({
            "element": element,
            "unit": unit,
            "code": code,
            "code_known": "yes" if known else "no",
            "validated_term": term,
            "validated_field": field,
            "status": status,
            "messages": messages,
            "canonical_term": canon_term,
            "canonical_magnitude": magnitude,
            "canonical_status": canon_status,
            "n_codes": n_codes[key],
            "occurrences": total,
            "example_observations": " | ".join(shown),
        })
    return rows


# --------------------------------------------------------------------------- #
# Output.
# --------------------------------------------------------------------------- #

def sha256(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def write_validation(rows, out_dir):
    path = os.path.join(out_dir, VALIDATION_NAME)
    # Descending occurrences puts the rows that carry the data at the top;
    # the remaining keys are a tiebreak only, so the file is byte-stable.
    ordered = sorted(rows, key=lambda r: (-r["occurrences"], r["element"],
                                          r["unit"], r["code"]))
    with open(path, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=VALIDATION_COLUMNS)
        writer.writeheader()
        writer.writerows(ordered)
    return path, ordered


def summarise(rows):
    def split(predicate):
        chosen = [r for r in rows if predicate(r)]
        return {"distinct": len(chosen),
                "occurrences": sum(r["occurrences"] for r in chosen)}

    # Keyed by canonical term AND magnitude, because the term alone is a
    # DIMENSION rather than a unit: `g/dL` and `ng/mL` both canonicalise to
    # `g.m-3` and are not remotely the same unit, while `mL` and `ml` share the
    # term and the magnitude and are two spellings of one. Only the second is a
    # collision worth a reader's time.
    collisions = collections.defaultdict(set)
    for row in rows:
        if row["canonical_term"]:
            key = (row["canonical_term"], row["canonical_magnitude"])
            collisions[key].add(row["validated_term"])

    return {
        "total": split(lambda r: True),
        "valid": split(lambda r: r["status"] == "valid"),
        "invalid": split(lambda r: r["status"] == "invalid"),
        "code_known": split(lambda r: r["code_known"] == "yes"),
        "arbitrary_units": split(
            lambda r: r["canonical_status"].startswith("arbitrary-unit")),
        # Distinct spellings that mean one unit: the reason canonical_term is
        # recorded at all. Only meaningful among the valid rows.
        "canonical_collisions": {
            f"{term} x{magnitude}": sorted(spellings)
            for (term, magnitude), spellings in sorted(collisions.items())
            if len(spellings) > 1
        },
    }


def report(rows, summary, top):
    total, valid, invalid = (summary["total"], summary["valid"],
                             summary["invalid"])
    log("")
    log(f"{total['distinct']} distinct unit string(s), "
        f"{total['occurrences']:,} occurrence(s)")
    log(f"  valid    {valid['distinct']:>4}  "
        f"{valid['occurrences']:>15,}")
    log(f"  invalid  {invalid['distinct']:>4}  "
        f"{invalid['occurrences']:>15,}")
    log(f"  a distinct Quantity.code was recorded on "
        f"{summary['code_known']['distinct']} of them")

    bad = [r for r in rows if r["status"] == "invalid"][:top]
    if bad:
        log(f"\nInvalid, by occurrence (top {len(bad)}):")
        for r in bad:
            log(f"  {r['occurrences']:>14,} {r['n_codes']:>4} code(s)  "
                f"{r['validated_term']!r}")

    if summary["canonical_collisions"]:
        log("\nDistinct spellings sharing one canonical form:")
        for term, spellings in summary["canonical_collisions"].items():
            log(f"  {term:<20} {', '.join(repr(s) for s in spellings)}")


# --------------------------------------------------------------------------- #

def main(argv=None):
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--shapes", default=DEFAULT_SHAPES,
                    help="observation-value-shapes.csv (default: %(default)s)")
    ap.add_argument("--out-dir", default=SCRIPT_DIR,
                    help="where to write the CSV + summary (default: next to "
                         "this script)")
    ap.add_argument("--top", type=int, default=25,
                    help="invalid units listed on the terminal, by descending "
                         "occurrence (default: %(default)s)")
    args = ap.parse_args(argv if argv is not None else sys.argv[1:])

    if not os.path.isfile(args.shapes):
        log(f"ERROR: not found: {args.shapes}")
        log("This script reads the committed extraction rather than a "
            "warehouse — see valueshapes/README.md if it is missing.")
        return 2

    log(f"Reading {args.shapes}")
    occurrences, n_codes, examples = read_inventory(args.shapes)
    log(f"{len(occurrences)} distinct unit string(s) to validate")

    # Imported here, not at module scope: it starts a JVM, and --help should
    # not pay for that.
    from ucumate import UCUMService
    svc = UCUMService()

    rows = build_rows(occurrences, n_codes, examples, svc)
    path, ordered = write_validation(rows, args.out_dir)
    summary = summarise(ordered)

    payload = {
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": os.path.relpath(args.shapes, MAPPING_DIR),
        "source_sha256": sha256(args.shapes),
        "validation_csv": VALIDATION_NAME,
        "validation_csv_sha256": sha256(path),
        "ucumate_version": importlib.metadata.version("ucumate"),
        "ucum_system": "http://unitsofmeasure.org",
        # Named in the output rather than only in the docstring, so a reader of
        # the JSON alone cannot mistake this for a complete picture.
        "not_observed": [
            "Quantity.system — selected by the extractor as qty_system but "
            "dropped before aggregation, so a UCUM code cannot be confirmed to "
            "sit under the UCUM system URI",
            "whether a bare label means code == unit or code absent — the "
            "committed encoding collapses the two; rows carry code_known: no",
        ],
        "summary": summary,
    }
    summary_path = os.path.join(args.out_dir, SUMMARY_NAME)
    with open(summary_path, "w") as fh:
        json.dump(payload, fh, indent=1)
        fh.write("\n")

    report(ordered, summary, args.top)
    log(f"\nWrote {path} ({len(ordered)} rows)")
    log(f"Wrote {summary_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
