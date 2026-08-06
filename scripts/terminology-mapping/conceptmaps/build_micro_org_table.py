#!/usr/bin/env python3
"""Generate conceptmaps/micro-org-snomed.csv — the 646 microbiology organism names -> SNOMED CT.

The fifth generated table, the second in the Observation.code map to target
SNOMED CT, and the FIRST in this repo to send the label with no wrapper at all.
That last one is the whole design story: every stream before this took flowsheet
column headings or bare drug names, which say what a clinician means only in the
context of the table they came from, and each needed a TEMPLATE to supply that
context. These labels are already clinical terms, and probing showed every
wrapper tried made the answers worse.

WHAT THE SOURCE CODES MEAN. mimic-microbiology-organism holds 646 organism names
from MIMIC's `microbiologyevents.org_name`, bound to Observation.code on
MimicObservationMicroOrg, whose `value[x]` is a plain **string**. So the code
itself names the organism that was identified, and the target is a SNOMED
organism taxon rather than an observable or a laboratory test.

Consumers must take that literally: this stream puts SNOMED **organisms** into
the Observation.code target ValueSet, so `<<363787002 |Observable entity|` is not
a safe assumption about a target of this map. It is the same caveat the README
already records for the ICU procedure population ("a SNOMED target is not
necessarily a procedure"), arriving from the other direction, and it follows
from the IG's own modelling rather than from anything chosen here.

THE POPULATION IS UNUSUALLY CLEAN, which is why the expectations differ from
every stream before it. Counted over the IG's own displays:

    plain binomial / plain taxon                    430
    '... SPECIES' / 'SP.' / 'SPP.'                   98
    parenthetical synonym                            31
    'POSITIVE FOR ...' (antigen / viral detection)   20
    gram-stain morphology group                      17
    slash-joined taxa                                15
    negation ('... NOT ...')                         14
    'PRESUMPTIVE ...'                                 8
    comma qualifier                                   6
    quantity prefix (FEW / MODERATE / MANY / RARE)    4
    non-organism result                               3

528 of the 646 are already exact taxonomic names. The honest prior here is
therefore ABOVE the 64% the ICU `procedureevents` population scored and well
above the ~40% the datetimeevents items managed, not because the method got
better but because the source labels are.

CONSTRAINT_ECL. `<<410607006 |Organism|`, 34,660 concepts. Unconstrained, three
of seven adversarial labels come back confidently wrong, every one of them
outside the organism hierarchy:

    POSITIVE FOR CYTOMEGALOVIRUS       0.90 445459004 |Cytomegalovirus
                                            serostatus positive| -- a FINDING
    POSITIVE FOR CRYPTOCOCCAL ANTIGEN  0.80 103094002 |Cryptococcal antigen|
                                            -- a SUBSTANCE
    POSITIVE FOR METHICILLIN RESISTANT 0.95 440608005 |Culture positive for
    STAPH AUREUS                            MRSA| -- a FINDING

Under `<<410607006` the same three answer 407444007 |Cytomegalovirus species|,
17579001 |Cryptococcus species| and 115329001 |Methicillin resistant
Staphylococcus aureus|. The wrong answers score HIGHER (0.90, 0.95) than several
of the correct constrained ones (0.85), which is the `Foley Catheter` lesson
repeating: confidence does not separate a good answer from an unusable one, only
the constraint does. The constraint costs nothing on any control row --
`CANDIDA ALBICANS`, `STAPHYLOCOCCUS, COAGULASE NEGATIVE` and `HAEMOPHILUS
INFLUENZAE, BETA-LACTAMASE POSITIVE` are unchanged, the last two because they
are themselves organism concepts and were never at risk.

It also IMPROVES RECALL, which is the opposite of the usual trade and worth
recording: `PINWORM EGG(S) SEEN` is NO MATCH unconstrained and resolves to
609080003 |Egg of Enterobius vermicularis| at 0.85 under the constraint.

The morphology worry was unfounded. SNOMED files the gram-stain groups inside
the organism hierarchy, so no widening is needed to reach them:
`GRAM NEGATIVE ROD(S)` -> 87172008 |Gram-negative bacillus| (0.95),
`ANAEROBIC GRAM POSITIVE COCCUS(I)` -> 243416009 (0.95),
`GRAM POSITIVE BACTERIA` -> 8745002 (0.95).

WIDENING TO CLINICAL FINDING WAS TESTED AND REJECTED. The three non-organism
labels (`NO GROWTH`, `POSITIVE`, `NEGATIVE`) are NO MATCH under the organism
constraint, and the obvious repair -- `(<<410607006 OR <<404684003)` -- was
built and probed. It loses on both sides. It wins nothing: `POSITIVE` still
fails, `NEGATIVE` picks up 442225006 |Negative measurement finding| which is the
wrong slot entirely, and the one genuinely correct concept, 264868006
|No growth|, sits under 260245000 |Findings values| and is not in the union at
all. And it breaks three of six control rows, two of them at HIGHER confidence
than the organism answer they displaced: CMV regresses to the serostatus
finding (0.90), MRSA to 312210001 |MRSA detected| (0.95), and the cryptococcal
antigen row regresses to NO MATCH. So the three result labels are left unmapped
with a stated reason, which is what the constraint refusing to invent an
organism looks like.

NO TEMPLATE, AND THE EVIDENCE IS A ROW WHERE EVERY WRAPPER ASSERTS SOMETHING
FALSE. Three candidates were run over the same eleven discriminating labels,
against the bare label as a fourth:

    A  {}                                                        <- kept
    B  Microbiology result naming the organism identified: {}
    C  Organism identified in a microbiology test result: {}
    D  Microbiology culture isolate: {}

B, C and D all answer `BETA STREP NOT GROUP A OR ANGINOSUS (MILLERI)` with
415597009 |Streptococcus anginosus group| -- PRECISELY THE TAXON THE LABEL
EXCLUDES. Naming "the organism identified" appears to prime the searcher to take
the most salient taxon token and read the negation as noise, which produces a
mapping that states the opposite of the source. The bare label stays on the
exclusion side. That single row disqualifies all three.

Each also fails on its own:

  * B additionally scores `FEW BLASTOCYSTIS HOMINIS` at confidence **0.00**,
    reasoning "the search text is a microbiology result, not the organism
    itself" -- its wording sets up a category conflict with the organism
    constraint and the searcher refuses a match it makes at 0.90 bare.
  * C degrades `GRAM NEGATIVE ROD(S)` from 87172008 |Gram-negative bacillus| to
    the broader 81325006 |Gram-negative bacterium|: the rod/bacillus equivalence
    is lost once the label is buried mid-sentence.
  * D is rejected on the house rule rather than on its answers, which is worth
    stating because its answers were mostly fine. "Culture isolate" is false of a
    table that also carries antigen tests, viral detection, parasitology and
    arthropod identification. The searcher was more robust to the false frame
    than expected -- it ignored the culture framing on the non-culture rows --
    so the frame's damage showed up on negation, not on modality.

Bare also wins on confidence systematically, 1.00 against 0.85 on exact taxa,
which for a threshold-gated pipeline is the difference between a clean
auto-accept and a near-miss.

TEMPLATE is therefore the identity wrapper, `{}`. It is kept as a named constant
rather than deleted so that the generation log records the setting the same way
every other stream's does, and so that adopting a wrapper later is a one-line
change with the evidence above to argue against.

NO NORMALISATION RULES, DELIBERATELY. Four shapes looked like candidates for a
stated strip and none of them earns one:

  * Quantity (`FEW`, `MODERATE`, `MANY`, `RARE`, 4 rows) and `PRESUMPTIVE`
    (8 rows) prefixes cost 0.10-0.15 confidence and NEVER change the code:
    `FEW BLASTOCYSTIS HOMINIS` 0.90 against 1.00 bare, both 28923009;
    `PRESUMPTIVE CLOSTRIDIUM PERFRINGENS` 0.85 against 1.00, both 8331005.
    Nothing observed crosses the 0.8 threshold, so a strip would buy headroom
    and nothing else, while adding a rule that has to be right about where the
    prefix ends. If a prefixed row does come back below threshold, the committed
    `codesearch_confidence` column makes adding the strip an evidenced change
    instead of a precaution.
  * The `#N` isolate index is harmless here, unlike in the outputevents and
    datetimeevents populations where it forced a family collapse. `GRAM NEGATIVE
    ROD #1` through `#4` all answer 87172008 at 0.95, as does the bare `(S)`
    form, so the consistency that FAMILY_INDEX had to manufacture there comes
    for free here.
  * Parenthetical synonyms resolve to the current taxon by themselves:
    `KLEBSIELLA (RAOULTELLA) ORNITHINOLYTICA` -> 416832000 |Raoultella
    ornithinolytica| at 0.95.
  * NEGATIONS MUST NOT BE STRIPPED, and this is the one where a plausible
    tidying rule would do real damage. SNOMED carries genuine exclusion
    concepts and the bare label finds them: `YEAST, PRESUMPTIVELY NOT C.
    ALBICANS` -> 714313009 |Candida species not Candida albicans| at 0.90,
    `ASPERGILLUS SP. NOT FUMIGATUS, FLAVUS OR NIGER` -> 719038009 at 0.95.
    Stripping the negation would manufacture exactly the false mapping the
    template comparison above rejected three candidates for.

SLASH-JOINED TAXA TAKE THE TOP ANSWER, like every other row. `STREPTOCOCCUS
MITIS/ORALIS` is a genuine tie -- 57997003 |Streptococcus mitis| and 19870004
|Streptococcus oralis| both at 0.85, with the service itself reasoning "two
organisms, no combined code exists" -- and 15 rows have this shape. Emitting
both would be the honest FHIR encoding, since ConceptMap.element.target is 0..*
and lib/project.py and verify_mappings already handle several targets per
element. It is not done here for three reasons, none of them about this stream:
lib/curated.py makes a duplicate mimic_code FATAL and assemble.build_groups
reads one row per code, so it is a change to machinery shared by all four bound
fields; the repo's own consumer projects with `translate(...).first()`, which
would silently drop the second target and make WHICH one survives depend on
element ordering -- the arbitrary pick relocated to where nothing records it;
and "accept every candidate above threshold" is not the same rule as "accept a
tie", because the service also returns broader concepts as second candidates,
which would bolt a noise target onto many of the 528 clean rows. Multi-target
belongs with issue #21 (code-search returning multiple codes), as a lib-level
change across every field. Here the tie is visible in the committed
`codesearch_*` columns and the mapping is `relatedto`, which asserts neither
identity nor completeness.

WRONG_TAXON is the one reject list. It exists for the failure a hierarchy
constraint cannot catch — the concept is a real, active, international organism
inside the constraint, and it is wrong about WHICH organism — and it is
currently EMPTY. It shipped with one entry, written from a design probe, and the
population run answered that label with a different and better concept, so the
entry declined nothing. Both the entry and the check that would have caught it
are discussed at the constant; the short version is that a reject list has to be
validated twice, once against the server before the run and once against the
answers after it.

WHAT TO EXPECT. Higher coverage than any previous semantic stream, on the
strength of the population rather than the method. The floor is small and
structural: 3 non-organism results have no organism target by construction, and
the negated and slash-joined rows are where the remaining risk sits.

WHAT THE 0.8 GATE ACTUALLY DECLINED, AND WHY IT STAYS AT 0.8 ANYWAY. The first
full run mapped 622 of 646 (96.3%), median confidence 1.00, mean 0.966. The 24
gaps are 15 `below-threshold` and 9 `no-match`, and the below-threshold band is
NOT the usual near-miss population — it is dominated by MISSPELLINGS IN THE
SOURCE DATA, where the service found the obviously correct taxon and marked it
down for the spelling rather than doubting the identification. Nine rows, all at
exactly 0.65:

    90340 GEOTRICHIUM SPECIES           0.65  34324005  Geotrichum species
    90352 CLOSTRIDIUM CLOSTRIDIIFORME   0.65  53220001  Clostridium clostridioforme
    90450 MORAXELLA NONLIQUIFACIENS     0.65  46455003  Moraxella nonliquefaciens
    90639 BACTEROIDIES THETAIOTAOMICRON 0.65  34236001  Bacteroides thetaiotaomicron
    90749 STREPTOCOCCUS SALIVARUS       0.65  39888004  Streptococcus salivarius
    90761 MYCOBATERIUM HAEMOPHILUM      0.65  21996001  Mycobacterium haemophilum
    90779 ACHROMOBACTER  DENTRIFICANS   0.65  413414001 Achromobacter denitrificans
    90802 ALACALIGENES SPECIES          0.65  68571003  Alcaligenes species
    90859 RHODATORULA MUCILAGINOSA      0.65  86724009  Rhodotorula mucilaginosa

The service is inconsistent about this rather than uniformly strict: probing
`CORYNEBCATERIUM AMYCOLATUM`, an equally mangled label, returned 113611002
|Corynebacterium amycolatum| at 0.95.

So the arithmetic of lowering the gate is genuinely different here from every
earlier stream. Dropping to 0.6 would take all 15 and put the stream at
637/646 = 98.6%. Thirteen of the 15 are defensible — the nine above, plus
`80235 STREPTOCOCCUS ANGINOSUS (MILLERI) GROUP` -> 415597009 (the right answer,
oddly scored 0.62), `90768 TICK` -> 106831000 |Ixodides| at 0.79,
`90621 TICK NOT CONSISTENT WITH IXODES SPECIES` -> the same broader concept at
0.70, and `80240 PRESUMPTIVE FUSOBACTERIUM MORTIFERUM/VARIUM GROUP` -> one of its
two taxa at 0.70. That is the OPPOSITE finding from the datetimeevents table,
where reading the near-threshold band row by row found most of it clinically
wrong.

TWO ROWS ARE WHY IT STAYS AT 0.8, and they are the two the constraint could
never fence out, because the labels are not organisms at all:

    90855 POSITIVE   0.75  8745002  |Gram-positive bacteria|
    90856 NEGATIVE   0.70  81325006 |Gram-negative bacterium|

The searcher is reading the result word `POSITIVE` as `gram-POSITIVE`. Those are
not vague mappings, they are fabrications about which organism grew, and at 0.6
both would ship. Trading two false organism identifications for thirteen
spelling corrections is not a trade this table makes; the threshold is the only
thing standing between them, and unlike the typos there is no signal in the data
that separates them.

RE-DERIVE THIS FROM THE COMMITTED TABLE rather than trusting the paragraphs
above — every declined row keeps the proposal that was rejected, which is what
the `codesearch_*` columns are for:

    python3 -c "import csv; [print(r['codesearch_confidence'], r['mimic_code'], \\
      r['mimic_display'], '->', r['codesearch_target'], r['codesearch_display']) \\
      for r in csv.DictReader(open('micro-org-snomed.csv')) \\
      if r['codesearch_status'] == 'below-threshold']"

A PROBE AND A POPULATION RUN CAN DISAGREE, AND HERE THEY DID — but the cause was
a different SERVICE CONFIGURATION, not run-to-run noise, and the distinction is
worth keeping straight because only one of them is a reason to distrust a table.
Two rows answered differently: `90707` (see WRONG_TAXON) and
`90819 POSITIVE FOR CRYPTOCOCCAL ANTIGEN`, which probed at 0.85 -> 17579001
|Cryptococcus species| and came back NO MATCH. The design probes ran against
code-search `a202bfd` on model profile `default`
(google/gemini-2.5-flash); the run that produced this table was `dev` on profile
`custom1` (deepseek/deepseek-v4-flash-0731). Different model, different answers,
which is expected rather than alarming.

This is exactly what `codesearch_service` in the generation log is for: it pins
the configuration each table was produced under, so "the answers moved" can
always be separated from "the service moved". Check it before reading a diff as
a change of opinion. The corollary for tuning: evidence gathered by probing is
only evidence about the configuration it was gathered under, which is how
WRONG_TAXON came to ship an entry that declined nothing.

SAME-CONFIGURATION VARIANCE IS UNMEASURED. Nothing here establishes how much two
runs of the SAME profile would differ, and the log's `path` distribution says a
re-run would mostly not be served from cache — 450 `fast`, 192 `agentic`, only 4
`cached`. Measuring it is a re-run and a `git diff` of this CSV, which is one of
the things committing the table buys.

READ A `no-match` ACCORDINGLY: it means "the service declined it on that run
under that configuration", NOT "SNOMED has no such concept". The two are not the
same claim. `90724 POSITIVE FOR ADENOVIRUS` and `90584 ANAEROBIC GRAM POSITIVE
BACTERIA` are almost certainly of that kind — the latter is odd given
`ANAEROBIC GRAM POSITIVE COCCUS(I)` scores 0.95.

Why it is NOT part of `make mappings`. Same as every generator here: it needs
the network and a model-backed service, and it is the one stage whose output is
not a pure function of this repo. Determinism lives in the split -- this runs
occasionally and by hand, its output is committed, and `make mappings` reads the
committed CSV and never a server, so `make mappings && git diff --exit-code`
stays a valid test.

    make micro-org-table ARGS=--insecure

Equivalence is not this script's concern. Every mapping a table supplies is
`relatedto`, set by lib/assemble.py when it builds the group; see lib/curated.py
for why a per-row equivalence column went away.

Output columns. The five in CURATED_COLUMNS are what the builder reads;
everything after them is provenance, ignored by the build and present so a
reader can audit any row -- what the service proposed, at what confidence, and
on what reasoning -- without re-running this script.
"""

