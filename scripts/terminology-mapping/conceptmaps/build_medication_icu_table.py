#!/usr/bin/env python3
"""Generate conceptmaps/medication-icu-standard.csv — MIMIC ICU flowsheet
medication items -> RxNorm and SNOMED CT.

Stream 5 of MedicationAdministration.medication[x] (issue #27), and the last
one: 324 observed codes carrying 8,978,893 occurrences, 24.4% of the element.
It follows build_formulary_drug_table.py in shape — the committed term index
first, code-search only for what the index cannot reach, the build offline and
byte-reproducible — and differs from it in exactly two places, both forced by
evidence recorded in #27: the SNOMED CONSTRAINT, and the SNOMED GATE.

    make medication-icu-table ARGS=--insecure

SAME RxNorm CONSTRAINT AS THE TWO SIBLING STREAMS, to the character:

    (rxnorm)(TTY=IN;TTY=PIN;TTY=MIN;TTY=BN;TTY=SCD;TTY=GPCK;TTY=BPCK)

which is what lets this generator join against the committed term index rather
than pull its own; lib/termindex.load_index asserts the two agree. TTY=SBD stays
out, carried over from the A/B build_formulary_drug_table.py records rather than
re-tested here — and this stream's own evidence points the same way, since its
characteristic RxNorm error is already the invention of a dose form the label
never stated, which a wider brand-product space can only make more likely.

THE SNOMED RUNG IS NOT `<<105590001 |Substance|`, AND THAT IS THIS STREAM'S ONE
REAL DESIGN CHANGE. Asked for the ICU label `Solution` — 561,934 occurrences,
the largest item the term index cannot settle — the substance rung answers
`8537005 |Solution|` at confidence 1.00, which is a correct reading of the text
and a physical-state category rather than anything administered. It is the
`Foley Catheter` failure of the Procedure map repeating: the worst answer scores
highest, so no threshold reaches it. Two more of the same shape sit in the
enteral slice, where the model latches onto an English modifier rather than the
brand — `Replete with Fiber` -> `37202001 |Plant fibre|` and `Vital High
Protein` -> `228065003 |High protein food|`, both at exactly 0.80.

Narrowing by SUBTRACTION was tried first and does not work, because SNOMED's
substance hierarchy is poly-hierarchical and every grouper cuts across the
distinction this needs. Measured against the terminology server:

    MINUS <<256248008 |Plant material|   also removes morphine, hydromorphone,
                                         naloxone, senna
    MINUS <<115669006 |Substance categorised by physical state|
                                         also removes iron, calcium, dextran 40
                                         AND operative salvaged blood
    MINUS <<762766007 |Edible substance| also removes arginine, cranberry
                                         extract, docosahexaenoic acid

A candidate built from those exclusions rejected 21 rows of legitimate drug
substances in the two already-committed sibling tables. So the constraint is a
POSITIVE ENUMERATION of what the rung is for — see SNOMED_ECL. Verified 26/26
with $validate-code: it rejects Solution, Plant fibre, High protein food, Fruit
juice, Whey protein, Nutritionally complete liquid supplement, Vial, Breast
pump, Enema and Administration of medicine, and admits the blood components,
the parenteral-nutrition and multivitamin agents, and every drug substance and
medicinal product the sibling tables legitimately use.

It also admits `346447007 |Fresh frozen plasma|`, which lives in the Blood
product branch and which `<<105590001` excluded — so MIMIC's FFP is mappable
here rather than declining for a reason that was an artefact of the constraint.

THE SNOMED GATE NOW ASSERTS THE CONSTRAINT, which the sibling generators do not
and should. Their snomed_gate checks that a target exists, is active and is in
the international core module, and stops there — while the RxNorm rungs prove
membership with $validate-code rather than assuming it from having asked
politely. Nothing therefore checked that code-search answered from inside the
ECL it was given. It does not always: 24 distinct SNOMED targets in the two
committed sibling tables are outside their declared `<<105590001`, four of them
wrong in the way this repo exists to prevent (`breast pump` -> |Breast pump|,
a formulary display of `Vial` -> |Vial|). Repairing those tables is #27's open
decision, not this stream's; asserting the ECL here is not optional either way.

BLOOD COMPONENTS ARE WHY THE SNOMED RUNG SURVIVES AT ALL. `225168 Packed Red
Blood Cells`, `220970 Fresh Frozen Plasma`, `225170 Platelets`, `225171
Cryoprecipitate` and `226372 OR Cell Saver Intake` are administered, recorded on
this element, and absent from RxNorm at every term type. They are the one
population here that needs a non-RxNorm answer, and each probed target was
adjudicated right.

THRESHOLD 0.80, the formulary stream's, and the band was adjudicated row by row
rather than inherited. Admitted at 0.80 and lost at 0.85: `Insulin - Regular`
284,527 occ, `Fentanyl (Concentrate)` 110,978, `LR` 108,282, `Acetaminophen-IV`
64,989, `Packed Red Blood Cells` 53,091, `Albumin 5%` 26,096, `Amiodarone
600/500` 7,759 — all correct. Wrong in the same band: `Furosemide (Lasix)
250/50` 18,713 and `NaCl 3% (Hypertonic Saline)` 8,504. That is 680,716
occurrences of correct mapping against 27,217 of error, 25:1, and raising the
gate would delete the largest ICU drug label in the stream.

The threshold is also the wrong instrument for the two errors it would catch.
Both share one signature — RxNorm inventing a dose form or a pack size the label
never stated (`250/50` read as a 250 MG Oral Tablet; `NaCl 3%` as an Inhalation
Solution; `D5NS` as `in 1000 ML`) — and the same failure at 0.85 on `Bactrim`
would survive it. Those four rows, 33,637 occurrences, 0.37% of the stream, are
this table's known defect. See KNOWN DEFECTS below.

TEMPLATE: none, and this is the one place the ICU population looks like the
d_items procedure table and turns out not to behave like it. A wrapper was the
obvious candidate — these are flowsheet labels, and the Procedure map needed one
— but three independent wrappers, A/B'd over ~20 labels, ALL returned exactly
0.85 for every probe, collapsing 1.00, 0.95 and 0.65 bare scores onto one value.
The scorer grades the wrapper, not the label. Acceptance would become a function
of a sentence this repo wrote, the threshold would stop discriminating, and
`Solution` would arrive at 0.85 on `18629005 |Administration of medicine|` — a
PROCEDURE — instead of being rejected by the constraint. A route template does
repair the dose-form errors above, and that is a real benefit declined for a
real reason.

NORMALISATION: QUERY-SIDE ONLY, two rules, both narrow. The committed
`mimic_display`, the source enumeration and the term index are untouched.

  N1  strip a trailing rate-fraction suffix — `(Full)`, `(3/4)`, `(2/3)`,
      `(1/2)`, `(1/4)`. 77 codes collapse to 25 distinct products. Adopted for
      DETERMINISM, not coverage: the suffix never changes WHICH code comes back,
      but it moves confidence by 0.10-0.25, and in two of four probed pairs that
      crosses the gate. Unstripped, `Replete with Fiber (Full)` and `Replete
      with Fiber (1/2)` — the same product, the same target — would land on
      opposite sides of the threshold in one ConceptMap. What N1 identifies is
      also what THE_RATE_FRACTION_RULE below suppresses.
  N2  pad a slash between two alphabetic tokens: `Piperacillin/Tazobactam` ->
      `Piperacillin / Tazobactam`, which is how RxNorm spells a multi-ingredient
      term. Validated by AGREEMENT rather than asserted: it moves
      `Piperacillin/Tazobactam (Zosyn)` (60,647 occ) and `Ampicillin/Sulbactam
      (Unasyn)` (8,065) from the service to the deterministic tier, landing on
      74169 and 1009148 — the same RxCUIs code-search returned unaided at 0.95.
      Digits are excluded on both sides so `D5 1/2NS`, `Insulin - 70/30` and
      `Amiodarone 450/250` are untouched.

  NOT ADOPTED — stripping the ICU context parentheticals `(Bolus)`, `(CRRT)`,
      `(Prophylaxis)`, `(Concentrate)`, `(Amp)`, `(Impella)`. The term index's
      own de-parenthesising rung already reaches the ingredient for all of them,
      and `KCL (Bolus)` answers correctly at 0.85 untouched. A rule with nothing
      to do is a rule that will one day do something.
  NOT ADOPTED — any not-a-drug suppression list. With SNOMED_ECL fixed the
      route, container and intake-category population declines on its own: ten
      of the fifteen probed non-drug labels decline on all three rungs unaided
      and the constraint rejects the rest, so `Solution`, `PO Intake`, `Gastric
      Meds` and `Piggyback` need no rule. A hand-kept list of ICU labels that
      "are not really medications" is exactly the per-item judgement the
      generated-table contract exists to remove.

THE_RATE_FRACTION_RULE. After the term join, a code whose label carried a rate
fraction is declared unmapped WITHOUT calling the service. This was NOT in the
first version of this generator, and the first full run is why it is here.

The proposal argued the enteral slice needed no rule because the constraint
would decline it. Over 77 codes the constraint mostly did — and the four rows it
let through were the worst in the table:

    228351 Nepro (Full)   ->  421915002 |Rotigotine|            0.80   16,694 occ
    228348 Nepro (1/2)    ->  421915002 |Rotigotine|            0.80       12 occ
    225937 Ensure (Full)  ->  373453009 |Nutritional supplement| 0.80     728 occ
    226875 Ensure (3/4)   ->  373453009 |Nutritional supplement| 0.80       1 occ

Nepro is a renal tube feed and rotigotine is a Parkinson's dopamine agonist.
The probe round had already seen this collision on the RxNorm side — `Nepro` ->
`707892 Neupro` at 0.65, correctly declined — and it came back through the
SNOMED rung above the gate. No threshold reaches it, and no ECL excludes it:
rotigotine genuinely IS a drug, so the constraint is working and the MATCH is
wrong. The other two are the class collapse the ECL was meant to remove, which
it does not, because `373453009 |Nutritional supplement|` sits inside
`<<410942007 |Drug or medicament|`.

So the slice is suppressed, and the rule is structural rather than a list: it
fires on the rate-fraction PATTERN, which is a fact about how an ICU chart
records a tube-feed rate, not a judgement about any product. What makes it
honest is that the premise is measured rather than assumed — an $expand over
ALL of RxNorm 20231106 with no TTY filter returns no concept for Beneprotein,
Osmolite, Peptamen, Isosource, Novasource, Fibersource, Optisource, Two Cal or
Mighty Shake, and every apparent hit for the rest is an edit-distance accident
(`Jevity 1.5` retrieves `JEVTANA 60 MG in 1.5 ML Injection`). It costs 729
occurrences of `Nutritional supplement`, a code that distinguishes nothing, and
removes 16,706 occurrences of a Parkinson's drug.

ORDERING IS LOAD-BEARING, exactly as in build_formulary_drug_table: the rule
fires AFTER the term join, so a formula name that IS an RxNorm term would still
be settled deterministically rather than suppressed. None is today; the ordering
is what keeps that true if one ever is.

The rule does NOT reach two errors that survive in this table — see KNOWN
DEFECTS. Neither is reachable by a rule this repo could state without writing a
per-item judgement, so both are documented instead of fixed.

WHAT THE JOIN REACHES, measured offline against the committed index: 151 of the
324 codes and 3,601,951 occurrences (40.1%) never reach the service — 100 by
exact match, 49 after dropping a trailing parenthetical (`Hydromorphone
(Dilaudid)` -> hydromorphone), 2 after salt canonicalisation. That last rung is
load-bearing here: `K Phos` reaches `34322 potassium phosphate` deterministically
and so never reaches code-search, which answers it with the BN `K-Phos` at 0.95
— an ORAL urinary acidifier, and the one prefix collision found anywhere in this
population.

THE GATE, per target system, applied as a filter rather than an assertion:
  RxNorm  membership of CONSTRAINT_VCL, proved with $validate-code.
  SNOMED  membership of SNOMED_ECL, proved with $validate-code — see above —
          AND exists, active, international core module rather than a national
          extension.
Target displays are then replaced with the server's preferred term, so
verify-curated's display check passes by construction.

KNOWN DEFECTS, stated here because the generator does not hand-write targets and
the fixes available are all changes to the METHOD rather than to a row:

  228340 `Furosemide (Lasix) 250/50` -> 428540 furosemide 250 MG Oral Tablet.
    An IV infusion bag coded as an oral tablet; correct injectable SCDs exist
    inside the same constraint. 18,713 occurrences.
  225161 `NaCl 3% (Hypertonic Saline)` -> 724590 sodium chloride 3 % Inhalation
    Solution. Route error, same shape. 8,504 occurrences.
  225825 `D5NS` and 228140 `Dextrose 20%` acquire a pack size (`in 1000 ML`,
    `in 500 ML`) the label never stated. 6,420 occurrences.
  225170 `Platelets` -> 256398006 |Platelets - irradiated| at 0.95. Irradiation
    is a real and clinically significant property of a platelet unit, and the
    MIMIC label does not state it. 10,857 occurrences.
  226365 `OR Colloid Intake` -> 421880 |silicon dioxide, colloidal| at 0.85. A
    word collision: `Colloid` here names a class of volume expander, not the
    excipient. 2,039 occurrences.

  The last two are above any threshold this stream could use and are not
  reachable by a stated rule — the fixes available are a per-item reject list,
  which would be a way to hand-write mappings around the gate, or nothing. A
  consumer should drop both rows, and should treat a dose form on any target
  from this stream as unasserted by the source unless the MIMIC label states
  one.

NOT PART OF `make mappings`: it needs the network and a model-backed service,
and it WRITES a build input. Determinism lives in the split — this runs by hand,
its output is committed, and the build reads the committed CSV and never a
server.

Usage:
  uv run .../build_medication_icu_table.py --insecure
  uv run .../build_medication_icu_table.py --append --insecure
  uv run .../build_medication_icu_table.py --only 225158,225943 --insecure
"""

