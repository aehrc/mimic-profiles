#!/usr/bin/env python3
"""Generate conceptmaps/medication-name-standard.csv — MIMIC drug names -> RxNorm.

The third generated table, and the first where code-search is the FALLBACK
rather than the method. Roughly three fifths of this population is resolved by
an exact normalised-term join against RxNorm's own designations: no model, no
confidence threshold, no judgement, and — measured, not assumed — no ambiguity
whatsoever. Only what the join cannot reach is sent to the service.

It follows build_micro_susc_table.py in shape: network generation is a separate
explicit target, the build stays offline and byte-reproducible, and the three
places a stream is allowed to differ are the constraint, the template and the
gate. See issue #25 for the probe evidence behind every number below.

    make medication-name-table ARGS=--insecure

WHY A DETERMINISTIC TIER EXISTS AT ALL. The other two tables map ICU flowsheet
labels and abbreviated antibiotic names — inputs with no chance of matching a
terminology's own strings. This population is different: it is a drug-NAME
column, so a large share of it already IS an RxNorm term, character for
character. Sending `Acetaminophen` to an LLM to be told `161 acetaminophen` is
paying a model to do a dictionary lookup, and worse, it makes the answer a
function of a service rather than of a committed file. The join settles those
rows in the repo, where they can be diffed.

That the join is unambiguous is a measured property of RxNorm, not a hope: over
the ingredient/brand/product term types every designation is distinct even
before normalisation, and the handful of keys that do collide after it are
deleted outright rather than tie-broken (see AMBIGUITY GUARD in refresh_index).
The exact counts are not repeated here, because they are a property of a RxNorm
release rather than of this file — they live in the index manifest, where a
release bump moves them and makes the change reviewable.

NORMALISATION IS ASYMMETRIC, and this is the subtle part. The obvious rule —
strip trailing parentheticals from both sides — is NOT deterministic and must
never be used: it produces 146 colliding keys, because in RxNorm a trailing
parenthetical is semantic rather than decorative.

    'polyvinyl alcohol'  -> six RxCUIs: (18000 MW), (40000 MW), (94000 MW), ...
    'Thyroid'            -> 10572 'thyroid (USP)' / 325521 'thyroid (beef)'
    'Pantoprazole'       -> 40790 [IN] / 236632 [PIN] '(as ... sesquihydrate)'

A term-type tie-break does not rescue it — 4 of the 11 label-level collisions are
within a single TTY. So the INDEX keeps its parentheticals and only the QUERY
drops them, as a late rung. That recovers 125 of the 134 rows the symmetric rule
would have won, with zero collisions.

The query rung that strips a parenthetical is LOSSY BUT NOT WRONG: it lands on
the ingredient, discarding a qualifier (`OxyCODONE (Immediate Release)` ->
`oxycodone`). Acceptable for a medication code at ingredient level, and recorded
as such per row in `join_rung` — but it must not be read as an exact-product
mapping.

CONSTRAINT_VCL. RxNorm's ingredient, brand and generic-product term types,
expressed as a VCL implicit ValueSet so nothing has to be published to the
shared terminology server:

    (rxnorm)(TTY=IN;TTY=PIN;TTY=MIN;TTY=BN;TTY=SCD;TTY=GPCK;TTY=BPCK)

73,214 codes. Note a VCL quirk: a bare `(system)` with no property clause is a
parse error, so an RxNorm constraint always needs at least one filter.

WHY SBD IS EXCLUDED, decided by A/B over the 70 highest-volume brand-like
labels (577 of the 2,888 are brand-like, 5.7% of occurrences — this is a
long-tail-of-codes question, not a volume one). Branded drug products are the
one term type where the service reliably asserts things the record never said:
with SBD in scope it accepted 7 targets carrying an invented brand, pack size or
strength (5,706 occurrences); without it, 2 (581). A 90% reduction.

The cost is 6 rows where a genuine branded product is now unreachable, and the
asymmetry is the argument: **A's errors are commissions, B's losses are
omissions.** On adjudication 5 of the 6 losses still return a true
generalisation of the label — `SymlinPen 120` reaches `pramlintide 1 MG/ML Pen
Injector`, `Stalevo 100` the identical composition minus the brand. Mapping
`Fluticasone-Salmeterol Diskus (500/50)` onto `ADVAIR DISKUS ... 14 Blisters` is
a data-integrity defect; mapping it onto the unbranded clinical drug is merely
less specific.

Two honest limits on that result. Dropping SBD fixes BRAND invention and not
STRENGTH invention — `BuPROPion XL (Once Daily)` still reaches an invented
300 MG, just without the invented brand — and fixing that would mean dropping
SCD, which is not on the table. And two of the four headline SBD failures were
really BN-retrieval misses wearing an SBD costume: `196466 Taxol` and
`203321 Lithobid` are inside the constraint and the service passed over them.

The obvious constraint is the wrong one. Restricted to TTY=SCD alone, the
service cannot answer the many ingredient-only labels MIMIC uses, and where it
does answer it FABRICATES a strength and dose form the source never stated:
`Phenytoin Sodium` becomes `phenytoin sodium 100 MG Oral Capsule` at 0.50, and
`*NF* Budesonide` becomes `budesonide 0.2 MG Inhalation Powder` at 0.50. Over 28
probe labels SCD-only declined 11 — including concepts it plainly knew — and
invented detail on 7 more. The union declined 5, all correctly. TTY=IN alone
fails in the other direction, collapsing `Warfarin 2.5mg Tablet` to bare
`warfarin` and discarding a strength MIMIC does record.

The constraint is genuinely applied, verified two ways: obviously-non-drug text
(`Appendectomy`) returns NO MATCH, and — the stronger proof — `Dexmedetomidine`
returns 48937 under the union and NO MATCH under TTY=SCD, i.e. the service
refuses a concept it knows because it is out of scope.

TEMPLATE: none. Unlike the ICU d_items labels, where `Foley Catheter` names a
device and leaves the procedure implicit, these strings already ARE drug names;
there is nothing for a template to supply. Tested and rejected: a wrapper was
neutral on correctness but inflated confidence uniformly toward the threshold —
exactly backwards when confidence is the only defence — and converted the
service's exact-term fast path into agentic calls, a ~60x latency penalty on the
majority of the population.

THRESHOLD 0.85, not the repo default 0.80. The deciding row is `Senna`, at
32,762 occurrences: at 0.80 it is mapped to `2166041 Senna pod`, a botanical
plant part rather than the laxative, and wrong-mapped occurrence mass triples
from 1.2% to 3.5%. Raising further is worse — 0.90 removes one more wrong answer
while destroying 18 correct ones including the single most frequent code in the
element.

THE INGREDIENT FALLBACK, and the exact condition that fires it. When the primary
call yields NO ACCEPTED ANSWER, the label is retried against ingredient term
types alone. This exists because the service gives up when the FORM it is asked
for is unreachable, even though the ingredient was in scope and correct:
`OxyCODONE (Immediate Release)` (18,323 occurrences) and `Lactulose Enema` both
did exactly that, with `7804 oxycodone` and `6218 lactulose` sitting in the
constraint the whole time.

The trigger is "no accepted answer" — NOMATCH **or** below threshold — and NOT
NOMATCH alone. This is not a detail. Under the old SBD-inclusive constraint both
motivating labels were genuine NOMATCHes, but under the constraint above they
come back below-threshold instead (`OxyCODONE (Immediate Release)` proposes an
invented 5 MG tablet at 0.80), so a NOMATCH-only trigger would silently fail to
fire on the 18,323-occurrence case the fallback was built for. Measured over the
A/B set the fallback converts 9 labels / 19,604 occurrences, all 9 correct, none
wrong — and it converts none of the four labels that must stay declined
(`Insulin`, `IV therapy`, `TPN`, `Influenza Vaccine Quadrivalent` all return
NOMATCH under the ingredient constraint too).

THE SNOMED FALLBACK, and its deliberate limit. A few labels name a drug CLASS,
which RxNorm does not model: `Insulin` at 122,879 occurrences has no generic
ingredient concept in the 20231106 release (RxCUI 5856 is retired and 404s),
only 49 specific insulins. SNOMED CT does — `67866001 |Insulin|` — so a third
rung searches SNOMED substances.

It is constrained to `<<105590001 |Substance|` and NOT to procedures, however
tempting `IV therapy` looks. Giving that label a procedure code would put a
procedure in a column whose FHIRPath is `medication[x]`, which is the
"looks right, means something else" failure this repo refuses everywhere else.
`IV therapy` and `TPN` are a modelling defect one layer down; issue #26 tracks
the real fix, and here they are declared unmapped.

THE GATE, per target system, applied as a filter rather than an assertion:
  RxNorm  membership of CONSTRAINT_VCL, asserted with $validate-code against
          the VCL URL rather than assumed from having asked politely.
  SNOMED  the same four checks build_d_items_table.py makes — exists, active,
          international core module rather than a national extension, and the
          display really is a designation. The module check is not decorative:
          searching `insulin` under the substance ECL returns AU-extension
          concepts that resolve on velonto and nowhere else.
Target displays are then replaced with the server's preferred term, so
verify-curated's display check passes by construction.

NOT PART OF `make mappings`: it needs the network and a model-backed service,
and it WRITES a build input. Determinism lives in the split — this runs by hand,
its output is committed, and the build reads the committed CSV and never a
server.

THE TABLE IS SHARED BETWEEN TWO BOUND ELEMENTS, and its population is therefore
not one field's. `mimic-medication-name` is bound to both
MedicationRequest.medication[x] (2,888 observed codes) and
MedicationAdministration.medication[x] (3,620), overlapping in 2,600. A table
per field over those sets is a way to publish two different RxNorm concepts for
one MIMIC drug name, in two ConceptMaps, with nothing in the repo to notice: the
term-join tier would agree by construction, but code-search re-asked on the
shared residual can answer differently, and no check compares two tables.

So the table is keyed by its SOURCE CodeSystem, not by the field that reads it,
and lib/builders.py discovers which fields those are rather than taking a list —
adding this table to a third field extends the population with nothing to keep
in step. lib/curated.py validates rows against the CodeSystem enumeration for
the same reason; a row belonging to a sibling population is simply never looked
up by the field that does not map that code.

--append IS WHAT MAKES SHARING CHEAP. Without it, adding one field's 1,020 new
codes means re-asking the service for all 3,908 and rewriting rows that were
generated, reviewed and committed for a map that is already built. With it the
committed rows are kept verbatim — including the declined ones, which are
answers and are the most expensive calls in the run — and only codes with no row
are asked. It refuses if the committed log's settings differ from this script's
constants: the log states one constraint, template and threshold for the whole
table, so appending across a settings change would attribute today's settings to
yesterday's rows. Moving a setting means regenerating in full.

Usage:
  uv run .../build_medication_name_table.py --refresh-index --insecure
  uv run .../build_medication_name_table.py --insecure
  uv run .../build_medication_name_table.py --append --insecure
  uv run .../build_medication_name_table.py --only Senna,Insulin --insecure
"""