import argparse
import concurrent.futures
import csv
# NOT `import http.client`: the fhirclient import below binds the name `http` to a
# function, so `HTTPException` in find_code's except clause raises
# AttributeError instead of retrying — which silently defeats the retry loop the
# docstring relies on, and only on the transport failures it exists to absorb.
from http.client import HTTPException
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.cli import add_common_args, DEFAULT_CODE_SEARCH  # noqa: E402
from common.fhirclient import configure_tls, http  # noqa: E402
# The module, not `from ... import SSL_CONTEXT`: configure_tls() REBINDS that global,
# so a name bound at import time would still be the pre-configuration context and
# --ca-bundle would be silently ignored.
from common import fhirclient  # noqa: E402
from conceptmaps.lib.canonical import SNOMED  # noqa: E402
from conceptmaps.lib.curated import CURATED_COLUMNS  # noqa: E402
from conceptmaps.lib.igsource import source_concepts  # noqa: E402
from verify.verify_curated_snomed import INTL_MODULE, lookup  # noqa: E402

# --------------------------------------------------------------------------- #
# The stated rules
# --------------------------------------------------------------------------- #

# The SNOMED organism hierarchy, and nothing else. See the module docstring for
# the three confidently-wrong unconstrained answers this rejects, for why
# widening to `(<<410607006 OR <<404684003)` was built, probed and dropped, and
# for the gram-stain morphology groups that turn out to live in here already.
CONSTRAINT_ECL = "<<410607006"

