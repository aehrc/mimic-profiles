"""The committed RxNorm term index, and the keying that reaches into it.

WHY THIS IS IN lib/ RATHER THAN IN THE GENERATOR THAT BUILT IT. The index is
ONE committed file — conceptmaps/medication-rxnorm-term-index.tsv — and it is
now read by three generators: build_medication_name_table.py, which owns it and
refreshes it, and build_formulary_drug_table.py and
build_medication_gsn_table.py, which only read it. The keys
in that file were written by `r3`/`salted` at refresh time, so a second copy of
those functions that drifted by one character would not raise anything: it would
silently stop matching, the deterministic tier would quietly shrink, and the
rows it used to settle would be re-answered by a model-backed service instead.

That is the same failure the README describes for the dot rules — reimplemented
in three scripts, drifted apart, and the coverage checker and the published map
disagreed as a result. So this is the notation.py of the term join: the keying
lives here and nowhere else.

WHAT IS NOT HERE: `refresh_index`. Writing the index is the name generator's
job, because that generator's CONSTRAINT_VCL is what defines which RxNorm
concepts the index covers. A reader asserts it was built under the constraint
the reader is also searching — see `load_index` — rather than being able to
rebuild it under its own.

NORMALISATION IS ASYMMETRIC, and the argument is build_medication_name_table's
to state in full: the INDEX keeps its parentheticals, and only the QUERY drops
them, as a late rung. The symmetric rule produces 146 colliding keys because in
RxNorm a trailing parenthetical is semantic rather than decorative
('polyvinyl alcohol' reaches six RxCUIs that differ only by molecular weight).
"""

import hashlib
import json
import re
import sys
import unicodedata

from .canonical import TABLE_DIR

INDEX_TSV = TABLE_DIR / "medication-rxnorm-term-index.tsv"
INDEX_MANIFEST = TABLE_DIR / "medication-rxnorm-term-index.json"

# Stripped from BOTH ends only. Never from the middle: `Sulfameth/Trimethoprim`
# and `Ipratropium-Albuterol` carry real internal punctuation.
_EDGE = " \t\r\n.,;:*#\"'`-/\\+"

# Token-wise, applied to whole tokens only, so `nascent` is not rewritten by the
# `na` entry. Salt names are the one place MIMIC and RxNorm reliably disagree in
# spelling rather than in meaning.
_SALT = {
    "hcl": "hydrochloride", "hbr": "hydrobromide", "na": "sodium",
    "k": "potassium", "so4": "sulfate", "sulphate": "sulfate",
    "phos": "phosphate", "mesilate": "mesylate",
}

_TRAILING_PAREN = re.compile(r"\s*\([^()]*\)\s*$")

# FDB's `generic [Brand]` display form, which only the GSN column uses. Anchored
# and non-greedy on the left so `a [b] [c]` splits at the LAST bracket group,
# and the inner class excludes brackets so a nested one cannot be swallowed.
_BRACKETED = re.compile(r"^(?P<generic>.*?)\s*\[(?P<brand>[^\[\]]*)\]\s*$")


def r3(text):
    """The base key: NFKC, casefold, collapse whitespace, strip edge punctuation."""
    text = unicodedata.normalize("NFKC", text).casefold().strip()
    text = " ".join(text.split())
    return text.strip(_EDGE).strip()


def salted(key):
    """`r3` output with salt-name tokens canonicalised, or None if unchanged."""
    tokens = [_SALT.get(t, t) for t in key.split(" ")]
    out = " ".join(tokens)
    return out if out != key else None


def deparenthesised(key):
    """`r3` output with one trailing parenthetical removed, or None if none."""
    out = _TRAILING_PAREN.sub("", key).strip(_EDGE).strip()
    return out if out and out != key else None


def query_rungs(display):
    """(rung name, key) in the order they are tried. First unique hit wins.

    Q1/Q2 are lossless. Q3/Q4 discard a trailing qualifier and land on the
    ingredient — recorded per row so a reader can tell the two apart.
    """
    base = r3(display)
    rungs = [("Q1-exact", base)]
    if (s := salted(base)):
        rungs.append(("Q2-salt", s))
    if (p := deparenthesised(base)):
        rungs.append(("Q3-paren", p))
        if (ps := salted(p)):
            rungs.append(("Q4-paren-salt", ps))
    return rungs