import argparse
import concurrent.futures
import csv
import hashlib
# NOT `import http.client`: the fhirclient import below binds the name `http` to
# a function, so `HTTPException` in find_code's except clause would raise
# AttributeError instead of retrying — silently defeating the retry loop on
# exactly the transport failures it exists to absorb.
from http.client import HTTPException
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common import fhirclient                                     # noqa: E402
from common.cli import add_common_args, DEFAULT_CODE_SEARCH       # noqa: E402
from common.fhirclient import configure_tls, http                 # noqa: E402
from common import paths                                          # noqa: E402
from conceptmaps.lib.builders import (describe_population,        # noqa: E402
                                      table_population)
from conceptmaps.lib.canonical import RXNORM, SNOMED, TABLE_DIR    # noqa: E402
# The keying and the index reader live in lib/ because the index is a COMMITTED
# file that build_formulary_drug_table.py also joins against. Two copies of r3
# that drifted by one character would not raise anything — the join would
# silently shrink and the rows it used to settle would be re-answered by the
# service. See lib/termindex.py.
from conceptmaps.lib.termindex import (INDEX_MANIFEST, INDEX_TSV,  # noqa: E402
                                       load_index, query_rungs, r3, salted)

OUT_CSV = TABLE_DIR / "medication-name-standard.csv"
LOG_JSON = paths.OUTPUT / "medication-name-generation-log.json"

