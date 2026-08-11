"""Every mapping stream, declared exactly once.

A STREAM is one source enumeration resolved into one or more target systems by
exactly one resolver — a committed table, a notation rule, or identity. It is
the unit the statistics are keyed by, the unit a generator regenerates, and the
unit a worklist (unmapped-<stream>.csv) is written for.

The stream key is the ENUMERATING IG RESOURCE, not the source CodeSystem. For
most streams the two coincide: the ValueSets bound over the MIMIC CodeSystems
are bare composes enumerating nothing, so the CodeSystem is the only
enumeration there is. `mimic-d-items` is the exception that forces the general
rule: one CodeSystem partitioned across three subset ValueSets, each mapped
from its own table into its own target system. Keyed by CodeSystem those would
be one stream with three tables and two target vocabularies — a number that
describes nothing. Keyed by enumeration they are the three streams the three
committed tables already are.

Names follow the committed tables (and their generation logs, and the `make`
targets): `d-items-snomed.csv` -> stream `d-items`, `labevents-loinc.csv` ->
`labevents`. Streams with no table (notation, identity) are named for their
enumerating resource.

WHY A REGISTRY, when this repo's stance is that a hand-kept list is the thing a
glob exists to avoid. That stance is about CONSUMER lists — "which fields share
this table" stays discovered, from which builders reference a stream name (see
lib/builders.py). A stream DECLARATION is the opposite case: before this file,
the same stream was declared once per consuming builder, and the duplicates
could disagree — mimic-medication-ndc was declared with a table in one builder
and without it in another, so the same Coding translated differently depending
on which element it sat on. One declaration, referenced by name, is the fix; a
builder naming an unknown stream is a hard error listing the real ones.

Streams sharing a source system must have pairwise-disjoint enumerations —
otherwise one code belongs to two streams and is counted twice, which is the
exact double-count this registry exists to end. check_disjoint() enforces it
and verify_mappings runs it.

DISJOINTNESS IS ONLY HALF THE INVARIANT. A registry that cannot double-count can
still under-count, by simply not mentioning a population — and the failure is
silent in a way an overlap is not, because a stream that does not exist writes no
row, no worklist and no warning. undeclared() is the other half: it reads the
bindings out of occurrences/elements.json, subtracts what the registry declares,
and hands back what is left, so build_stream_reports can give the gap a row in
the per-stream table (at 0% coverage, in the denominator) instead of leaving it
out of the numbers entirely. Adding a stream should be able to LOWER the headline
figure by revealing work; it must never RAISE it by revealing nothing.
"""

import sys

from common import occurrences

from .assemble import target
from .canonical import (ICD9_CM, ICD10_CM, ICD10_PCS, LOINC, MIMIC_BASE,
                        NULL_FLAVOR, RXNORM, SNOMED, TABLE_DIR)
from .curated import MIXED_TARGET_COLUMNS
from .igsource import resource_path, source_concepts
from .notation import (dot_icd9_diagnosis, dot_icd9_procedure, dot_icd10cm,
                       is_pcs_leaf, no_dot)

# One note per stream, not per consuming element: a stream resolves identically
# wherever it is consumed, so its explanation must too.
_POE_IV_NOTE = (
    "Maps nothing by design. `IV therapy` and `TPN` are POE order flags, not "
    "substances, so no RxNorm concept exists for either at any term type — and "
    "a SNOMED procedure code, which does exist, would put a procedure in a "
    "column whose FHIRPath is medication[x] or Medication.code. The 0% is the "
    "honest result of a modelling defect one layer down, in the ETL, not of a "
    "mapping that failed. Every map whose binding admits these two codes "
    "declines them from this one shared table.")

_NDC_NOTE = (
    "The one stream in this repo with no model and no threshold: an NDC is a "
    "package identifier, not a label, and RxNorm publishes the mapping as a "
    "property. Two deterministic tiers — the NDC property, then the MIMIC "
    "label joined against the committed drug-name table — and a code either "
    "resolves through one of them or is declared. Where both tiers answer and "
    "disagree the NDC wins, because it is the manufacturer's own package "
    "identity rather than a free-text drug name; the label's answer is kept "
    "on the table row as `display_rxcui` so the disagreement stays auditable. "
    "Read a mapped target's specificity from its term type: the NDC tier "
    "gives the packaged product, the label tier only an ingredient-level "
    "generalisation.")