# The identity wrapper: this stream sends the label as it stands. The first
# generator here to do so, because it is the first whose labels are already
# clinical terms rather than column headings. Three wrappers were run against it
# over eleven discriminating labels and all three answered a NEGATED label with
# the taxon it excludes — see TEMPLATE in the module docstring.
#
# Kept as a named constant rather than removed so that the generation log records
# this setting exactly as every other stream's does, and so lib/stats.py reads it
# without a special case.
TEMPLATE = "{}"

# Below this, code-search's answer is discarded and the item is left unmapped.
# Matches the four generators before it. The accuracy rests on CONSTRAINT_ECL,
# not here: probing found the unconstrained WRONG answers scoring 0.90 and 0.95,
# above several correct constrained ones at 0.85, so this number cannot be the
# thing separating them. The distribution is printed at the end of every run so
# it can be moved with evidence rather than by taste.
#
# KEPT AT 0.8 AS A DECISION, NOT BY INHERITANCE, and this is the one stream where
# the evidence pointed the other way. Lowering it to 0.6 would take 15 more rows
# and reach 98.6%, and 13 of those 15 are defensible — 9 of them are the same
# phenomenon, a MISSPELLING in the source label scored down at 0.65 with the
# correct taxon already identified. It stays at 0.8 for two rows: `90855
# POSITIVE` and `90856 NEGATIVE`, which the searcher reads as gram-POSITIVE and
# gram-NEGATIVE and answers with an organism at 0.75 and 0.70. Those are
# fabrications about which organism grew, nothing in the data separates them from
# the thirteen good rows, and this gate is the only thing that declines them.
# See "WHAT THE 0.8 GATE ACTUALLY DECLINED" in the module docstring for the full
# list and for the one-liner that re-derives it from the committed table.
CONFIDENCE_THRESHOLD = 0.8