import argparse
import concurrent.futures
import csv
# NOT `import http.client`: the fhirclient import below binds the name `http` to
# a function, so `HTTPException` in find_code's except clause would raise
# AttributeError instead of retrying — silently defeating the retry loop on
# exactly the transport failures it exists to absorb.
from http.client import HTTPException
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common import fhirclient                                     # noqa: E402
from common.cli import add_common_args, DEFAULT_CODE_SEARCH       # noqa: E402
from common.fhirclient import configure_tls, http                 # noqa: E402
from common import paths                                          # noqa: E402
from conceptmaps.lib.builders import (describe_population,        # noqa: E402
                                      table_population)
from conceptmaps.lib.canonical import RXNORM, SNOMED, TABLE_DIR    # noqa: E402
from conceptmaps.lib.termindex import (load_index, query_rungs,    # noqa: E402
                                       r3)

OUT_CSV = TABLE_DIR / "medication-icu-standard.csv"
LOG_JSON = paths.OUTPUT / "medication-icu-generation-log.json"

# The RxNorm release the index and the table were built from. Asserted on every
# run against what the server echoes back: a silent release bump would change
# committed answers with no diff to explain them.
RXNORM_VERSION = "20231106"

# Character-identical to build_medication_name_table.CONSTRAINT_VCL and to
# build_formulary_drug_table's, which is what lets this generator join against
# the committed term index. load_index asserts it rather than trusting this
# comment.
CONSTRAINT_VCL = (f"({RXNORM})"
                  "(TTY=IN;TTY=PIN;TTY=MIN;TTY=BN;TTY=SCD;TTY=GPCK;TTY=BPCK)")

