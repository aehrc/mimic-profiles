"""Resolving stream declarations into ConceptMap groups.

A builder consumes streams (lib/streams.py); this resolves each one and turns
the outcomes into R4 groups plus the list of codes nothing could map. Three
resolver shapes are supported, and a stream picks exactly one:

  notation  `targets` is an ordered list of target(); the first that resolves
            wins, later entries are the cross-system fallback.
  identity  `identity: True`; the code is already standard terminology and maps
            to itself.
  table     `table` names a committed CSV; the mapping is data, see curated.py.
            Single-target by default. A table declaring MIXED_TARGET_COLUMNS
            names its target system per row instead, and then one stream spans
            one group per system it named — which is how the chartevents stream
            reaches LOINC where LOINC answers and SNOMED CT where it does not.

The resolver also fixes the equivalence: `equivalent` for notation and identity,
`relatedto` for every table row. See build_groups for why it is a property of
the resolver rather than of the row.

A STREAM RESOLVES IDENTICALLY WHEREVER IT IS CONSUMED. resolve_source is a
function of (declaration, built releases, union-observed codes) and knows no
bound element, so two ConceptMaps consuming one stream cannot publish two
answers for one code. That replaces the per-element `observed_only` narrowing
this module used to apply, under which the same drug code was `mapped` in one
medication map and `unmatched / not-observed` in a sibling — defensible, but it
meant a consumer's answer depended on which element the Coding sat on, and it
made every shared stream's numbers exist once per consuming field.

Nothing downstream re-derives a mapping. The builders write a ConceptMap; the
ValueSet projection, the verifier, the stream reports and every consumer read
what one resolution pass produced.
"""

import sys
from collections import defaultdict

from .built import find
from .curated import DEFAULT_TARGET_COLUMNS, is_mixed, load_table
from .igsource import resource_path

# The reason recorded for a code the binding admits that the warehouse records
# on NO bound element at all — a union-level fact, read from the committed
# occurrence counts. It is deliberately NOT one of the resolver's failure
# reasons: nothing was searched for and nothing was declined, so folding it in
# with them would inflate every "we tried and failed" number in the statistics.
NOT_OBSERVED = "not-observed-in-data"

# The reason recorded for a population a stream declares but has no resolver
# for yet. Distinct from the other reasons on purpose:
#
#   not-observed-in-data  no data anywhere carries the code
#   no-row-in-curated-table  observed, but the table predates its population
#   no-suitable-concept   a stream considered this code and declined it
#   no-stream-yet         nobody has looked
#
# Declared absence is a fact; omission is not. A population left out of the map
# entirely answers $translate with silence, which a consumer cannot tell from a
# map that failed to load.
NOT_BUILT = "no-stream-yet"

# Outcome kinds resolve_source emits. MAPPED carries a target; every other kind
# becomes an `unmatched` element and a worklist row.
MAPPED = "mapped"

Target = dict  # {system, rule, kind, predicate}


def target(system, rule, kind=None, predicate=None):
    """One candidate target system for a stream.

    `rule` rewrites the MIMIC code into the target's notation. `kind` filters on
    the built CodeSystem's `kind` property, which is how ICD-9-CM diagnoses
    (Vol 1-2) and procedures (Vol 3) are told apart — THO gives them the same
    canonical URL, so a Coding cannot distinguish them. `predicate` rejects codes
    that exist but are not selectable, e.g. PCS groupers.
    """
    return {"system": system, "rule": rule, "kind": kind, "predicate": predicate}


def method_of(source):
    """Which resolver a declaration picked, for the reports.

    `declared` is the last case: no table, no identity, and no notation rule on
    any target — a population declared only so that every code the binding
    admits has an entry in the map. It must not read as `notation`, which would
    name a resolver that does not exist.
    """
    if source.get("identity"):
        return "identity"
    if "table" in source:
        return "table"
    if any(t["rule"] for t in source["targets"]):
        return "notation"
    return "declared"


def resolve_source(source, built, observed):
    """Resolve one stream: every enumerated code to exactly one outcome.

    `observed` is the union of (system, code) pairs the occurrence extraction
    saw on ANY bound element, or None when that artifact is absent. It affects
    no mapping — only which reason an un-tabled code is reported under, because
    "nobody uses this code" and "the table has not caught up with this
    population" are different backlogs. Without the artifact both report as
    `no-row-in-curated-table`, which is the weaker, always-true claim.

    Returns [(code, display, outcome)] in enumeration order, where a MAPPED
    outcome is {kind, target_system, target_code, target_display, equivalence,
    comment} and every other outcome is {kind (== the worklist reason),
    expected_code, expected_system, comment}.
    """
    from .igsource import source_concepts  # local import keeps lib acyclic

    enumerated = list(source_concepts(source))
    table_columns = source.get("table_columns", DEFAULT_TARGET_COLUMNS)
    mixed_table = is_mixed(table_columns)
    table = (load_table(source["table"], dict(enumerated),
                        resource_path(source).name, table_columns,
                        allowed_systems={t["system"]
                                         for t in source["targets"]})
             if "table" in source else None)

    outcomes = []
    for code, display in enumerated:
        outcomes.append((code, display,
                         _resolve_code(source, code, built, observed,
                                       table, mixed_table)))
    return outcomes