# The RxNorm release the index and the table were built from. Asserted on every
# run against what the server echoes back: a silent release bump would change
# committed answers with no diff to explain them. NOT pinned into the map —
# see lib/canonical.py UNVERSIONED_SYSTEMS for why those are different claims.
RXNORM_VERSION = "20231106"

CONSTRAINT_VCL = (f"({RXNORM})"
                  "(TTY=IN;TTY=PIN;TTY=MIN;TTY=BN;TTY=SCD;TTY=GPCK;TTY=BPCK)")

# Rung 2: ingredient term types only. See THE INGREDIENT FALLBACK above.
INGREDIENT_VCL = f"({RXNORM})(TTY=IN;TTY=PIN;TTY=MIN)"

# Rung 3: SNOMED substances, for labels naming a drug class. Substances only —
# emphatically not procedures. See THE SNOMED FALLBACK above.
SNOMED_ECL = "<<105590001"

CONFIDENCE_THRESHOLD = 0.85

# No template. The label is sent bare; see TEMPLATE above.
TEMPLATE = "{}"

# SNOMED CT international core. A national extension resolves on the server it
# was authored against and nowhere else, which is invisible from reading a CSV.
INTERNATIONAL_CORE = "900000000000207008"

CURATED_HEADER = [
    "mimic_code", "mimic_display",
    "target_system", "target_code", "target_display", "comment",
    # Provenance: read by lib/stats.py and discarded by the build. Recorded on
    # every row INCLUDING the ones where the proposal was then rejected, so any
    # mapping and any non-mapping can be audited from the CSV alone.
    "method", "join_rung",
    "codesearch_target", "codesearch_display", "codesearch_confidence",
    "codesearch_status", "codesearch_reasoning",
]

