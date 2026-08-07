"""Resolving a declaration into ConceptMap groups.

A builder declares `sources`; this turns them into R4 groups plus the list of
codes nothing could map. Three resolver shapes are supported, and a source picks
exactly one:

  notation  `targets` is an ordered list of target(); the first that resolves
            wins, later entries are the cross-system fallback.
  identity  `identity: True`; the code is already standard terminology and maps
            to itself.
  table     `table` names a committed CSV; the mapping is data, see curated.py.
            Single-target by default. A table declaring MIXED_TARGET_COLUMNS
            names its target system per row instead, and then one source spans
            one group per system it named — which is how the chartevents stream
            reaches LOINC where LOINC answers and SNOMED CT where it does not.

The resolver also fixes the equivalence: `equivalent` for notation and identity,
`relatedto` for every table row. See build_groups for why it is a property of
the resolver rather than of the row.

Nothing downstream re-derives a mapping. The builders write a ConceptMap, and
the ValueSet projection, the verifier and every consumer read that.
"""

import sys
from collections import Counter, defaultdict

from .built import find
from .curated import DEFAULT_TARGET_COLUMNS, is_mixed, load_table
from .igsource import partition_observed, resource_path, source_concepts

# The reason recorded for a code that is in the bound ValueSet but that the
# warehouse never puts on this element. It is deliberately NOT one of the
# resolver's failure reasons: nothing was searched for and nothing was
# declined, so folding it in with them would inflate every "we tried and
# failed" number in the statistics. See igsource.partition_observed.
NOT_OBSERVED = "not-observed-in-data"

Target = dict  # {system, rule, kind, predicate}


def target(system, rule, kind=None, predicate=None):
    """One candidate target system for a source.

    `rule` rewrites the MIMIC code into the target's notation. `kind` filters on
    the built CodeSystem's `kind` property, which is how ICD-9-CM diagnoses
    (Vol 1-2) and procedures (Vol 3) are told apart — THO gives them the same
    canonical URL, so a Coding cannot distinguish them. `predicate` rejects codes
    that exist but are not selectable, e.g. PCS groupers.
    """
    return {"system": system, "rule": rule, "kind": kind, "predicate": predicate}