# A proposal declined because the concept is wrong about WHICH ORGANISM — the one
# failure neither the constraint nor the server gate can see. Every entry here
# names a concept that is a real, active, international-core member of
# `<<410607006`, so it passes every automated check; what is wrong is the pairing.
#
# Keyed on (mimic_code, snomed_code), the same shape COMMENT_OVERRIDES uses,
# because each entry is a judgement about one specific pairing rather than about
# either code alone. 406609007 is a perfectly good target for a label that
# actually excludes group B — `90708 BETA STREP NOT GROUP A, B OR ANGINOSUS
# (MILLERI)` is the obvious candidate — so rejecting the code outright would
# foreclose that.
#
# Note the boundary, which is the same one COMMENT_OVERRIDES observes: this list
# can only DECLINE a pair. It cannot pin a target. Ontoserver has no concept for
# "beta-haemolytic streptococcus, not group A and not anginosus" — the branch
# holds 53490009 |Beta-haemolytic Streptococcus|, 413643004 (group A),
# 441981000124105 (non-group B) and 406609007 — and writing 53490009 in by hand
# would make this table something other than "what the service returned, gated",
# which is the property that makes it reviewable. The row is left unmapped with
# the proposal recorded instead.
#
# EMPTY, and the story of why is the argument for checking a reject list twice.
#
# It shipped with one entry, ("90707", "406609007"). Design probing had
# `90707 BETA STREP NOT GROUP A OR ANGINOSUS (MILLERI)` answered with
# 406609007 |Beta-haemolytic streptococcus, non-Group A, non-Group B|, which
# over-asserts a non-group-B result the label never mentions. The full run
# answered the same label with 713922006 |Beta-hemolytic Streptococcus,
# non-Group A| at 0.90 instead — a target that under-specifies (it does not
# exclude the anginosus group) rather than asserting something false, which is
# the ordinary broader-than relationship `relatedto` already covers. The entry
# therefore declined nothing, and the premise it was written on was a single
# observation the population run did not reproduce.
#
# TWO LESSONS, both wired into the code rather than left here as prose:
#
#  1. A probe is not evidence that a pairing will recur, because probing and the
#     population run need not hit the same service configuration — and here they
#     did not: the probes ran on model profile `default` (gemini-2.5-flash), the
#     run on `custom1` (deepseek-v4-flash). The log's `codesearch_service` block
#     is what lets that be checked rather than guessed. See the module docstring.
#  2. validate_wrong_taxon() runs BEFORE any search and cannot catch this: it
#     checks that the concept is real and the itemid is live, both of which were
#     true. Whether a pair actually fires is only knowable afterwards, so
#     assert_wrong_taxon_fired() checks it after the run and is FATAL, the same
#     way apply_comments() is fatal on a comment that matches no row. An entry
#     that declines nothing is a judgement that has quietly evaporated.
#
# The pair-keying earned its keep even so: 406609007 is the CORRECT target for
# `90708 BETA STREP NOT GROUP A, B OR ANGINOSUS (MILLERI)`, which the run mapped
# to it at 0.80. Rejecting the code outright would have taken that row down too.
#
# Add an entry only from what the generated table actually shows, never from a
# probe, and give it the (mimic_code, snomed_code) key so it cannot outlive the
# pairing it was written about. Displays are the server's preferred terms and
# both halves are checked at startup by validate_wrong_taxon(): a mistyped SCTID
# or a stale itemid declines nothing, and does so silently.
WRONG_TAXON = {}