def bracketed_rungs(display):
    """(rung name, key) for FDB's `generic [Brand]` display form, or [].

    Tried AFTER query_rungs and only by build_medication_gsn_table.py. The GSN
    column writes a drug two ways in one string — `lamotrigine [Lamictal]`,
    `hepatitis A and B vaccine (PF) [Twinrix (PF)]` — and neither half is
    reachable by the rungs above, because the whole string is a key RxNorm has
    no term for. 2,137 of the 9,347 GSN displays take this form.

    WHY THIS IS OPT-IN RATHER THAN PART OF query_rungs. The bracket is GSN's
    grammar and nobody else's: of the other three populations that join against
    this index, `mimic-medication-name` has 0 bracketed displays out of 9,971,
    `mimic-medication-formulary-drug-cd` 0 of 4,108 and `mimic-medication-icu`
    0 of 474. Folding these rungs into query_rungs would therefore be a no-op
    for every committed table — but it would still widen the shared function on
    the strength of one stream's label convention, and the `join_rung` column
    exists so a reader can tell WHICH loss a row took. Two functions keep the
    two grammars, and their two kinds of loss, distinguishable in the CSV.

    B1/B2 land on the generic name the label leads with. B3/B4 additionally
    discard a trailing parenthetical from it, exactly as Q3/Q4 do. B5/B6 are
    the last resort and land on the BRAND concept instead — asserting the brand
    as the drug's identity, which the label does state outright, but at a
    different specificity from the generic. Generic before brand, because 874
    GSN displays reach BOTH with different RxCUIs and the generic is what FDB
    puts first; the rung name is what records which one answered.

    No new ambiguity is possible here. refresh_index deletes every key reaching
    more than one RxCUI, so a hit is unique by construction and an extra QUERY
    rung can only ever add lossiness — never a tie to break.
    """
    if not (match := _BRACKETED.match(display)):
        return []
    rungs = []
    if (generic := r3(match.group("generic"))):
        rungs.append(("B1-generic", generic))
        if (gs := salted(generic)):
            rungs.append(("B2-generic-salt", gs))
        if (gp := deparenthesised(generic)):
            rungs.append(("B3-generic-paren", gp))
            if (gps := salted(gp)):
                rungs.append(("B4-generic-paren-salt", gps))
    if (brand := r3(match.group("brand"))):
        rungs.append(("B5-brand", brand))
        if (bp := deparenthesised(brand)):
            rungs.append(("B6-brand-paren", bp))
    return rungs


def load_index(constraint_vcl=None):
    """The committed term index, with its manifest verified.

    Two tripwires, and the second is what makes the file safe to share:

      the sha256, so a hand-edited index cannot become a mapping;
      `constraint_vcl`, so a generator searching one constraint cannot join
      against an index built under another. Without it, a reader would keep
      matching keys that describe concepts outside its own search space — every
      one of them a target its own gate would have rejected, arriving through
      the tier that has no gate at all.
    """
    if not INDEX_TSV.is_file():
        sys.exit(f"  {INDEX_TSV.name} not found. Run "
                 f"`make medication-name-table ARGS=\"--refresh-index "
                 f"--insecure\"` first; it needs the network.")
    manifest = json.loads(INDEX_MANIFEST.read_text())
    actual = hashlib.sha256(INDEX_TSV.read_bytes()).hexdigest()
    if manifest["tsv_sha256"] != actual:
        sys.exit(f"  {INDEX_TSV.name} does not match tsv_sha256 in "
                 f"{INDEX_MANIFEST.name}. A hand-edited index must not become "
                 f"a mapping.\n    expected {manifest['tsv_sha256']}"
                 f"\n    actual   {actual}")
    if constraint_vcl is not None and manifest["constraint_vcl"] != constraint_vcl:
        sys.exit(f"  {INDEX_TSV.name} was built under a different constraint, "
                 f"so its keys describe a different set of RxNorm concepts "
                 f"than this generator searches. Joining against it would let "
                 f"targets past a gate they were never shown.\n"
                 f"    index    {manifest['constraint_vcl']}\n"
                 f"    searching {constraint_vcl}")
    index = {}
    with open(INDEX_TSV, newline="") as fh:
        for line in fh:
            key, _, rxcui = line.rstrip("\n").partition("\t")
            index[key] = rxcui
    return index, manifest