_ETC_NOTE = (
    "A therapeutic CLASS rather than a drug, which is why this is the one "
    "medication stream with no RxNorm target: RxNorm publishes no class "
    "concepts at any term type, and ATC — the natural target — is on no "
    "server this repo can reach. Mapped into SNOMED CT's substance hierarchy "
    "and not its medicinal-product hierarchy, because `<<763158003` contains "
    "no diuretic and no dihydropyridine concept whatsoever, which is 4.66% of "
    "the element's occurrences a product-only constraint could never reach. "
    "Consumers should read a target as 'the class of drug this record names', "
    "never as the drug: 57 of the 1,201 source codes are not medications at "
    "all (FDB files devices, supplies and bulk chemicals in the same column) "
    "and are declined, and one — `Chemicals - Solvents` — is a known accepted "
    "defect mapping to a laboratory reagent.")

_GSN_NOTE = (
    "The one medication stream a deterministic join mostly answers: the codes "
    "are FDB Generic Sequence Numbers and their displays are drug names, so "
    "61.4% of the enumeration (64.1% of the codings) resolves against the "
    "committed RxNorm term index with no model, no threshold and no judgement — "
    "including 2,137 displays in FDB's `generic [Brand]` form, which needs its "
    "own query rungs (lib/termindex.bracketed_rungs). Only the residual is "
    "asked of code-search. Two consequences for a consumer. Read a mapped "
    "target's specificity from its term type rather than assuming it: a label "
    "stating a strength and form reaches the clinical drug (`FoLIC Acid 1mg "
    "TAB` -> the 1 MG oral tablet), while a brand-only or ingredient-only "
    "label reaches only the ingredient, and a bracketed one is mapped to the "
    "GENERIC it names first, not to the brand. And this is the only medication "
    "stream with no SNOMED CT target at all, so a GSN code naming a drug class "
    "is declared rather than mapped into the substance hierarchy — an omission "
    "by decision, taken after that hierarchy answered `TAB A VITE` with a "
    "nerve agent.")