# Rung 2: ingredient term types only, for when the service gives up because the
# FORM it was asked for is unreachable while the ingredient was in scope.
INGREDIENT_VCL = f"({RXNORM})(TTY=IN;TTY=PIN;TTY=MIN)"

# Rung 3, and the setting that carries this stream's accuracy. A POSITIVE
# enumeration of what a non-RxNorm answer may be, NOT `<<105590001 |Substance|`
# minus its accidents — see the module docstring for the three subtraction
# candidates that were measured and rejected. 68,786 concepts.
#
#   <<410942007 |Drug or medicament|      the drug substances and the class
#                                         concepts (TPN agent, Multivitamin
#                                         agent) RxNorm does not model
#   <<763158003 |Medicinal product|       product-level answers, e.g. `Glucose
#                                         only product in parenteral dose form`
#   <<256906008 |Blood material|          packed red cells, platelets,
#                                         cryoprecipitate, salvaged blood
#   <<410652009 |Blood product|           fresh frozen plasma, which sits in the
#                                         product branch and which the old
#                                         substance ECL excluded
SNOMED_ECL = ("<<410942007 OR <<763158003 OR <<256906008 OR <<410652009")

# 0.80, adjudicated row by row over this stream's own band — see THRESHOLD.
CONFIDENCE_THRESHOLD = 0.80