# --------------------------------------------------------------------------- #
# Tier 1: the term index.
#
# The keying (`r3`, `salted`, `deparenthesised`, `query_rungs`) and the reader
# (`load_index`) moved to lib/termindex.py when a second generator began joining
# against this same committed file. Refreshing it stays here, because this
# script's CONSTRAINT_VCL is what decides which RxNorm concepts it covers.
# --------------------------------------------------------------------------- #

def constraint_url(vcl=None):
    """A VCL expression as a resolvable implicit-ValueSet canonical."""
    return ("http://fhir.org/VCL?v1="
            + urllib.parse.quote(vcl or CONSTRAINT_VCL, safe=""))


def snomed_url(ecl=None):
    """A SNOMED ECL as its implicit-ValueSet canonical.

    NOT the VCL form. SNOMED CT has its own implicit ValueSet syntax and that is
    what the server and code-search resolve; a VCL wrapper round an ECL string
    404s, which is how this was found.
    """
    return (f"{SNOMED}?fhir_vs=ecl/"
            + urllib.parse.quote(ecl or SNOMED_ECL, safe=""))


# The rungs, in the order build_row tries them: (constraint URL, target system).
# Each is a resolvable canonical, so code-search and $validate-code are asked
# about exactly the same search space.
def rungs():
    return ((constraint_url(CONSTRAINT_VCL), RXNORM),
            (constraint_url(INGREDIENT_VCL), RXNORM),
            (snomed_url(), SNOMED))


def get(fhir_base, path, **params):
    """A GET returning the parsed body, or None. Non-200 is not an answer."""
    query = urllib.parse.urlencode(params)
    status, body = http("GET", f"{fhir_base.rstrip('/')}/{path}?{query}")
    return body if status == 200 and body else None


def _expand_page(fhir_base, vcl, offset, count):
    body = get(fhir_base, "ValueSet/$expand", url=constraint_url(vcl),
               offset=offset, count=count, includeDesignations="true")
    if body is None:
        raise RuntimeError(f"$expand failed at offset {offset}")
    return body