# --------------------------------------------------------------------------- #
# Paths and provenance
# --------------------------------------------------------------------------- #

TERM = Path(__file__).resolve().parents[1]
OUT_CSV = Path(__file__).resolve().parent / "micro-org-snomed.csv"
LOG_JSON = TERM / "output" / "micro-org-generation-log.json"

# What the service proposed on every row, including rows where the proposal was
# then rejected by the threshold, by the gate or by WRONG_TAXON — so that "this
# item is unmapped" is auditable in the committed diff rather than only in a run
# that has since scrolled away.
#
# No `codesearch_query` column, unlike the datetimeevents table: with the
# identity TEMPLATE and no family collapse, the string sent to the service is
# `mimic_display` exactly, so a column holding it would carry no information.
#
# `codesearch_status` and `codesearch_confidence` are the two columns
# lib/stats.py reads for the per-stream statistics, so the vocabulary stays the
# one the other tables use — plus `wrong-taxon`, which only this stream can
# produce.
#
# The build ignores all of them: lib.curated.load_table reads CURATED_COLUMNS and
# discards the rest.
PROVENANCE_COLUMNS = ["codesearch_target", "codesearch_display",
                      "codesearch_confidence", "codesearch_status",
                      "codesearch_reasoning"]

# Recorded per row in the log only. `path` (cached / fast / agentic) says how this
# run fetched an answer, not anything about the answer, so it would flip to
# "cached" on the next run and show up as a wall of changed rows in a diff where
# no mapping moved.
LOG_ONLY_COLUMNS = ["path"]

# --------------------------------------------------------------------------- #
# Sources
# --------------------------------------------------------------------------- #


def ig_codes():
    """(code, display) for the 646 organisms, read from the IG itself.

    Routed through the observation builder's own SOURCES declaration for the
    reason the four generators before it give: lib.curated.load_table rejects a
    row whose display differs from the IG's by so much as a character, so the
    generator and the build must read displays through the same function, and
    through the same declaration, or the table this writes can fail the build
    that reads it.

    Note the source names the CodeSystem, not the bound ValueSet:
    ValueSet-mimic-microbiology-organism.json is a bare compose with no
    enumerated concepts, so the CodeSystem is the only enumeration there is —
    the same shape as the microbiology antibiotics and test names.
    """
    from conceptmaps.build_observation_cm_vs import SOURCES

    source = next(s for s in SOURCES if s.get("table") == OUT_CSV)
    return dict(source_concepts(source))


def service_info(service):
    """code-search's self-reported configuration, or None if it won't say."""
    try:
        with urllib.request.urlopen(
                f"{service.rstrip('/')}/api/v1/info", timeout=30,
                context=fhirclient.SSL_CONTEXT) as response:
            return json.load(response)
    except Exception:                                 # noqa: BLE001
        return None