# No template. Tested here with three independent wrappers and rejected; see
# TEMPLATE in the module docstring.
TEMPLATE = "{}"

# SNOMED CT international core. A national extension resolves on the server it
# was authored against and nowhere else, which is invisible from reading a CSV.
INTERNATIONAL_CORE = "900000000000207008"

CURATED_HEADER = [
    "mimic_code", "mimic_display",
    "target_system", "target_code", "target_display", "comment",
    # Provenance: read by lib/stats.py and discarded by the build. Recorded on
    # every row INCLUDING the ones where the proposal was then rejected, so any
    # mapping and any non-mapping can be audited from the CSV alone. `query` and
    # `normalisation` are carried for the same reason build_formulary_drug_table
    # carries them: with a normalisation layer in play, the string actually sent
    # is not recoverable from mimic_display by eye.
    "method", "join_rung", "query", "normalisation",
    "codesearch_target", "codesearch_display", "codesearch_confidence",
    "codesearch_status", "codesearch_reasoning",
]


# --------------------------------------------------------------------------- #
# Normalisation. QUERY-SIDE ONLY — see NORMALISATION in the module docstring.
# --------------------------------------------------------------------------- #

# N1. The rate fraction an ICU chart records alongside a tube feed: how much of
# the prescribed rate was running, not part of the product name. Anchored to the
# END of the label so a fraction inside a product name could not be eaten.
_RATE_FRACTION = re.compile(r"\s*\(\s*(?:full|1/4|1/2|2/3|3/4)\s*\)\s*$",
                            re.IGNORECASE)