def _resolve_code(source, code, built, observed, table, mixed_table):
    primary = source["targets"][0]
    if source.get("identity"):
        # Already standard terminology: the code is its own target, so there
        # is nothing to look up and no release to pin.
        return {"kind": MAPPED, "target_system": primary["system"],
                "target_code": code, "target_display": "",
                "target_version": None, "equivalence": "equivalent",
                "comment": ""}
    if table is not None:
        row = table.get(code)
        if row is None:
            # No row. Which backlog this is depends on whether any data
            # anywhere carries the code — a fact the occurrence artifact
            # settles and nothing else can.
            if observed is not None and (source["system"], code) not in observed:
                return {"kind": NOT_OBSERVED,
                        "expected_code": "",
                        "expected_system": primary["system"],
                        "comment": (
                            "Recorded on no bound element in the warehouse "
                            "extract the committed occurrence counts describe. "
                            "Deliberately not asked rather than declined: the "
                            "mapping tables are generated over the codes the "
                            "warehouse actually uses, and this one has never "
                            "been used. If you are translating it, that "
                            "assumption does not hold for your data — extend "
                            "the table's generation population.")}
            return {"kind": "no-row-in-curated-table",
                    "expected_code": "",
                    "expected_system": primary["system"],
                    "comment": (
                        f"Not considered yet. The committed mapping table for "
                        f"{resource_path(source).stem} has no row for this "
                        f"code. Nothing was searched for and no target was "
                        f"declined — this is a backlog, not a finding that no "
                        f"{primary['system']} concept exists. Extending the "
                        f"table's generation population is what fills it.")}
        if not row["target_code"]:
            # Considered and deliberately not mapped. The row's own comment is
            # the reason.
            return {"kind": "no-suitable-concept",
                    "expected_code": "",
                    "expected_system": primary["system"],
                    "comment": row["comment"]}
        # No release pinned: the systems tables map into are all on
        # UNVERSIONED_SYSTEMS. `relatedto` is set here rather than carried in
        # the table, so it holds for every table equally and cannot drift as
        # one generator's rule is edited.
        return {"kind": MAPPED,
                "target_system": (row["target_system"] if mixed_table
                                  else primary["system"]),
                "target_code": row["target_code"],
                "target_display": row["target_display"],
                "target_version": None, "equivalence": "relatedto",
                "comment": row["comment"]}
    for tgt in source["targets"]:
        if tgt["rule"] is None:
            # A stream with no table, no identity and no notation rule has no
            # way to resolve anything. Stopping here is the only outcome that
            # neither lies nor loses the code.
            sys.exit(
                f"  {source['system']} enumerates {code!r}, but the stream "
                f"declares no resolver: no table, no identity, and target "
                f"{tgt['system']} has no notation rule. Build the stream for "
                f"this population, or give it a table — do not widen the rule "
                f"to make the build pass.")
        official = tgt["rule"](code)
        found = find(built, tgt, official)
        if found:
            version, display = found
            return {"kind": MAPPED, "target_system": tgt["system"],
                    "target_code": official, "target_display": display,
                    "target_version": version, "equivalence": "equivalent",
                    "comment": ""}
    return {"kind": "absent-from-all-built-releases",
            "expected_code": primary["rule"](code),
            "expected_system": primary["system"],
            "comment": ""}


def unmapped_row(source, code, display, outcome):
    """One worklist row, shared by the field CSVs' successor (the per-stream
    worklists) and the map's own `unmatched` elements."""
    return {
        "stream": source.get("stream", ""),
        "source_system": source["system"],
        "mimic_code": code,
        "mimic_display": display,
        "expected_code": outcome.get("expected_code", ""),
        # The system that WOULD have been searched, not the source's own:
        # `X -> X unmatched` would read as "we looked in the source system and
        # found nothing", which is nonsense.
        "expected_system": outcome["expected_system"],
        "reason": outcome["kind"],
        "comment": outcome.get("comment", ""),
    }