STREAMS = {
    # ------------------------------------------------------------------ #
    # ICD notation streams. Deterministic dot insertion, cannot fail on a
    # code the built releases carry. See lib/notation.py.
    # ------------------------------------------------------------------ #
    "diagnosis-icd10": {
        "system": f"{MIMIC_BASE}/CodeSystem/mimic-diagnosis-icd10",
        "file": "CodeSystem-mimic-diagnosis-icd10.json",
        "targets": [target(ICD10_CM, dot_icd10cm)],
    },
    "diagnosis-icd9": {
        "system": f"{MIMIC_BASE}/CodeSystem/mimic-diagnosis-icd9",
        "file": "CodeSystem-mimic-diagnosis-icd9.json",
        # The ICD-10-CM fallback is how the six codes MIMIC filed under
        # icd_version 9 that are really ICD-10-CM are found. Diagnosis only:
        # the same fallback on procedures collides with PCS groupers.
        "targets": [
            target(ICD9_CM, dot_icd9_diagnosis, kind="diagnosis"),
            target(ICD10_CM, dot_icd10cm),
        ],
    },
    "procedure-icd10": {
        "system": f"{MIMIC_BASE}/CodeSystem/mimic-procedure-icd10",
        "file": "CodeSystem-mimic-procedure-icd10.json",
        "targets": [target(ICD10_PCS, no_dot, predicate=is_pcs_leaf)],
    },
    "procedure-icd9": {
        "system": f"{MIMIC_BASE}/CodeSystem/mimic-procedure-icd9",
        "file": "CodeSystem-mimic-procedure-icd9.json",
        "targets": [target(ICD9_CM, dot_icd9_procedure, kind="procedure")],
    },

    # ------------------------------------------------------------------ #
    # Identity streams: already standard terminology, mapped to themselves
    # so "needs no translation" is a declared fact rather than a silent
    # omission.
    # ------------------------------------------------------------------ #
    "procedure-types-ed": {
        "system": SNOMED,
        "valueset_file": "ValueSet-mimic-procedure-types-ed.json",
        "identity": True,
        "targets": [target(SNOMED, no_dot)],
    },
    "observation-type-ed": {
        "system": LOINC,
        "valueset_file": "ValueSet-mimic-observation-type-ed.json",
        "identity": True,
        "targets": [target(LOINC, no_dot)],
    },
    "observation-type-vital": {
        "system": LOINC,
        "valueset_file": "ValueSet-mimic-observation-type-vital.json",
        "identity": True,
        "targets": [target(LOINC, no_dot)],
    },
    "observation-component-vital": {
        "system": LOINC,
        "valueset_file": "ValueSet-mimic-observation-component-vital.json",
        "identity": True,
        "targets": [target(LOINC, no_dot)],
    },
    "medication-with-unknown": {
        # v3-NullFlavor#UNK, for administrations whose drug could not be
        # coded. Ships in input/resources/ despite being a ValueSet, hence
        # `file` rather than `valueset_file`.
        "system": NULL_FLAVOR,
        "file": "ValueSet-mimic-medication-with-unknown.json",
        "identity": True,
        "targets": [target(NULL_FLAVOR, no_dot)],
    },

    # ------------------------------------------------------------------ #
    # Table streams: the populations no rule can derive. One committed CSV
    # per stream, named <stream>-<target>.csv; the generation log drops the
    # target token (lib/stats._log_path).
    # ------------------------------------------------------------------ #
    "d-items": {
        # The procedureevents partition of CodeSystem mimic-d-items. The
        # subset ValueSet is the enumeration — the CodeSystem also holds the
        # datetimeevents and outputevents partitions, which are their own
        # streams with their own tables and targets.
        "system": f"{MIMIC_BASE}/CodeSystem/mimic-d-items",
        "valueset_file": "ValueSet-mimic-procedureevents-d-items.json",
        "table": TABLE_DIR / "d-items-snomed.csv",
        "targets": [target(SNOMED, no_dot)],
    },
    "datetimeevents": {
        "system": f"{MIMIC_BASE}/CodeSystem/mimic-d-items",
        "valueset_file": "ValueSet-mimic-datetimeevents-d-items.json",
        "table": TABLE_DIR / "datetimeevents-snomed.csv",
        "targets": [target(SNOMED, no_dot)],
    },
    "outputevents": {
        "system": f"{MIMIC_BASE}/CodeSystem/mimic-d-items",
        "valueset_file": "ValueSet-mimic-outputevents-d-items.json",
        "table": TABLE_DIR / "outputevents-loinc.csv",
        "table_columns": ("loinc_code", "loinc_display"),
        "targets": [target(LOINC, no_dot)],
    },
    "micro-susc": {
        "system": f"{MIMIC_BASE}/CodeSystem/mimic-microbiology-antibiotic",
        "file": "CodeSystem-mimic-microbiology-antibiotic.json",
        "table": TABLE_DIR / "micro-susc-loinc.csv",
        "table_columns": ("loinc_code", "loinc_display"),
        "targets": [target(LOINC, no_dot)],
    },
    "micro-test": {
        "system": f"{MIMIC_BASE}/CodeSystem/mimic-microbiology-test",
        "file": "CodeSystem-mimic-microbiology-test.json",
        "table": TABLE_DIR / "micro-test-loinc.csv",
        "table_columns": ("loinc_code", "loinc_display"),
        "targets": [target(LOINC, no_dot)],
    },
    "micro-org": {
        "system": f"{MIMIC_BASE}/CodeSystem/mimic-microbiology-organism",
        "file": "CodeSystem-mimic-microbiology-organism.json",
        "table": TABLE_DIR / "micro-org-snomed.csv",
        "targets": [target(SNOMED, no_dot)],
    },
    "labevents": {
        "system": f"{MIMIC_BASE}/CodeSystem/mimic-d-labitems",
        "file": "CodeSystem-mimic-d-labitems.json",
        "table": TABLE_DIR / "labevents-loinc.csv",
        "table_columns": ("loinc_code", "loinc_display"),
        "targets": [target(LOINC, no_dot)],
    },
    "chartevents": {
        "system": f"{MIMIC_BASE}/CodeSystem/mimic-chartevents-d-items",
        "file": "CodeSystem-mimic-chartevents-d-items.json",
        "table": TABLE_DIR / "chartevents-standard.csv",
        "table_columns": MIXED_TARGET_COLUMNS,
        "targets": [target(LOINC, no_dot), target(SNOMED, no_dot)],
    },
    "lab-fluid": {
        "system": f"{MIMIC_BASE}/CodeSystem/mimic-lab-fluid",
        "file": "CodeSystem-mimic-lab-fluid.json",
        "table": TABLE_DIR / "lab-fluid-snomed.csv",
        "targets": [target(SNOMED, no_dot)],
    },
    "spec-type": {
        "system": f"{MIMIC_BASE}/CodeSystem/mimic-spec-type-desc",
        "file": "CodeSystem-mimic-spec-type-desc.json",
        "table": TABLE_DIR / "spec-type-snomed.csv",
        "targets": [target(SNOMED, no_dot)],
    },
    "medication-name": {
        "system": f"{MIMIC_BASE}/CodeSystem/mimic-medication-name",
        "file": "CodeSystem-mimic-medication-name.json",
        "table": TABLE_DIR / "medication-name-standard.csv",
        # Mixed-target: a few labels name a drug CLASS rather than a product,
        # and SNOMED CT has the class concept where RxNorm has only the
        # specific products.
        "table_columns": MIXED_TARGET_COLUMNS,
        "targets": [target(RXNORM, None), target(SNOMED, None)],
    },
    "medication-poe-iv": {
        "system": f"{MIMIC_BASE}/CodeSystem/mimic-medication-poe-iv",
        "file": "CodeSystem-mimic-medication-poe-iv.json",
        # Complete, and maps nothing BY DECISION — the obstacle is upstream
        # of terminology, so its gaps bucket apart from genuine declines and
        # every element consuming it reports coverage both with and without
        # them. See common/occurrences.py BLOCKED.
        "blocked_upstream": True,
        "note": _POE_IV_NOTE,
        "note_url": "https://github.com/fhnaumann/master_thesis_pipeline/issues/26",
        "table": TABLE_DIR / "medication-poe-iv-standard.csv",
        "table_columns": MIXED_TARGET_COLUMNS,
        "targets": [target(RXNORM, None), target(SNOMED, None)],
    },
    "formulary-drug": {
        "system": f"{MIMIC_BASE}/CodeSystem/mimic-medication-formulary-drug-cd",
        "file": "CodeSystem-mimic-medication-formulary-drug-cd.json",
        "table": TABLE_DIR / "formulary-drug-standard.csv",
        "table_columns": MIXED_TARGET_COLUMNS,
        "targets": [target(RXNORM, None), target(SNOMED, None)],
    },
    "medication-icu": {
        "system": f"{MIMIC_BASE}/CodeSystem/mimic-medication-icu",
        "file": "CodeSystem-mimic-medication-icu.json",
        "table": TABLE_DIR / "medication-icu-standard.csv",
        "table_columns": MIXED_TARGET_COLUMNS,
        "targets": [target(RXNORM, None), target(SNOMED, None)],
    },
    "medication-etc": {
        # FDB Enhanced Therapeutic Classification: the source codes name a drug
        # CLASS and nothing else, which makes this the one medication stream
        # with no RxNorm target — RxNorm publishes no class concepts at any term
        # type, and ATC, which would be the natural target, is not on the
        # server. Single-target SNOMED, and the substance hierarchy rather than
        # the product one because `<<763158003` contains no diuretic and no
        # dihydropyridine concept at all: 4.66% of the element's occurrences
        # that a product-only constraint cannot reach for a structural reason.
        # See build_medication_etc_table.py and issue #28.
        "system": f"{MIMIC_BASE}/CodeSystem/mimic-medication-etc",
        "file": "CodeSystem-mimic-medication-etc.json",
        "table": TABLE_DIR / "medication-etc-snomed.csv",
        "targets": [target(SNOMED, no_dot)],
        "note": _ETC_NOTE,
        "note_url": "https://github.com/fhnaumann/master_thesis_pipeline/issues/28",
    },
    "medication-gsn": {
        # FDB Generic Sequence Numbers, and the one medication stream whose
        # deterministic tier does most of the work: the displays are drug NAMES
        # in FDB's `generic [Brand]` grammar, so 61.4% of the enumeration joins
        # against the committed RxNorm term index with no model involved. The
        # only SINGLE-TARGET RxNorm table here — the SNOMED substance rung the
        # sibling name/formulary streams carry was probed and dropped, because
        # GSN has no drug-CLASS gap to fill and the hierarchy answered
        # `TAB A VITE` with the nerve agent Tabun. See
        # build_medication_gsn_table.py and issue #29.
        "system": f"{MIMIC_BASE}/CodeSystem/mimic-medication-gsn",
        "file": "CodeSystem-mimic-medication-gsn.json",
        "table": TABLE_DIR / "medication-gsn-rxnorm.csv",
        "table_columns": ("rxnorm_code", "rxnorm_display"),
        "targets": [target(RXNORM, None)],
        "note": _GSN_NOTE,
        "note_url": "https://github.com/fhnaumann/master_thesis_pipeline/issues/29",
    },
    "medication-ndc": {
        "system": f"{MIMIC_BASE}/CodeSystem/mimic-medication-ndc",
        "file": "CodeSystem-mimic-medication-ndc.json",
        "table": TABLE_DIR / "medication-ndc-standard.csv",
        # Mixed-target for one reason only: tier 2 reads medication-name-
        # standard.csv, which routes drug-CLASS labels to SNOMED substances,
        # and a handful of NDC codes inherit a SNOMED target that way. Tier 1
        # is RxNorm-only.
        "table_columns": MIXED_TARGET_COLUMNS,
        "targets": [target(RXNORM, None), target(SNOMED, None)],
        "note": _NDC_NOTE,
        "note_url": "https://github.com/fhnaumann/master_thesis_pipeline/issues/25",
    },
}