def refresh_index(fhir_base, page=5000):
    """Pull CONSTRAINT_VCL with designations and write the committed term index.

    AMBIGUITY GUARD. Any key reaching more than one RxCUI is DELETED rather
    than resolved by a tie-break. A tie-break would be a per-row judgement
    smuggled into the one tier that exists to have none, and — measured — the
    collisions are not tie-breakable anyway: several are within a single term
    type. Deleting them costs three keys, none of which any MIMIC label uses,
    and it is what makes a future RxNorm release fail closed instead of
    silently changing an answer.
    """
    print(f"  expanding {CONSTRAINT_VCL}", file=sys.stderr)
    by_key, offset, total, terms = {}, 0, None, 0
    while total is None or offset < total:
        bundle = _expand_page(fhir_base, CONSTRAINT_VCL, offset, page)
        expansion = bundle["expansion"]
        if total is None:
            total = expansion.get("total")
            _assert_version(expansion)
            print(f"  {total:,} codes", file=sys.stderr)
        contains = expansion.get("contains", [])
        if not contains:
            break
        for concept in contains:
            strings = {concept.get("display", "")}
            strings |= {d.get("value", "")
                        for d in concept.get("designation", [])}
            terms += len(strings)
            for text in strings:
                if not (key := r3(text)):
                    continue
                for variant in {key, salted(key)} - {None}:
                    by_key.setdefault(variant, set()).add(concept["code"])
        offset += len(contains)
        print(f"    {offset:,}/{total:,}", end="\r", file=sys.stderr)

    ambiguous = sorted(k for k, v in by_key.items() if len(v) > 1)
    for key in ambiguous:
        del by_key[key]
    print(f"\n  {len(by_key):,} keys, {len(ambiguous)} ambiguous key(s) dropped",
          file=sys.stderr)

    with open(INDEX_TSV, "w", newline="") as fh:
        for key in sorted(by_key):
            fh.write(f"{key}\t{next(iter(by_key[key]))}\n")
    digest = hashlib.sha256(INDEX_TSV.read_bytes()).hexdigest()
    INDEX_MANIFEST.write_text(json.dumps({
        "description": (
            "Derived from the RxNorm designations reachable through "
            "constraint_vcl. Committed so the deterministic tier of "
            "build_medication_name_table.py is a pure function of this repo. "
            "The counts and the digest are tripwires: a RxNorm release bump "
            "changes them, which makes it a reviewable diff instead of a "
            "silent change to committed answers."),
        "system": RXNORM,
        "version": RXNORM_VERSION,
        "constraint_vcl": CONSTRAINT_VCL,
        "codes": total,
        "terms": terms,
        "keys": len(by_key),
        "ambiguous_keys_dropped": len(ambiguous),
        "ambiguous_keys": ambiguous,
        "tsv_sha256": digest,
    }, indent=1) + "\n")
    print(f"  wrote {INDEX_TSV.name} and {INDEX_MANIFEST.name}",
          file=sys.stderr)


def _assert_version(expansion):
    """Fail closed if the server is serving a different RxNorm release."""
    for parameter in expansion.get("parameter", []):
        value = parameter.get("valueUri") or parameter.get("valueString") or ""
        if value.startswith(f"{RXNORM}|") and not value.endswith(
                f"|{RXNORM_VERSION}"):
            sys.exit(f"  server is serving {value}, this table is built "
                     f"against {RXNORM}|{RXNORM_VERSION}. Refusing to mix "
                     f"releases: re-pin RXNORM_VERSION and --refresh-index "
                     f"deliberately, and review the resulting diff.")


# --------------------------------------------------------------------------- #
# Tier 2: code-search.
# --------------------------------------------------------------------------- #