def build_groups(sources, built, observed):
    """Resolve every stream, returning (groups, unmapped rows).

    Groups are keyed by (source system, target system, target version) because
    group.targetVersion is the only place R4 records a target release. Streams
    sharing a (source, target) pair merge into one R4 group by design — the two
    LOINC identity populations land in ONE group — which is why per-stream
    numbers cannot be read back out of a finished map and live in the stream
    reports instead (build_stream_reports.py).
    """
    buckets = defaultdict(list)
    unmapped = []

    for source in sources:
        outcomes = resolve_source(source, built, observed)
        hits = 0
        for code, display, outcome in outcomes:
            if outcome["kind"] == MAPPED:
                buckets[(source["system"], outcome["target_system"],
                         outcome["target_version"])].append(
                    (code, display, outcome["target_code"],
                     outcome["target_display"], outcome["equivalence"],
                     outcome["comment"]))
                hits += 1
            else:
                unmapped.append(unmapped_row(source, code, display, outcome))
        print(f"  {source.get('stream', resource_path(source).stem):45s} "
              f"{hits:>6,}/{len(outcomes):<6,} mapped", file=sys.stderr)

    groups = []
    # `version or ""` only to keep None sortable against the release strings;
    # the None-versioned groups are the identity and table ones.
    for key in sorted(buckets, key=lambda k: (k[0], k[1], k[2] or "")):
        source_system, target_system, version = key
        elements = []
        for (code, mimic_display, official, display, equivalence,
             comment) in sorted(buckets[key], key=lambda r: r[0]):
            element = {"code": code}
            if mimic_display:
                element["display"] = mimic_display
            # Two equivalences are emitted, and which one a mapping gets is
            # decided by its RESOLVER, not per row:
            #
            #   equivalent  identity and notation mappings. The target is the
            #               same concept as the source — either literally the
            #               same code, or the same code written in the official
            #               notation (ICD dot placement, see lib/notation.py).
            #               Nothing about the meaning changes, so this is a
            #               fact about spelling and not a judgement.
            #   relatedto   every curated-table mapping. A MIMIC flowsheet
            #               label or antibiotic name and a SNOMED/LOINC concept
            #               are related, and this repo does not claim to know
            #               the direction. The row's `comment` says what the
            #               mapping rests on, in prose, where a reader can
            #               weigh it.
            #
            # `relatedto` is deliberately flat: an earlier version derived
            # `wider`/`narrower`/`equivalent` per row from the label and the
            # target's designations. Direction is not something a lexical
            # comparison can establish, so the claims were confident where the
            # evidence was not, and each exception needed a hand-written
            # override to walk one back. Consumers that filter on direction
            # will drop these rows — the right outcome for a relationship we do
            # not assert, and better than picking a direction to survive a
            # filter.
            #
            # Never `equal`, which reads better for an identity mapping but is
            # filtered out by consumers that pin the equivalence their
            # translate() accepts.
            concept = {"code": official, "equivalence": equivalence}
            if display:
                concept["display"] = display
            if comment:
                concept["comment"] = comment
            element["target"] = [concept]
            elements.append(element)
        group = {"source": source_system, "target": target_system}
        if version:
            group["targetVersion"] = version
        group["element"] = elements
        groups.append(group)
    return groups, unmapped


def unmatched_groups(unmapped):
    """Codes we looked at and deliberately did NOT map, as R4 `unmatched`.

    Recorded in the map itself so "considered, no target exists" is a
    machine-readable fact rather than only a line in a CSV. One group per
    (source system, system we searched), carrying the searched system as
    group.target but no targetVersion — the code is absent from every built
    release, so no single version is the right one to name. The elements carry
    equivalence `unmatched` and no target.code, which is precisely how R4 says
    to spell "looked, found nothing".

    group.target is required even though R4 itself allows a target-less group:
    Ontoserver rejects the write with `business-rule: ConceptMap.group.target
    is required` because its fallback is to infer the system from
    targetCanonical, and our target ValueSet spans several systems.

    NOT ConceptMap.group.unmapped — that element is a fallback *rule*, not a
    list. Its only plausible mode here, `provided`, would echo the source code
    back as though it were a valid code in the target system, so $translate
    would return a fabricated answer instead of reporting no match. A silent
    wrong answer is worse than a reported gap.
    """
    by_source = defaultdict(list)
    for row in unmapped:
        by_source[(row["source_system"], row["expected_system"])].append(row)

    groups = []
    for source_system, expected_system in sorted(by_source):
        elements = []
        for row in sorted(by_source[(source_system, expected_system)],
                          key=lambda r: r["mimic_code"]):
            element = {"code": row["mimic_code"]}
            if row["mimic_display"]:
                element["display"] = row["mimic_display"]
            # A table row carries its own reason. The generated wording below
            # names an expected code that was searched for and missed, which is
            # not what happened to a code the generator declined to map.
            element["target"] = [{
                "equivalence": "unmatched",
                "comment": row.get("comment") or (
                    f"No {row['expected_system']} concept for the "
                    f"expected code {row['expected_code']} in any built "
                    f"release. Reason: {row['reason']}."),
            }]
            elements.append(element)
        groups.append({"source": source_system, "target": expected_system,
                       "element": elements})
    return groups