# N2. A slash joining two ALPHABETIC tokens, which is how MIMIC writes a
# multi-ingredient product and how RxNorm does not. Both sides must be at least
# three letters and neither may contain a digit, so `D5 1/2NS`, `Insulin - 70/30`
# and `Amiodarone 450/250` are left exactly as they are.
_ALPHA_SLASH = re.compile(r"(?<=[A-Za-z]{3})/(?=[A-Za-z]{3})")

# ... and only OUTSIDE a parenthetical. A slash inside one is not joining two
# ingredients: `Mighty Shake (Vanilla/Strawberry)` lists flavours and `Bactrim
# (SMX/TMP)` an abbreviation pair. Neither is a term RxNorm spells with spaces,
# and a rule that fires where its argument does not hold is a rule that will one
# day matter.
_PARENTHETICAL = re.compile(r"\([^()]*\)")

# Edge punctuation, stripped from the finished query with the SAME characters
# lib/termindex.r3 strips from an index key. Not cosmetic: `225970 Beneprotein`
# and `229583 Beneprotein.` are one product, neither reaches the index, and
# without this they are two distinct queries that the fan-out cannot merge — so
# one ConceptMap could carry two different targets for them. The ICU dictionary
# has three of these (`Beneprotein.`, `Epinephrine.`, `Sodium Acetate.`).
_EDGE = " \t\r\n.,;:*#\"'`-/\\+"


def _pad_slashes(text):
    """N2, applied only to the parts of `text` outside any parenthetical."""
    out, last = [], 0
    for match in _PARENTHETICAL.finditer(text):
        out.append(_ALPHA_SLASH.sub(" / ", text[last:match.start()]))
        out.append(match.group(0))
        last = match.end()
    out.append(_ALPHA_SLASH.sub(" / ", text[last:]))
    return "".join(out)


def normalise(display):
    """The string actually sent to the index and the service.

    Returns (query, [rule names applied]) so the CSV can record which rules
    touched a row and a reader can reproduce the query by hand.
    """
    applied = []
    text = display
    if _RATE_FRACTION.search(text):
        text, applied = _RATE_FRACTION.sub(" ", text), applied + ["N1-rate"]
    padded = _pad_slashes(text)
    if padded != text:
        text, applied = padded, applied + ["N2-slash"]
    return " ".join(text.split()).strip(_EDGE).strip(), applied


# --------------------------------------------------------------------------- #
# code-search, the gate, and the constraint URLs.
# --------------------------------------------------------------------------- #

def constraint_url(vcl=None):
    """A VCL expression as a resolvable implicit-ValueSet canonical."""
    return ("http://fhir.org/VCL?v1="
            + urllib.parse.quote(vcl or CONSTRAINT_VCL, safe=""))


def snomed_url(ecl=None):
    """A SNOMED ECL as its implicit-ValueSet canonical.

    NOT the VCL form. SNOMED CT has its own implicit ValueSet syntax and that is
    what the server and code-search resolve; a VCL wrapper round an ECL string
    404s.
    """
    return (f"{SNOMED}?fhir_vs=ecl/"
            + urllib.parse.quote(ecl or SNOMED_ECL, safe=""))


def rungs():
    """The rungs resolve() tries, in order: (constraint URL, target system)."""
    return ((constraint_url(CONSTRAINT_VCL), RXNORM),
            (constraint_url(INGREDIENT_VCL), RXNORM),
            (snomed_url(), SNOMED))


def get(fhir_base, path, **params):
    """A GET returning the parsed body, or None. Non-200 is not an answer."""
    query = urllib.parse.urlencode(params)
    status, body = http("GET", f"{fhir_base.rstrip('/')}/{path}?{query}")
    return body if status == 200 and body else None


