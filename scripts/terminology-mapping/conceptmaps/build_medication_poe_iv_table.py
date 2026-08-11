#!/usr/bin/env python3
"""Generate conceptmaps/medication-poe-iv-standard.csv — the two POE order flags.

The only generator in this repo that makes NO network call, because there is
nothing to ask. `IV therapy` and `TPN` are the whole of
`mimic-medication-poe-iv`, they are bound to BOTH
MedicationRequest.medication[x] and MedicationAdministration.medication[x], and
neither is a medication:

    IV therapy   a POE order TYPE. The product being infused is recorded
                 elsewhere on the prescription.
    TPN          total parenteral nutrition: a patient-specific compounded
                 admixture whose composition is not in the code.

Together 353,392 occurrences: 167,144 on MedicationRequest.medication[x], which
is 8.9% of that element, and 186,248 on MedicationAdministration.medication[x].

ONE TABLE FOR BOTH ELEMENTS. Both codes are observed on both, so the population
is the same two rows either way and the union costs nothing. It still matters
that it is one file: two tables could state different reasons for declining the
same code, in two published ConceptMaps, with nothing to compare them. The
population comes from lib/builders.py, which discovers the fields declaring this
table rather than taking a list, so the reasons below are written once and
cannot be phrased against one element while serving two.

WHY THIS EXISTS AT ALL rather than a two-line hand-written CSV. Every mapping
table in this repo is generated, so that no row rests on a judgement a reader
cannot re-derive. A table committed by hand would be the single exception, and
the first question a reviewer would rightly ask is which other rows were typed
in. The decision here is not a lookup, so this script is short — but it is still
the thing that produced the file, and its reasoning is in one place.

WHY NOT SNOMED CT, even though SNOMED has concepts that fit. This stream could
reach `intravenous therapy` and `total parenteral nutrition` as procedures, and
declining to is deliberate. Those are PROCEDURE concepts, and putting one in a
column whose FHIRPath is `medication[x]` produces exactly the failure this repo
refuses everywhere else: a map that validates, resolves, and makes the data say
something it does not mean. A consumer projecting `medication[x]` would get a
procedure mixed in among drugs, with nothing to signal it.

The sibling stream DOES use SNOMED, for `Insulin` — but that is a substance
naming a drug class, so it stays inside what the column means. The difference is
the whole reason the SNOMED fallback there is constrained to `<<105590001
|Substance|` and not to procedures.

So both codes are declared unmapped with their reason, both
`unmapped-medication.csv` and `unmapped-medication-administration.csv` carry
them, and both ConceptMaps carry them as `unmatched` elements. The real fix is
one layer down, in the ETL, and is tracked in issue #26 of
fhnaumann/master_thesis_pipeline — not here, and not by mapping around it.

RxNorm was checked rather than assumed, at every term type in the sibling
stream's constraint:

    filter=intravenous therapy   -> 0 concepts
    filter=TPN                   -> 0
    filter=total parenteral      -> 0
    filter=parenteral nutrition  -> 0
    filter=nutrition             -> 4, all 'Ocean Blue Nutritionals' supplements

    make medication-poe-iv-table

Usage:
  uv run scripts/terminology-mapping/conceptmaps/build_medication_poe_iv_table.py
"""

import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common import paths                                          # noqa: E402
from conceptmaps.lib.builders import (describe_population,        # noqa: E402
                                      table_population)
from conceptmaps.lib.canonical import TABLE_DIR                    # noqa: E402

OUT_CSV = TABLE_DIR / "medication-poe-iv-standard.csv"
LOG_JSON = paths.OUTPUT / "medication-poe-iv-generation-log.json"

HEADER = ["mimic_code", "mimic_display",
          "target_system", "target_code", "target_display", "comment",
          "method", "join_rung",
          "codesearch_target", "codesearch_display", "codesearch_confidence",
          "codesearch_status", "codesearch_reasoning"]

# Keyed on the source code. A code with no entry here is a hard error rather
# than a blank row: this stream is two codes, and a third appearing means the
# CodeSystem changed under a decision that was made about its contents.
REASONS = {
    "IV therapy": (
        "Not a medication. `IV therapy` is a POE order type recording that "
        "intravenous therapy was ordered; the product infused is recorded "
        "elsewhere on the order. RxNorm names drug products and has no "
        "concept for an administration modality at any term type. A SNOMED CT "
        "procedure concept exists but is deliberately not used: this code sits "
        "in a column whose FHIRPath is medication[x], and a procedure code "
        "here would resolve correctly while making the data mean something "
        "else. See issue #26."),
    "TPN": (
        "Not a medication. `TPN` names total parenteral nutrition, a "
        "patient-specific compounded admixture whose composition the code does "
        "not carry. RxNorm has no concept for it because it is not a "
        "manufactured product. Declined for the same reason as `IV therapy`, "
        "and tracked in issue #26."),
}


def ig_codes():
    """The observed source codes for EVERY field that reads this table.

    Both bound elements admit both codes and the data uses both on both, so the
    union is the same two rows either field would produce alone. Discovered
    rather than hard-coded all the same: a third field adding this table would
    extend the population with nothing to keep in step, and a code observed only
    there would otherwise be silently missing from the file. See lib/builders.py.
    """
    return table_population(OUT_CSV)


def main():
    concepts = ig_codes()
    for element, count in describe_population(OUT_CSV):
        print(f"  {element:42s} {count:>6,} observed", file=sys.stderr)
    if unknown := set(concepts) - set(REASONS):
        sys.exit(f"  {sorted(unknown)} is in mimic-medication-poe-iv and "
                 f"observed on a bound element, but no reason is recorded for "
                 f"it. This stream declines every code it holds, so a new one "
                 f"is a decision to make, not a blank to fill.")

    rows = [{**{c: "" for c in HEADER},
             "mimic_code": code, "mimic_display": display,
             "comment": REASONS[code], "method": "declared",
             "codesearch_status": "not-attempted"}
            for code, display in sorted(concepts.items())]

    with open(OUT_CSV, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=HEADER, restval="")
        writer.writeheader()
        writer.writerows(rows)
    print(f"  wrote {OUT_CSV.name} ({len(rows)} row(s), all declined)",
          file=sys.stderr)

    LOG_JSON.parent.mkdir(parents=True, exist_ok=True)
    LOG_JSON.write_text(json.dumps({
        "elements": [element for element, _ in
                     describe_population(OUT_CSV)],
        # No constraint, template or threshold: nothing was searched. Recorded
        # as explicit nulls so lib/stats.py finds the keys it looks for and a
        # reader can tell "no search happened" from "the log is incomplete".
        "constraint_vcl": None,
        "template": None,
        "confidence_threshold": None,
        "note": ("No terminology service was contacted. Both codes are "
                 "declared unmapped by decision; see the module docstring and "
                 "issue #26."),
        "rows": rows,
    }, indent=1) + "\n")
    print(f"  wrote {LOG_JSON.name}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