def find_code(service, text, url, system, timeout, attempts=4):
    """code-search's best match for `text`, constrained to `url`.

    Retries transport failures for the reason build_d_items_table.py gives: a
    dropped connection is not an answer, and a run that quietly mixes 'no match'
    with 'the service was not running' produces a table that understates
    coverage and reads exactly like a real result. Exhausted retries raise, and
    main() refuses to write the CSV.
    """
    body = json.dumps({
        "text": TEMPLATE.format(text),
        "url": url,
        "system": system,
        "max_candidates": 1,
        "effort": "balanced",
    }).encode()
    last = None
    for attempt in range(attempts):
        request = urllib.request.Request(
            f"{service.rstrip('/')}/api/v1/find-code", data=body,
            headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(
                    request, timeout=timeout,
                    context=fhirclient.SSL_CONTEXT) as response:
                return json.load(response)
        except (urllib.error.URLError, ConnectionError, TimeoutError,
                HTTPException) as exc:
            last = exc
            if attempt < attempts - 1:
                time.sleep(2 ** attempt)
    raise RuntimeError(f"{attempts} attempt(s) failed: {last}")


def best(answer):
    """(code, display, confidence, reasoning) or None, from a find-code reply."""
    matches = (answer or {}).get("matches") or []
    if not matches:
        return None
    top = matches[0]
    return (top.get("code"), top.get("display", ""),
            float(top.get("confidence", 0.0)), top.get("reasoning", ""))


# --------------------------------------------------------------------------- #
# The gate.
# --------------------------------------------------------------------------- #

def in_constraint(fhir_base, code, url, system):
    """True if `code` is a member of `vcl`, per the server. Asserted, not assumed."""
    result = get(fhir_base, "ValueSet/$validate-code",
                 url=url, system=system, code=code)
    if result is None:
        return False
    return any(p.get("name") == "result" and p.get("valueBoolean")
               for p in result.get("parameter", []))


def snomed_gate(fhir_base, code):
    """(ok, preferred_display) for a SNOMED target: exists, active, core module.

    The module check is the one a reader of the CSV cannot make. An AU- or
    US-extension concept resolves on the server it was picked from and nowhere
    else, and searching `insulin` under the substance ECL genuinely returns
    them.
    """
    result = get(fhir_base, "CodeSystem/$lookup", system=SNOMED, code=code)
    if result is None:
        return False, ""
    display, properties = "", {}
    for parameter in result.get("parameter", []):
        if parameter.get("name") == "display":
            display = parameter.get("valueString", "")
        elif parameter.get("name") == "property":
            part = {p["name"]: p for p in parameter.get("part", [])}
            name = part.get("code", {}).get("valueCode")
            value = part.get("value", {})
            properties[name] = (value.get("valueCode")
                                or value.get("valueString")
                                or value.get("valueBoolean"))
    if properties.get("inactive") is True:
        return False, display
    if str(properties.get("moduleId", "")) != INTERNATIONAL_CORE:
        return False, display
    return True, display


def rxnorm_display(fhir_base, code):
    """The server's preferred term, so verify-curated's display check passes."""
    result = get(fhir_base, "CodeSystem/$lookup", system=RXNORM, code=code)
    if result is None:
        return ""
    return next((p.get("valueString", "") for p in result.get("parameter", [])
                 if p.get("name") == "display"), "")


# --------------------------------------------------------------------------- #
# Resolving one row.
# --------------------------------------------------------------------------- #

def build_row(code, display, index, fhir_base, service, timeout):
    """One CSV row: the deterministic tier first, then the service."""
    row = {c: "" for c in CURATED_HEADER}
    row["mimic_code"], row["mimic_display"] = code, display

    for rung, key in query_rungs(display):
        if (rxcui := index.get(key)):
            row.update(method="term-join", join_rung=rung,
                       target_system=RXNORM, target_code=rxcui,
                       target_display=rxnorm_display(fhir_base, rxcui)
                                      or display,
                       codesearch_status="not-needed")
            return row

    row["method"] = "code-search"
    for url, system in rungs():
        answer = best(find_code(service, display, url, system, timeout))
        if answer is None:
            continue
        target, proposed, confidence, reasoning = answer
        row.update(codesearch_target=target, codesearch_display=proposed,
                   codesearch_confidence=f"{confidence:.2f}",
                   codesearch_reasoning=reasoning)
        if confidence < CONFIDENCE_THRESHOLD:
            row["codesearch_status"] = "below-threshold"
            continue
        if system == SNOMED:
            ok, preferred = snomed_gate(fhir_base, target)
            if not ok:
                row["codesearch_status"] = "gate-failed"
                continue
        else:
            if not in_constraint(fhir_base, target, url, system):
                row["codesearch_status"] = "out-of-constraint"
                continue
            preferred = rxnorm_display(fhir_base, target) or proposed
        row.update(codesearch_status="ok", target_system=system,
                   target_code=target, target_display=preferred)
        return row

    row["codesearch_status"] = row["codesearch_status"] or "no-match"
    return row


def declined_comment(row):
    """Why a blank target is a DECISION. A blank one with no reason is fatal
    in lib/curated.py, and rightly: a reader cannot audit silence."""
    proposal = (f"{row['codesearch_target']} "
                f"'{row['codesearch_display']}' at "
                f"{row['codesearch_confidence']}")
    return {
        "no-match": (f"code-search returned no match within "
                     f"{CONSTRAINT_VCL}, its ingredient-only subset, or "
                     f"SNOMED CT {SNOMED_ECL}."),
        "below-threshold": (f"code-search proposed {proposal}, below the "
                            f"{CONFIDENCE_THRESHOLD} threshold."),
        "out-of-constraint": (f"code-search proposed {proposal} but that code "
                              f"is not a member of the search constraint."),
        "gate-failed": (f"code-search proposed {proposal} but that concept is "
                        f"inactive or outside the SNOMED CT international "
                        f"core module."),
    }.get(row["codesearch_status"], f"code-search: {row['codesearch_status']}.")


# --------------------------------------------------------------------------- #

def ig_codes():
    """The observed source codes for EVERY field that reads this table.

    Not one element's population. `mimic-medication-name` is bound to both
    MedicationRequest.medication[x] and MedicationAdministration.medication[x],
    which observe overlapping-but-different subsets of it, and one table over
    the union is what stops this repo publishing two different RxNorm concepts
    for one MIMIC drug name. lib/builders.py discovers which fields those are
    rather than taking a list, so adding the table to a third field extends the
    population with nothing to keep in step.
    """
    return table_population(OUT_CSV)


def read_committed():
    """The committed table as {code: row}, or {} if there is none yet."""
    if not OUT_CSV.is_file():
        return {}
    with open(OUT_CSV, newline="") as fh:
        return {row["mimic_code"]: row for row in csv.DictReader(fh)}


def assert_same_settings():
    """Refuse to append onto rows generated under different settings.

    The generation log records constraint, template and threshold ONCE, at top
    level, and lib/stats.py reads them as the settings that produced every row.
    Appending to a table whose committed rows predate a settings change would
    make that a lie — the log would describe the new rows and be quoted for all
    of them. Fail closed instead, the same shape as the RxNorm version assertion
    the index already makes: a full regeneration is the correct response to
    moving a setting.
    """
    if not LOG_JSON.is_file():
        sys.exit(f"  --append needs {LOG_JSON.name} to check the committed "
                 f"rows were generated under today's settings, and it is "
                 f"missing. Run a full generation instead.")
    log = json.loads(LOG_JSON.read_text())
    current = {"constraint_vcl": CONSTRAINT_VCL,
               "ingredient_fallback_vcl": INGREDIENT_VCL,
               "snomed_fallback_ecl": SNOMED_ECL,
               "template": TEMPLATE,
               "confidence_threshold": CONFIDENCE_THRESHOLD,
               "rxnorm_version": RXNORM_VERSION}
    drifted = {k: (log.get(k), v) for k, v in current.items()
               if log.get(k) != v}
    if drifted:
        detail = "\n".join(f"      {k}: log {was!r} -> now {now!r}"
                            for k, (was, now) in sorted(drifted.items()))
        sys.exit(f"  --append refused: the committed rows were generated under "
                 f"different settings.\n{detail}\n"
                 f"    The log states one set of settings for the whole table, "
                 f"so appending would attribute today's to yesterday's rows. "
                 f"Regenerate the table in full.")


def report(rows):
    print(f"\n  {len(rows):,} row(s)", file=sys.stderr)
    by_method = Counter(r["method"] for r in rows)
    for method, n in by_method.most_common():
        print(f"    {method or '(none)':14s} {n:>6,}", file=sys.stderr)
    print("\n  join rung", file=sys.stderr)
    for rung, n in Counter(r["join_rung"] for r in rows
                           if r["join_rung"]).most_common():
        print(f"    {rung:14s} {n:>6,}", file=sys.stderr)
    print("\n  code-search status", file=sys.stderr)
    for status, n in Counter(r["codesearch_status"] for r in rows
                             if r["codesearch_status"]).most_common():
        print(f"    {status:18s} {n:>6,}", file=sys.stderr)
    print("\n  target system", file=sys.stderr)
    for system, n in Counter(r["target_system"] for r in rows
                             if r["target_code"]).most_common():
        print(f"    {system:50s} {n:>6,}", file=sys.stderr)
    mapped = sum(1 for r in rows if r["target_code"])
    print(f"\n  {mapped:,}/{len(rows):,} mapped "
          f"({100 * mapped / len(rows):.1f}%)", file=sys.stderr)


def main():
    ap = argparse.ArgumentParser(
        description=__doc__.split("\n\n")[0],
        formatter_class=argparse.RawDescriptionHelpFormatter)
    add_common_args(ap)
    ap.add_argument("--code-search", default=DEFAULT_CODE_SEARCH
                    or "http://localhost:3000",
                    help="code-search base URL (default: $CODE_SEARCH_URL "
                         "or %(default)s)")
    ap.add_argument("--refresh-index", action="store_true",
                    help="re-pull the RxNorm term index, then exit. Network; "
                         "review the resulting diff before committing.")
    ap.add_argument("--workers", type=int, default=8,
                    help="concurrent code-search calls (default: %(default)s)")
    ap.add_argument("--timeout", type=int, default=120)
    ap.add_argument("--only", help="comma-separated MIMIC codes, for probing. "
                                   "WITHOUT --append this REWRITES the table "
                                   "to just those rows")
    ap.add_argument("--append", action="store_true",
                    help="keep every committed row and ask the service only "
                         "for codes that have none. Refuses if the committed "
                         "log's settings differ from this script's")
    args = ap.parse_args()

    fhir_base = (args.fhir_base or "").rstrip("/")
    if not fhir_base:
        sys.exit("  no --fhir-base and $ONTOSERVER_URL unset.")
    configure_tls(args.ca_bundle, args.insecure)

    if args.refresh_index:
        refresh_index(fhir_base)
        return 0

    index, manifest = load_index(CONSTRAINT_VCL)
    print(f"  term index: {len(index):,} keys, {manifest['system']}|"
          f"{manifest['version']}", file=sys.stderr)

    concepts = ig_codes()
    for element, count in describe_population(OUT_CSV):
        print(f"  {element:42s} {count:>6,} observed", file=sys.stderr)
    print(f"  {len(concepts):,} distinct source code(s) across "
          f"{len(describe_population(OUT_CSV))} element(s)", file=sys.stderr)

    if args.only:
        wanted = {c.strip() for c in args.only.split(",")}
        concepts = {k: v for k, v in concepts.items() if k in wanted}
        if missing := wanted - set(concepts):
            sys.exit(f"  --only names code(s) not in the observed population: "
                     f"{sorted(missing)}")

    carried = {}
    if args.append:
        assert_same_settings()
        carried = read_committed()
        # Carried rows are kept verbatim, including the declined ones: a row
        # that says the service found nothing is an answer, and re-asking it
        # would spend the most expensive calls in the run re-deriving it.
        concepts = {k: v for k, v in concepts.items() if k not in carried}
        print(f"  --append: {len(carried):,} committed row(s) kept, "
              f"{len(concepts):,} to generate", file=sys.stderr)
        if not concepts:
            print("  nothing to do — every code already has a row.",
                  file=sys.stderr)
            return 0
    elif args.only:
        print(f"  WARNING: --only without --append rewrites {OUT_CSV.name} to "
              f"{len(concepts)} row(s). Add --append to keep the rest.",
              file=sys.stderr)

    rows, failed = [], []
    with concurrent.futures.ThreadPoolExecutor(args.workers) as pool:
        futures = {pool.submit(build_row, code, display, index, fhir_base,
                               args.code_search, args.timeout): code
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
        # died is indistinguishable from one where the service said no.
        for code, exc in failed[:5]:
            print(f"    {code}: {exc}", file=sys.stderr)
        sys.exit(f"\n  {len(failed)} of {len(concepts)} call(s) failed. "
                 f"Refusing to write a table that would understate coverage.")

    for row in rows:
        if not row["target_code"]:
            row["comment"] = declined_comment(row)
    # Committed rows first so a generated row can never silently replace one;
    # `concepts` was already narrowed to the codes that had none.
    rows = list(carried.values()) + rows
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
        "constraint_vcl": CONSTRAINT_VCL,
        "constraint_url": constraint_url(),
        "ingredient_fallback_vcl": INGREDIENT_VCL,
        "snomed_fallback_ecl": SNOMED_ECL,
        "template": TEMPLATE,
        "confidence_threshold": CONFIDENCE_THRESHOLD,
        "rxnorm_version": RXNORM_VERSION,
        "term_index": {k: manifest[k] for k in
                       ("codes", "terms", "keys", "ambiguous_keys_dropped",
                        "tsv_sha256")},
        "rows": rows,
    }, indent=1) + "\n")
    print(f"  wrote {LOG_JSON.name}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