def get(name):
    """One stream's declaration, carrying its own name.

    A wrong name is a hard error listing the real ones — the registry's whole
    contract is that a stream cannot be half-declared by a typo.
    """
    if name not in STREAMS:
        sys.exit(f"  unknown stream {name!r}. Declared streams: "
                 f"{', '.join(sorted(STREAMS))}")
    return {"stream": name, **STREAMS[name]}


def sources(*names):
    """The SOURCES list for a builder, from stream names.

    Order is preserved: it is the declaration order the ConceptMap's groups
    and the build's progress lines follow.
    """
    return [get(name) for name in names]


def stream_for_table(table_path):
    """The stream a committed table belongs to, for the generators."""
    for name, stream in STREAMS.items():
        if stream.get("table") == table_path:
            return {"stream": name, **stream}
    sys.exit(f"  no stream declares {table_path.name}. A generator writes the "
             f"table its stream reads; declare the stream in lib/streams.py "
             f"first, or this run produces a file nothing will ever load.")


def enumeration(stream):
    """[(code, display)] — the stream's full enumeration, from the IG."""
    return list(source_concepts(stream))


def check_disjoint():
    """Streams sharing a source system must partition it, not overlap.

    Returns a list of human-readable failures, empty when the invariant
    holds. An overlapping code would belong to two streams, be counted twice
    in every statistic, and could be published with two different targets —
    the double-count this registry exists to end.
    """
    by_system = {}
    for name in sorted(STREAMS):
        stream = get(name)
        by_system.setdefault(stream["system"], []).append(
            (name, {code for code, _ in enumeration(stream)}))
    failures = []
    for system, entries in by_system.items():
        for i, (name_a, codes_a) in enumerate(entries):
            for name_b, codes_b in entries[i + 1:]:
                shared = codes_a & codes_b
                if shared:
                    failures.append(
                        f"streams {name_a!r} and {name_b!r} overlap in "
                        f"{len(shared)} code(s) of {system}, e.g. "
                        f"{sorted(shared)[:5]} — a code must belong to "
                        f"exactly one stream")
    return failures