def find_code(service, text, url, system, timeout, attempts=4):
    """code-search's best match for `text`, constrained to `url`.

    Retries transport failures: a dropped connection is not an answer, and a run
    that quietly mixes 'no match' with 'the service was not running' produces a
    table that understates coverage and reads exactly like a real result.
    Exhausted retries raise, and main() refuses to write the CSV.

    A 4xx IS NOT RETRIED: the service rejecting a request is a permanent answer
    about that request, not a transport fault — but urllib raises HTTPError, a
    SUBCLASS of URLError, so a bare transport clause would swallow it and retry
    a guaranteed-identical failure. Re-raised immediately instead.
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
        except urllib.error.HTTPError as exc:
            if 400 <= exc.code < 500:
                raise RuntimeError(
                    f"code-search rejected the request with HTTP {exc.code} "
                    f"({exc.reason}) for text={text!r}. That is a permanent "
                    f"answer about this request, not a transport fault, so it "
                    f"is not retried.") from exc
            last = exc
            if attempt < attempts - 1:
                time.sleep(2 ** attempt)
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


def in_constraint(fhir_base, code, url, system):
    """True if `code` is a member of `url`, per the server. Asserted, not assumed.

    Used for BOTH target systems here. The sibling generators call it only for
    the RxNorm rungs and let the SNOMED rung through on a $lookup alone, which
    is how 24 out-of-constraint SNOMED targets reached their committed tables —
    see THE SNOMED GATE in the module docstring.
    """
    result = get(fhir_base, "ValueSet/$validate-code",
                 url=url, system=system, code=code)
    if result is None:
        return False
    return any(p.get("name") == "result" and p.get("valueBoolean")
               for p in result.get("parameter", []))


def snomed_gate(fhir_base, code, url):
    """(ok, preferred_display) for a SNOMED target.

    Four checks, and the first is the one the sibling generators are missing:
    the concept is inside the ECL code-search was told to search, it exists, it
    is active, and it is in the international core module rather than a national
    extension. The last is the one a reader of the CSV cannot make — an AU- or
    US-extension concept resolves on the server it was picked from and nowhere
    else.
    """
    if not in_constraint(fhir_base, code, url, SNOMED):
        return False, ""
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


def assert_rxnorm_version(fhir_base):
    """Fail closed if the server is serving a different RxNorm release.

    The term index carries its release in its manifest; the SERVICE does not, so
    this asks the server directly before any answer is accepted. Mixing releases
    would change committed answers with no diff to explain them.
    """
    body = get(fhir_base, "CodeSystem/$lookup", system=RXNORM, code="161",
               property="version")
    served = ""
    for parameter in (body or {}).get("parameter", []):
        if parameter.get("name") == "version":
            served = parameter.get("valueString", "")
    if served and served != RXNORM_VERSION:
        sys.exit(f"  server is serving {RXNORM}|{served}, this table is built "
                 f"against |{RXNORM_VERSION}. Refusing to mix releases.")


# --------------------------------------------------------------------------- #
# Resolving one distinct query.
# --------------------------------------------------------------------------- #

def resolve(query, index, fhir_base, service, timeout):
    """Resolve ONE normalised label. Returns the target/provenance fields only.

    Keyed on the query rather than on a code, because a label shared by several
    ICU itemids is asked once and the answer fanned across its members — see
    SHARED-LABEL FAN-OUT in main().
    """
    out = {c: "" for c in CURATED_HEADER}

    for rung, key in query_rungs(query):
        if (rxcui := index.get(key)):
            out.update(method="term-join", join_rung=rung,
                       target_system=RXNORM, target_code=rxcui,
                       target_display=rxnorm_display(fhir_base, rxcui) or query,
                       codesearch_status="not-needed")
            return out

    # Fail-safe, not a population rule. No ICU display normalises to nothing
    # today, but sending "" to code-search is an HTTP 400 — a permanent
    # rejection — and in the formulary stream that killed a run which had
    # already paid for 1,954 good answers. Tested on r3() so a query that is
    # only punctuation is caught by the same guard.
    if not r3(query):
        out.update(method="no-label", codesearch_status="no-label")
        return out

    out["method"] = "code-search"
    for url, system in rungs():
        answer = best(find_code(service, query, url, system, timeout))
        if answer is None:
            continue
        target, proposed, confidence, reasoning = answer
        out.update(codesearch_target=target, codesearch_display=proposed,
                   codesearch_confidence=f"{confidence:.2f}",
                   codesearch_reasoning=reasoning)
        if confidence < CONFIDENCE_THRESHOLD:
            out["codesearch_status"] = "below-threshold"
            continue
        if system == SNOMED:
            ok, preferred = snomed_gate(fhir_base, target, url)
            if not ok:
                out["codesearch_status"] = "gate-failed"
                continue
        else:
            if not in_constraint(fhir_base, target, url, system):
                out["codesearch_status"] = "out-of-constraint"
                continue
            preferred = rxnorm_display(fhir_base, target) or proposed
        out.update(codesearch_status="ok", target_system=system,
                   target_code=target, target_display=preferred)
        return out

    out["codesearch_status"] = out["codesearch_status"] or "no-match"
    return out


def declined_comment(row):
    """Why a blank target is a DECISION. A blank one with no reason is fatal in
    lib/curated.py, and rightly: a reader cannot audit silence."""
    if row["codesearch_status"] == "not-searchable":
        return ("Not sent to code-search: the label carries an ICU rate "
                "fraction, so it records how much of a prescribed tube feed was "
                "running. RxNorm holds no concept for any of these branded "
                "enteral formulas at any term type — measured by expanding the "
                "whole code system with no term-type filter, not assumed — and "
                "SNOMED CT answers them only with a nutritional-supplement "
                "class code or with a lexical collision on the brand name.")
    if row["codesearch_status"] == "no-label":
        return ("source display carries no searchable label, so no search was "
                "made.")
    proposal = (f"{row['codesearch_target']} "
                f"'{row['codesearch_display']}' at "
                f"{row['codesearch_confidence']}")
    return {
        "no-match": (f"code-search returned no match within {CONSTRAINT_VCL}, "
                     f"its ingredient-only subset, or SNOMED CT "
                     f"{SNOMED_ECL}."),
        "below-threshold": (f"code-search proposed {proposal}, below the "
                            f"{CONFIDENCE_THRESHOLD} threshold."),
        "out-of-constraint": (f"code-search proposed {proposal} but that code "
                              f"is not a member of the search constraint."),
        "gate-failed": (f"code-search proposed {proposal} but that concept is "
                        f"outside the SNOMED CT search constraint, inactive, or "
                        f"outside the international core module."),
    }.get(row["codesearch_status"], f"code-search: {row['codesearch_status']}.")


# --------------------------------------------------------------------------- #

def ig_codes():
    """The observed source codes for EVERY field that reads this table.

    `mimic-medication-icu` is bound to one element today, so this is one field's
    population — but it is discovered rather than declared, so binding the
    CodeSystem to a second element extends the generation population with
    nothing to keep in step. See lib/builders.py.
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

    The generation log records the constraint, template and threshold ONCE, at
    top level, and lib/stats.py reads them as the settings that produced every
    row. Appending to a table whose committed rows predate a settings change
    would make that a lie. Fail closed instead: a full regeneration is the
    correct response to moving a setting.
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
    # The suppression rule decides whether a code was ASKED at all, so a table
    # generated before it and appended to after it would carry two populations
    # under one stated method. Checked with the other settings rather than
    # trusted to be remembered.
    rules = set((log.get("normalisation") or {}))
    if rules != {"N1-rate", "N2-slash", "rate_fraction_rule"}:
        drifted["normalisation rules"] = (sorted(rules),
                                          ["N1-rate", "N2-slash",
                                           "rate_fraction_rule"])
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
    for method, n in Counter(r["method"] for r in rows).most_common():
        print(f"    {method or '(none)':16s} {n:>6,}", file=sys.stderr)
    print("\n  normalisation applied", file=sys.stderr)
    for rule, n in Counter(r["normalisation"] for r in rows
                           if r.get("normalisation")).most_common():
        print(f"    {rule:16s} {n:>6,}", file=sys.stderr)
    print("\n  join rung", file=sys.stderr)
    for rung, n in Counter(r["join_rung"] for r in rows
                           if r["join_rung"]).most_common():
        print(f"    {rung:16s} {n:>6,}", file=sys.stderr)
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
    ap.add_argument("--workers", type=int, default=8,
                    help="concurrent code-search calls (default: %(default)s)")
    ap.add_argument("--timeout", type=int, default=180)
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
    assert_rxnorm_version(fhir_base)

    # The index is the drug-name generator's file. Passing the constraint makes
    # "this reader searches what that index describes" an assertion rather than
    # a comment — see lib/termindex.load_index.
    index, manifest = load_index(CONSTRAINT_VCL)
    print(f"  term index: {len(index):,} keys, {manifest['system']}|"
          f"{manifest['version']}", file=sys.stderr)

    concepts = ig_codes()
    for element, count in describe_population(OUT_CSV):
        print(f"  {element:42s} {count:>6,} observed", file=sys.stderr)

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

    # SHARED-LABEL FAN-OUT. Normalise once, then group by the query actually
    # sent, so every code sharing a query shares its answer by construction. On
    # this stream that is a correctness guarantee before it is a saving: N1
    # collapses the 77 rate-fraction variants onto 25 products, and without the
    # fan-out `Replete with Fiber (Full)` and `Replete with Fiber (1/2)` could
    # receive different targets for the same tube feed.
    normalised = {code: normalise(display)
                  for code, display in concepts.items()}

    # THE_RATE_FRACTION_RULE, applied HERE so it really does mean "without
    # calling the service", and ordered AFTER the term-join test so a formula
    # name the index can answer is still settled deterministically. Keyed on N1
    # having fired rather than on re-matching the pattern, so the suppression
    # and the normalisation can never disagree about which rows they describe.
    joins = {query: any(key in index for _, key in query_rungs(query))
             for query, _ in normalised.values()}
    suppressed = {code for code, (query, applied) in normalised.items()
                  if not joins[query] and "N1-rate" in applied}

    members = defaultdict(list)
    for code, (query, _) in normalised.items():
        if code not in suppressed:
            members[query].append(code)

    joinable = sum(1 for q in members if joins[q])
    print(f"  {len(concepts):,} code(s) -> {len(members):,} distinct query(s) "
          f"after normalisation, fan-out and suppression", file=sys.stderr)
    print(f"    {joinable:,} answered by the committed term index, "
          f"{len(members) - joinable:,} go to code-search; "
          f"{len(suppressed):,} code(s) carry an ICU rate fraction and are "
          f"declined without a call", file=sys.stderr)

    rows, failed = [], []
    with concurrent.futures.ThreadPoolExecutor(args.workers) as pool:
        futures = {pool.submit(resolve, query, index, fhir_base,
                               args.code_search, args.timeout): query
                   for query in members}
        answers = {}
        for done, future in enumerate(
                concurrent.futures.as_completed(futures), 1):
            query = futures[future]
            try:
                answers[query] = future.result()
            except Exception as exc:                             # noqa: BLE001
                failed.append((query, exc))
            print(f"    {done:,}/{len(futures):,}", end="\r", file=sys.stderr)

    if failed:
        # Refusing to write is the point: a table missing the rows whose calls
        # died is indistinguishable from one where the service said no.
        for query, exc in failed[:5]:
            print(f"    {query!r}: {exc}", file=sys.stderr)
        sys.exit(f"\n  {len(failed)} of {len(members)} call(s) failed. "
                 f"Refusing to write a table that would understate coverage.")

    for code, display in concepts.items():
        query, applied = normalised[code]
        # A suppressed code never joined a group, so there is no answer to copy
        # and no call was made for it. The codesearch_* columns stay blank,
        # which is what distinguishes "asked and declined" from "never asked".
        row = ({c: "" for c in CURATED_HEADER}
               | {"method": "rate-fraction",
                  "codesearch_status": "not-searchable"}
               if code in suppressed else dict(answers[query]))
        row.update(mimic_code=code, mimic_display=display, query=query,
                   normalisation="+".join(applied))
        rows.append(row)

    for row in rows:
        if not row["target_code"]:
            row["comment"] = declined_comment(row)
    # Committed rows first so a generated row can never silently replace one;
    # `concepts` was already narrowed to the codes that had none.
    rows = list(carried.values()) + rows
    rows.sort(key=lambda r: r["mimic_code"])

    with open(OUT_CSV, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=CURATED_HEADER, restval="",
                                extrasaction="ignore")
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
        "snomed_fallback_url": snomed_url(),
        "template": TEMPLATE,
        "confidence_threshold": CONFIDENCE_THRESHOLD,
        "rxnorm_version": RXNORM_VERSION,
        "normalisation": {
            "N1-rate": ("strip a trailing ICU rate-fraction suffix — (Full), "
                        "(3/4), (2/3), (1/2), (1/4)"),
            "N2-slash": ("pad a slash joining two alphabetic tokens, as RxNorm "
                         "spells a multi-ingredient term"),
            "rate_fraction_rule": ("after the term join, a code whose label "
                                   "carried an ICU rate fraction is declared "
                                   "unmapped without calling the service"),
        },
        "snomed_gate": ("$validate-code against snomed_fallback_ecl, then "
                        "active and international core module"),
        "term_index": {k: manifest[k] for k in
                       ("codes", "terms", "keys", "ambiguous_keys_dropped",
                        "tsv_sha256")},
        "rows": rows,
    }, indent=1) + "\n")
    print(f"  wrote {LOG_JSON.name}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