def build_groups(sources, element, built):
    """Resolve every MIMIC code, returning (groups, unmapped rows, streams).

    Groups are keyed by (source system, target system, target version) because
    group.targetVersion is the only place R4 records a target release.

    `streams` is the per-SOURCES-entry tally, collected here because this loop
    is the only place stream identity still exists: the finished map merges
    populations into shared (source, target) groups — the two LOINC identity
    populations land in ONE R4 group by design — so reading per-stream numbers
    back out of the map is impossible. One entry per source, in declaration
    order, keyed by the IG resource the codes came from. See lib/stats.py.
    """
    buckets = defaultdict(list)
    unmapped = []
    streams = []

    for source in sources:
        concepts = list(source_concepts(source))
        enumerated_total = len(concepts)
        # A code in the bound ValueSet that the data never carries is DECLARED,
        # not dropped: it gets an `unmatched` element and a CSV row exactly like
        # a resolver failure, so a consumer translating one is told the
        # assumption out loud instead of getting silence. It is only kept out of
        # this stream's coverage arithmetic below.
        concepts, never_observed = partition_observed(source, element, concepts)
        for code, display in never_observed:
            unmapped.append({
                "field": element, "source_system": source["system"],
                "mimic_code": code, "mimic_display": display,
                # The system that WOULD have been searched, not the source's
                # own: `X -> X  unmatched` would read as "we looked in the
                # source system and found nothing", which is nonsense. This
                # also merges these into the one unmatched group per (source,
                # searched system), where the per-element comment and the CSV's
                # `reason` column are what tell the two kinds of gap apart.
                "expected_code": "",
                "expected_system": source["targets"][0]["system"],
                "reason": NOT_OBSERVED,
                "comment": (
                    f"In {resource_path(source).stem}, which {element} is bound "
                    f"to, but never recorded on {element} in the warehouse "
                    f"extract this map was built against. Deliberately not "
                    f"mapped rather than not considered: if you are translating "
                    f"this code, the assumption it was left out under does not "
                    f"hold for your data."),
            })
        hits = 0
        unmapped_before = len(unmapped)
        target_systems = set()
        by_equivalence = Counter()
        # `table_columns` names the target pair as this table spells it; the
        # rows come back keyed `target_code` / `target_display` either way. A
        # mixed-target table names a THIRD column, `target_system`, and its rows
        # additionally come back keyed `target_system` — see curated.py.
        table_columns = source.get("table_columns", DEFAULT_TARGET_COLUMNS)
        mixed_table = is_mixed(table_columns)
        table = (load_table(source["table"], dict(concepts),
                            resource_path(source).name, table_columns,
                            allowed_systems={t["system"]
                                             for t in source["targets"]})
                 if "table" in source else None)

        for code, mimic_display in concepts:
            if source.get("identity"):
                # Already standard terminology: the code is its own target, so
                # there is nothing to look up and no release to pin. Version
                # None -> the group is emitted without targetVersion.
                tgt = source["targets"][0]
                buckets[(source["system"], tgt["system"], None)].append(
                    (code, mimic_display, code, mimic_display,
                     "equivalent", ""))
                hits += 1
                target_systems.add(tgt["system"])
                by_equivalence["equivalent"] += 1
                continue
            if table is not None:
                # The system an UNMAPPED row is reported against. For a
                # single-target table that is the only system there is; for a
                # mixed one it is the system asked FIRST, which is what the
                # declining comment on the row is phrased against. A row that
                # declined was refused by every space the generator tried, so no
                # single system is the whole truth — naming the primary keeps
                # the unmatched elements in one group and leaves the row's own
                # comment to say what was actually searched.
                tgt = source["targets"][0]
                row = table.get(code)
                if row is None:
                    unmapped.append({
                        "field": element,
                        "source_system": source["system"],
                        "mimic_code": code,
                        "mimic_display": mimic_display,
                        "expected_code": "",
                        "expected_system": tgt["system"],
                        "reason": "no-row-in-curated-table",
                    })
                elif not row["target_code"]:
                    # Considered and deliberately not mapped. The row's own
                    # comment is the reason; unmatched_groups prefers it over
                    # the generated "absent from every release" wording, which
                    # would be a lie here — nothing was searched for.
                    unmapped.append({
                        "field": element,
                        "source_system": source["system"],
                        "mimic_code": code,
                        "mimic_display": mimic_display,
                        "expected_code": "",
                        "expected_system": tgt["system"],
                        "reason": "no-suitable-concept",
                        "comment": row["comment"],
                    })
                else:
                    # No release pinned: both SNOMED and LOINC, the two systems
                    # tables target, are on UNVERSIONED_SYSTEMS.
                    #
                    # `relatedto` is set here rather than carried in the table,
                    # so it holds for every table equally and cannot drift as
                    # one generator's rule is edited. The tables have no
                    # equivalence column to carry — see lib/curated.py.
                    #
                    # A mixed-target table decides the target system PER ROW, so
                    # one stream fans out across as many groups as it named
                    # systems — a group is keyed by (source, target, version),
                    # and load_table has already checked every row's system is
                    # one this source declared.
                    mapped_system = (row["target_system"] if mixed_table
                                     else tgt["system"])
                    buckets[(source["system"], mapped_system, None)].append(
                        (code, mimic_display, row["target_code"],
                         row["target_display"], "relatedto",
                         row["comment"]))
                    hits += 1
                    target_systems.add(mapped_system)
                    by_equivalence["relatedto"] += 1
                continue
            for tgt in source["targets"]:
                official = tgt["rule"](code)
                found = find(built, tgt, official)
                if found:
                    version, display = found
                    buckets[(source["system"], tgt["system"], version)].append(
                        (code, mimic_display, official, display,
                         "equivalent", ""))
                    hits += 1
                    target_systems.add(tgt["system"])
                    by_equivalence["equivalent"] += 1
                    break
            else:
                primary = source["targets"][0]
                unmapped.append({
                    "field": element,
                    "source_system": source["system"],
                    "mimic_code": code,
                    "mimic_display": mimic_display,
                    "expected_code": primary["rule"](code),
                    "expected_system": primary["system"],
                    "reason": "absent-from-all-built-releases",
                })

        print(f"  {resource_path(source).name:45s} "
              f"{hits:>6,}/{len(concepts):<6,} mapped", file=sys.stderr)

        missed = unmapped[unmapped_before:]
        by_equivalence["unmatched"] = len(missed)
        streams.append({
            # The IG resource id, which is the name a stream is invoked by:
            # ValueSet-mimic-observation-type-ed.json -> mimic-observation-type-ed
            "stream": resource_path(source).stem.split("-", 1)[1],
            # The same resource, un-abbreviated. Stripping the prefix above is
            # not invertible — mimic-microbiology-antibiotic exists as BOTH a
            # CodeSystem and a ValueSet, and only the CodeSystem enumerates
            # anything — so anything needing this stream's code list reads the
            # file named here rather than guessing at the prefix. That is how
            # common/occurrences.py attaches occurrence counts to streams.
            "source_file": resource_path(source).name,
            "source_system": source["system"],
            "method": ("identity" if source.get("identity")
                       else "table" if "table" in source else "notation"),
            "total": len(concepts),
            "mapped": hits,
            "unmapped": len(missed),
            # Over the population the stream SET OUT to map. For an
            # observed_only stream that is the observed subset, and the two
            # keys below say so — reporting 2,888 mapped out of a 9,971-code
            # enumeration would describe a job nobody attempted, while hiding
            # the narrowing entirely would be worse. Both numbers, always.
            "coverage_pct": round(100 * hits / len(concepts), 1)
                            if concepts else 0.0,
            # Only for a stream that narrowed itself, so a report for a field
            # that did not stays byte-identical. See RESTRICTION_COLUMNS.
            **({"restriction": "observed-only",
                "enumerated_total": enumerated_total,
                "not_observed": len(never_observed)}
               if source.get("observed_only") else {}),
            # Free prose a stream declares about its own numbers, surfaced as a
            # footnote by build_statistics.py. For the case where a coverage
            # figure is correct but reads as a failure without context — see the
            # poe-iv entry in build_medication_cm_vs.py. Declared next to the
            # SOURCES entry it describes, so it cannot drift from the stream.
            # Declares that this stream's gaps are NOT a terminology judgement:
            # the obstacle is upstream, so common/occurrences.py buckets them
            # apart from `declined` and the element reports its coverage both
            # with and without them. Costs nothing when absent.
            **({"blocked_upstream": True}
               if source.get("blocked_upstream") else {}),
            **({"note": source["note"]} if source.get("note") else {}),
            **({"note_url": source["note_url"]}
               if source.get("note_url") else {}),
            "target_systems": sorted(target_systems),
            "by_equivalence": dict(sorted(by_equivalence.items())),
            "unmapped_by_reason": dict(sorted(Counter(
                r["reason"] for r in missed).items())),
        })

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
    return groups, unmapped, streams


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