def streamed_keys():
    """{(system, code)} — every code the registry declares, across all streams.

    The universe the per-stream view can see. Anything a binding admits that is
    not in here is invisible to that view until undeclared() names it.
    """
    keys = set()
    for name in sorted(STREAMS):
        stream = get(name)
        keys |= {(stream["system"], code) for code, _ in enumeration(stream)}
    return keys


def _undeclared_name(system):
    """The name an undeclared population is reported under.

    The enumerating resource's id with the `mimic-` prefix dropped, which is the
    naming rule a real stream over the same CodeSystem would follow — so
    declaring the stream later keeps the row, its worklist filename and its
    history rather than renaming them. A collision with a declared name is
    impossible by construction (that stream would cover these codes) but is
    resolved to the full id anyway rather than silently merging two rows.
    """
    name = system.rstrip("/").rsplit("/", 1)[-1]
    short = name[len("mimic-"):] if name.startswith("mimic-") else name
    return short if short not in STREAMS else name


def undeclared():
    """[population] — every bound (system, code) that NO stream declares.

    [{stream, system, concepts: {code: display}, bound_on: [element, ...]}],
    sorted by system, one entry per source system rather than per element: a
    population is a property of the codes, and reporting it once per binding
    that admits it would double-count exactly the way check_disjoint exists to
    prevent.

    Read from occurrences/elements.json — the bindings as the profiles write
    them — and NOT from the builders' SOURCES. Comparing the registry against
    the builders can only find a stream someone forgot to wire up; it is blind
    to a population no builder ever mentioned, and to an element with no builder
    at all, which is the case this function exists for. Returns [] when the
    registry is absent (elements.json is committed, so that means a partial
    checkout) or when no bound ValueSet could be expanded, because "nothing is
    bound" and "nothing could be read" must not produce the same answer as
    "everything is covered".
    """
    reg = occurrences.registry()
    if not reg:
        return []
    index = occurrences._resource_index()  # noqa: SLF001 — same repo, same job
    bound_on, displays = {}, {}
    for element in sorted(reg):
        for url in reg[element].get("bound_valuesets", []):
            for key, display in occurrences.expand(url, index).items():
                displays.setdefault(key, display)
                bound_on.setdefault(key, set()).add(element)

    gap = set(displays) - streamed_keys()
    by_system = {}
    for system, code in sorted(gap):
        entry = by_system.setdefault(system, {"concepts": {}, "bound_on": set()})
        entry["concepts"][code] = displays[(system, code)]
        entry["bound_on"] |= bound_on[(system, code)]
    return [{"stream": _undeclared_name(system),
             "system": system,
             "concepts": entry["concepts"],
             "bound_on": sorted(entry["bound_on"])}
            for system, entry in sorted(by_system.items())]


def check_covers_bindings():
    """The other half of check_disjoint: does the registry COVER the bindings?

    Returns a list of human-readable gaps, empty when every code a bound
    ValueSet admits belongs to some stream. Not fatal on its own — an
    undeclared population is a data gap of exactly the kind unmapped-<stream>.csv
    records, not a correctness bug in what was built — so verify_mappings gates
    it behind --allow-unmapped alongside the unmapped counts.
    """
    return [f"{len(pop['concepts']):,} code(s) of {pop['system']} belong to no "
            f"stream, though {', '.join(pop['bound_on'])} bind them — declare a "
            f"stream for them in lib/streams.py, or they stay a 0% row nothing "
            f"can fill"
            for pop in undeclared()]


def stream_label(source):
    """The name a resolved source is reported under.

    Sources built from this registry carry their stream name; anything else
    falls back to the enumerating resource's id, which was the old naming
    rule and keeps foreign declarations printable.
    """
    return source.get("stream") or resource_path(source).stem.split("-", 1)[1]