def find_code(service, text, timeout, attempts=4):
    """code-search's best match for `text`, constrained to CONSTRAINT_ECL.

    Retries transport failures. A dropped connection is not an answer, and the
    difference matters more here than it looks: 'the service said no match' and
    'the service was not running' both end up as an unmapped row, and only one
    of them is a finding. A run that quietly mixes the two produces a table that
    understates coverage and reads exactly like a real result. Exhausted retries
    raise, and main() refuses to write the CSV.
    """
    url = (f"{SNOMED}?fhir_vs=ecl/"
           f"{urllib.parse.quote(CONSTRAINT_ECL, safe='')}")
    body = json.dumps({
        "text": text,
        "url": url,
        "system": SNOMED,
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


# --------------------------------------------------------------------------- #
# The validation gate
# --------------------------------------------------------------------------- #


def gate(fhir_base, code):
    """('ok', display) if `code` is usable, else (reason, None).

    The same three checks verify_curated_snomed.py enforces, used as a filter
    rather than an assertion: a target that fails here is treated exactly as an
    absent one, and the item is left unmapped with the rejected proposal
    recorded. A confidence score says nothing about whether a concept is retired
    or belongs to a national extension, and an extension concept resolves on the
    server it was authored against and nowhere else — invisible by reading a CSV
    and it would survive the build.

    The display returned is the server's preferred term, not whatever string the
    service carried next to the code. That is what keeps verify-curated's fourth
    check (display must be a real designation of the concept) green by
    construction.
    """
    result = lookup(fhir_base, code)
    if result is None:
        return "absent", None
    active, module, names = result
    if not active:
        return "retired", None
    if module != INTL_MODULE:
        return "extension", None
    display = preferred_display(fhir_base, code)
    if not display or display not in names:
        return "no-display", None
    return "ok", display


def preferred_display(fhir_base, code):
    """The concept's preferred term on this server."""
    query = urllib.parse.urlencode({"system": SNOMED, "code": code})
    status, body = http(
        "GET", f"{fhir_base.rstrip('/')}/CodeSystem/$lookup?{query}")
    if status != 200 or not body:
        return None
    for parameter in body.get("parameter", []):
        if parameter["name"] == "display":
            return parameter["valueString"]
    return None


def validate_wrong_taxon(fhir_base, codes):
    """Every WRONG_TAXON entry names a real concept and a live itemid.

    A reject list fails SILENTLY when it is wrong: a mistyped SCTID or an itemid
    the IG has since dropped simply never matches, the answer it was meant to
    decline sails through, and nothing says so. Both halves are therefore checked
    before any search runs, and against the full IG enumeration rather than an
    `--only` subset, so a probe run cannot mask a stale entry.
    """
    problems = []
    for (mimic_code, code), (expected, _why) in sorted(WRONG_TAXON.items()):
        named = f"WRONG_TAXON {mimic_code} -> {code} |{expected}|"
        if mimic_code not in codes:
            problems.append(f"    {named}: the IG no longer has {mimic_code}")
        result = lookup(fhir_base, code)
        if result is None:
            problems.append(f"    {named}: not known to the server")
            continue
        active, _module, names = result
        if not active:
            problems.append(f"    {named}: retired")
        elif expected not in names:
            problems.append(f"    {named}: server does not call this "
                            f"{expected!r} — it is {sorted(names)[:3]}")
    if problems:
        print("\n  WRONG_TAXON does not describe this server:", file=sys.stderr)
        for problem in problems:
            print(problem, file=sys.stderr)
        sys.exit("  A reject list that names the wrong concept rejects nothing "
                 "and does so silently. Fix the entries and re-run.")


def assert_wrong_taxon_fired(rows):
    """Every WRONG_TAXON entry declined the row it was written about. Fatal.

    The other half of the same silent failure, and the half validate_wrong_taxon
    cannot see. That one runs before any search and can only check that the
    concept is real and the itemid is live; whether the service still PROPOSES
    that pairing is knowable only afterwards. An entry whose pairing no longer
    occurs is a judgement that has quietly evaporated — the row it was about now
    maps to whatever came back instead, unreviewed, and nothing says so.

    Not hypothetical. This list shipped with ("90707", "406609007") on the
    strength of one design probe; the population run answered that label with a
    different and better concept, so the entry declined nothing and the check
    that would have said so did not exist. See the WRONG_TAXON comment.

    Scoped to the codes actually searched, so an `--only` probe cannot fire it
    spuriously — it is the full run that has to justify every entry.
    """
    searched = {r["mimic_code"] for r in rows}
    fired = {(r["mimic_code"], r["codesearch_target"]) for r in rows
             if r["codesearch_status"] == "wrong-taxon"}
    dead = [(mimic, code) for (mimic, code) in sorted(WRONG_TAXON)
            if mimic in searched and (mimic, code) not in fired]
    if not dead:
        return
    for mimic, code in dead:
        row = next(r for r in rows if r["mimic_code"] == mimic)
        got = (f"{row['codesearch_target']} |{row['codesearch_display']}| "
               f"at {row['codesearch_confidence'] or '—'}"
               if row["codesearch_target"] else "no proposal at all")
        print(f"    WRONG_TAXON {mimic} -> {code} declined nothing: "
              f"code-search returned {got}", file=sys.stderr)
    sys.exit(f"  {len(dead)} WRONG_TAXON entr(ies) matched no row. The pairing "
             f"each was written about no longer occurs, so the entry declines "
             f"nothing while the row maps to whatever came back instead. "
             f"Re-read those rows, then update or delete the entries. NOT "
             f"writing {OUT_CSV.name}.")


# --------------------------------------------------------------------------- #
# Reviewed comments
# --------------------------------------------------------------------------- #


# Prose notes on individual mappings, keyed on (mimic_code, snomed_code).
#
# NOT equivalence. Every mapping this table supplies is `relatedto`, fixed by
# lib/assemble.py, and nothing here can change it. What an entry adds is a
# sentence in ConceptMap.target.comment for a row where the code pair alone would
# mislead a reader — a slash-joined label mapped to one of its two taxa is the
# shape most likely to need one here.
#
# Keyed on the PAIR and not on the itemid alone, because each note is written
# about one specific target concept. If a re-run moves the target, the note no
# longer describes what it was written about, and apply_comments exits rather
# than carrying it silently onto a different concept. An entry that matches no
# row is fatal, not a no-op.
#
# Comments only: this mechanism deliberately cannot pin a snomed_code. The moment
# it can, it becomes a way to hand-write mappings around CONFIDENCE_THRESHOLD and
# the gate.
#
# Empty on the first run: which rows need one is a question about what the
# service actually returned over the whole population, so the entries are written
# after reading the generated table, not guessed before it exists.
COMMENT_OVERRIDES = {}


def apply_comments(rows):
    """Attach the reviewed comments to their rows. Fatal on drift."""
    by_pair = {(r["mimic_code"], r["snomed_code"]): r
               for r in rows if r["snomed_code"]}
    for (code, target), comment in sorted(COMMENT_OVERRIDES.items()):
        row = by_pair.get((code, target))
        if row is None:
            current = next((r for r in rows if r["mimic_code"] == code), None)
            now = ("is no longer in the IG" if current is None else
                   f"now targets {current['snomed_code'] or '(unmapped)'}")
            sys.exit(f"  comment {code} -> {target} does not apply: the item "
                     f"{now}. The note was written about {target}, so it "
                     f"cannot be carried over. Re-read the row, then update or "
                     f"delete the entry.")
        if not comment:
            sys.exit(f"  comment {code} -> {target} is empty — delete the "
                     f"entry rather than leaving it blank.")
        row["comment"] = comment


# --------------------------------------------------------------------------- #
# Row construction
# --------------------------------------------------------------------------- #


def build_row(item, fhir_base, service, timeout):
    """One CSV row: the service asked once, its answer gated.

    The proposal is recorded whether or not it survives — a row rejected at
    CONFIDENCE_THRESHOLD, at the gate or by WRONG_TAXON keeps its
    `codesearch_target` and `codesearch_reasoning`, so the committed table shows
    what was considered and on what ground it was declined, rather than only
    that nothing was found.
    """
    code, label = item
    row = {c: "" for c in CURATED_COLUMNS + PROVENANCE_COLUMNS
           + LOG_ONLY_COLUMNS}
    row["mimic_code"] = code
    row["mimic_display"] = label

    confidence = 0.0
    try:
        result = find_code(service, TEMPLATE.format(label), timeout)
    except Exception as exc:                          # noqa: BLE001
        row["codesearch_status"] = f"error: {str(exc)[:80]}"
        result = None
    if result is not None:
        row["path"] = result.get("path", "")
        matches = result.get("matches") or []
        if not matches:
            row["codesearch_status"] = "no-match"
        else:
            match = matches[0]
            confidence = float(match.get("confidence") or 0.0)
            row["codesearch_confidence"] = f"{confidence:.2f}"
            row["codesearch_reasoning"] = (match.get("reasoning") or "").strip()
            row["codesearch_target"] = match["code"]
            row["codesearch_display"] = match.get("display", "")
            # MEANING FIRST, then the score, then the server — the ordering the
            # datetimeevents table established and for the same reason. What
            # disqualifies a WRONG_TAXON pair is what the concept MEANS, a fact
            # no score can change and no server check can see, and these
            # concepts are real, active and international so the gate would pass
            # them. Recording such a row as `below-threshold` would make the
            # committed table say a looser gate would take it, which is false.
            if (code, match["code"]) in WRONG_TAXON:
                row["codesearch_status"] = "wrong-taxon"
            elif confidence < CONFIDENCE_THRESHOLD:
                row["codesearch_status"] = "below-threshold"
            else:
                status, display = gate(fhir_base, match["code"])
                row["codesearch_status"] = status
                if status == "ok":
                    row.update(snomed_code=match["code"],
                               snomed_display=display)
                    return row

    row["comment"] = declined_comment(row, confidence)
    return row


def declined_comment(row, confidence):
    """Why a row carries no target. load_table requires one, and rightly: an
    empty target is a claim that the source could not answer, and a claim has to
    say what it rests on."""
    proposal = (f"{row['codesearch_target']} "
                f"|{row['codesearch_display']}| at {confidence:.2f}")
    why = WRONG_TAXON.get((row["mimic_code"], row["codesearch_target"]),
                          ("", ""))[1]
    return {
        "no-match": (f"code-search returned no match within "
                     f"{CONSTRAINT_ECL}."),
        "below-threshold": (f"code-search proposed {proposal}, below the "
                            f"{CONFIDENCE_THRESHOLD} threshold."),
        "wrong-taxon": (f"code-search proposed {proposal}, but {why}. The "
                        f"concept is a real organism inside the constraint and "
                        f"wrong about which one, so the mapping would assert "
                        f"something the source does not say."),
        "retired": (f"code-search proposed {proposal} but that concept is "
                    f"retired."),
        "extension": (f"code-search proposed {proposal} but that concept is not "
                      f"in the SNOMED international core."),
        "absent": f"code-search proposed {proposal} but that code is not known.",
        "no-display": (f"code-search proposed {proposal} but it has no usable "
                       f"display."),
    }.get(row["codesearch_status"], f"code-search: {row['codesearch_status']}.")


# --------------------------------------------------------------------------- #
# Reporting
# --------------------------------------------------------------------------- #


def report(rows):
    """What the run found. Printed so it can be pasted into a write-up."""
    mapped = [r for r in rows if r["snomed_code"]]
    print(f"\n  {len(rows)} item(s): {len(mapped)} mapped, "
          f"{len(rows) - len(mapped)} declared unmapped")

    statuses = {}
    for row in rows:
        statuses[row["codesearch_status"]] = \
            statuses.get(row["codesearch_status"], 0) + 1
    print("\n  code-search answer status")
    for status, count in sorted(statuses.items()):
        print(f"    {status:<16} {count:>4}")

    scored = sorted(float(r["codesearch_confidence"]) for r in rows
                    if r["codesearch_confidence"])
    if scored:
        print(f"\n  code-search confidence, {len(scored)} answered")
        buckets = [(1.0, 1.01), (0.9, 1.0), (0.8, 0.9), (0.7, 0.8), (0.0, 0.7)]
        for low, high in buckets:
            hits = [s for s in scored if low <= s < high]
            label = f"{low:.2f}" if high > 1.0 else f"{low:.2f}–{high:.2f}"
            print(f"    {label:<12} {len(hits):>4}")
        print(f"    threshold {CONFIDENCE_THRESHOLD}: "
              f"{sum(1 for s in scored if s >= CONFIDENCE_THRESHOLD)} kept, "
              f"{sum(1 for s in scored if s < CONFIDENCE_THRESHOLD)} dropped")

    # How many source items share a target. Some concentration is correct here —
    # `... SPECIES` labels and their genus-level siblings legitimately meet, and
    # the four numbered gram-negative rods are meant to land together — but a
    # taxon answering an implausible number of distinct organism names is the
    # shape of a bad answer, so it is printed rather than left to be found.
    shared = {}
    for row in mapped:
        shared.setdefault((row["snomed_code"], row["snomed_display"]),
                          []).append(row["mimic_code"])
    crowded = sorted(((len(v), k) for k, v in shared.items()), reverse=True)
    print(f"\n  {len(shared)} distinct target(s) for {len(mapped)} mapped item(s)")
    for count, (code, display) in crowded[:10]:
        if count > 1:
            print(f"    {count:>3} items -> {code:<12} {display[:48]}")

    commented = [r for r in rows if r["snomed_code"] and r["comment"]]
    if commented:
        print(f"\n  {len(commented)} mapped row(s) carrying a reviewed comment")
        for row in commented:
            print(f"    {row['mimic_code']} {row['mimic_display'][:34]:<34} "
                  f"-> {row['snomed_code']:<11} {row['snomed_display'][:44]}")

    unmapped = [r for r in rows if not r["snomed_code"]]
    print(f"\n  {len(unmapped)} unmapped, declared:")
    for row in unmapped:
        print(f"    {row['mimic_code']} {row['mimic_display'][:44]:<44} "
              f"{row['codesearch_status']}")


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    add_common_args(parser)
    parser.add_argument("--service",
                        default=DEFAULT_CODE_SEARCH or "http://localhost:3000",
                        help="code-search base URL (default: $CODE_SEARCH_URL "
                             "or %(default)s)")
    parser.add_argument("--workers", type=int, default=6,
                        help="concurrent code-search calls (default: %(default)s)")
    parser.add_argument("--timeout", type=int, default=600,
                        help="per-call timeout in seconds (default: %(default)s)")
    parser.add_argument("--only",
                        help="comma-separated mimic codes to ask about, for "
                             "probing a handful of items. Implies --dry-run: a "
                             "table built from a subset would drop every item "
                             "it did not ask about.")
    parser.add_argument("--dry-run", action="store_true",
                        help="report only; do not write the CSV")
    args = parser.parse_args()

    configure_tls(args.ca_bundle, args.insecure)
    if not args.fhir_base:
        sys.exit("  no --fhir-base and ONTOSERVER_URL unset — the validation "
                 "gate needs a terminology server.")

    codes = ig_codes()
    items = sorted(codes.items())
    if args.only:
        wanted = {c.strip() for c in args.only.split(",") if c.strip()}
        unknown = wanted - set(codes)
        if unknown:
            sys.exit(f"  --only names code(s) not in the IG: {sorted(unknown)}")
        items = [i for i in items if i[0] in wanted]
        args.dry_run = True

    print(f"  {len(items)} IG code(s)"
          + (f" (subset of {len(codes)}, --only)" if args.only else ""))
    print(f"  gate:       {args.fhir_base}")
    print(f"  service:    {args.service}")
    print(f"  ECL:        {CONSTRAINT_ECL}")
    print(f"  template:   {TEMPLATE}  (the identity wrapper — the label as it "
          f"stands)")
    print(f"  threshold:  {CONFIDENCE_THRESHOLD}")
    print(f"  rejects:    {len(WRONG_TAXON)} wrong-taxon pair(s)")
    print(f"  comments:   {len(COMMENT_OVERRIDES)}\n")

    # Before any search: a reject list that names the wrong concept — or an
    # itemid the IG has dropped — rejects nothing and says nothing about it.
    validate_wrong_taxon(args.fhir_base, codes)

    def work(item):
        row = build_row(item, args.fhir_base, args.service, args.timeout)
        print(f"    {row['mimic_code']} {row['mimic_display'][:40]:<40} "
              f"{row['codesearch_status']:<16} {row['snomed_code'] or '—':<12} "
              f"{row['snomed_display'][:36]}", flush=True)
        return row

    with concurrent.futures.ThreadPoolExecutor(args.workers) as pool:
        rows = list(pool.map(work, items))

    # Sorted by mimic_code so a re-run diffs only where an answer changed, not
    # wherever the thread pool happened to finish first.
    rows.sort(key=lambda r: r["mimic_code"])

    # A transport failure is not an answer. Writing a table whose gaps are half
    # findings and half a service that stopped answering would ship something
    # that reads like a result and is not one, so a partial run writes nothing.
    failed = [r for r in rows if r["codesearch_status"].startswith("error")]
    if failed:
        print(f"\n  {len(failed)} of {len(rows)} code-search call(s) failed "
              f"after retries — NOT writing {OUT_CSV.name}.")
        for row in failed[:5]:
            print(f"    {row['mimic_code']} {row['mimic_display'][:26]:<26} "
                  f"{row['codesearch_status'][:70]}")
        if len(failed) > 5:
            print(f"    … and {len(failed) - 5} more")
        sys.exit("  Fix the service and re-run; cached answers make the "
                 "retry cheap.")

    # After the failure gate, so that a run where the service dropped out
    # reports the transport failure rather than a wall of entries that could not
    # match because their targets never arrived. Both are fatal for the same
    # reason: a hand-written judgement that silently applies to nothing is worse
    # than no judgement, because the row it was about ships unreviewed.
    assert_wrong_taxon_fired(rows)
    apply_comments(rows)
    report(rows)

    if args.dry_run:
        print("\n  --dry-run: nothing written")
        return

    columns = CURATED_COLUMNS + PROVENANCE_COLUMNS
    with open(OUT_CSV, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns)
        writer.writeheader()
        writer.writerows({c: row[c] for c in columns} for row in rows)
    print(f"\n  wrote {OUT_CSV.relative_to(TERM.parents[1])}")

    LOG_JSON.parent.mkdir(parents=True, exist_ok=True)
    LOG_JSON.write_text(json.dumps({
        "constraint_ecl": CONSTRAINT_ECL,
        "template": TEMPLATE,
        "confidence_threshold": CONFIDENCE_THRESHOLD,
        # Every hand decision that touched this table, so the log records the
        # curation as well as the run. The rest is whatever the service said,
        # gated.
        "wrong_taxon": {f"{mimic}->{code}": {"display": display, "why": why}
                        for (mimic, code), (display, why)
                        in sorted(WRONG_TAXON.items())},
        "comment_overrides": {f"{code}->{target}": comment
                              for (code, target), comment
                              in sorted(COMMENT_OVERRIDES.items())},
        "fhir_base": args.fhir_base,
        # The service's own configuration at the end of the run. Recorded
        # because a `cached` path means the answer was produced by whatever model
        # was configured when it was first asked, which is not necessarily this
        # one — so this pins the run, not every row.
        "codesearch_service": service_info(args.service),
        "rows": rows,
    }, indent=2) + "\n")
    print(f"  wrote {LOG_JSON.relative_to(TERM.parents[1])}")


if __name__ == "__main__":
    main()
