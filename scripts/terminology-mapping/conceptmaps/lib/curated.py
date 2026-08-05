"""Loading a mapping table — the populations no rule can derive.

Some populations cannot be derived by rule. The ICU d_items displays are
flowsheet labels rather than clinical terms: '225461 Pelvis' is an X-ray series,
not a body structure; '224276 16 Gauge' is a peripheral cannula insertion;
'MAC', 'AVA', 'RIC' and 'EKOS' are local device acronyms. Any string matcher
answers all four confidently and wrongly, which is the same failure mode as
`unmapped: provided` and the PCS grouper collision.

So the mapping is data. The table itself is generated — see
build_d_items_table.py and build_micro_susc_table.py, which derive it from a
code-search service and gate every target against a terminology server.
Determinism comes from that table being committed: a build reads a file, never a
network service or a SNOMED release that moves under it.

One generator per stream, and therefore one table per stream: each needs its own
search constraint and its own context template, and a single file spanning
several of them would be unreviewable. What they share is this loader and the
shape it enforces.

A table is the one thing that names source codes, which the builders never do.
What replaces that guarantee is checking it against the IG rather than trusting
it — see load_table.
"""

import csv
import sys

# A table carries NO equivalence column, by design. Every mapping it supplies is
# `relatedto`, and assemble.build_groups sets that when it builds the group, so
# it holds for all tables equally and cannot drift as one generator is edited.
#
# The column existed, holding a per-row `equivalent`/`wider`/`narrower` derived
# by each generator from the label and the target's designations. Direction is
# not something a lexical comparison can establish, so the claims came out
# confident where the evidence was not, and each exception needed a hand-written
# override to walk one back. What a reader of one of these rows actually needs
# survives in `comment` — prose, not a claim a consumer will filter on.

# The target column pair a table uses when it does not say otherwise.
#
# Only these two column NAMES vary between tables; the other four do not. A
# table that maps into LOINC but calls its target column `snomed_code` is a
# committed file that lies about itself, and these tables are meant to be
# readable without running the generator that wrote them. So a source may
# declare `table_columns`, and load_table normalises whatever it finds to the
# terminology-agnostic keys `target_code` / `target_display`. That is what
# assemble.build_groups reads, so nothing downstream of here has to know which
# terminology a given table aims at.
DEFAULT_TARGET_COLUMNS = ("snomed_code", "snomed_display")


def curated_columns(target_columns=DEFAULT_TARGET_COLUMNS):
    """The five columns a builder reads, for a table with these target names.

    A generator may emit any number of extra provenance columns after these —
    they are read and discarded here, which is what lets build_d_items_table.py
    record the `codesearch_*` detail in the committed file at no cost to the
    build.
    """
    code, display = target_columns
    return ["mimic_code", "mimic_display", code, display, "comment"]


# The default layout, as a constant because build_d_items_table.py writes a
# SNOMED table and reads this to lay out its header.
CURATED_COLUMNS = curated_columns()


def load_table(path, expected, expected_name,
               target_columns=DEFAULT_TARGET_COLUMNS):
    """code -> row, validated against the IG's own enumeration.

    `expected` is {code: display} from igsource.source_concepts. A row naming a
    code the IG does not have is fatal, and a row whose display has drifted from
    the IG's is fatal too — an item that got relabelled upstream is exactly one a
    human should look at again. A code with no row is NOT fatal; it flows to the
    unmapped CSV as an ordinary gap in the worklist.

    NOTE for when tables become field-agnostic (keyed by source CodeSystem and
    target system rather than by field): the "not in `expected`" check has to
    move from the bound ValueSet to the CodeSystem, because a shared table
    legitimately carries rows for codes this population's ValueSet does not
    include. Staleness detection survives that move — a relabelled or deleted
    itemid still fails — but the check as written here would reject every row
    belonging to a sibling population.
    """
    if not path.is_file():
        sys.exit(f"  {path} not found — this population has no rule to fall "
                 f"back on, and building without it would silently drop every "
                 f"code in it.")

    columns = curated_columns(target_columns)
    code_column, display_column = target_columns

    rows = {}
    with open(path, newline="") as fh:
        reader = csv.DictReader(fh)
        missing = set(columns) - set(reader.fieldnames or [])
        if missing:
            sys.exit(f"  {path.name}: missing column(s) {sorted(missing)}")
        for line, row in enumerate(reader, start=2):
            row = {k: (v or "").strip() for k, v in row.items()
                   if k in columns}
            # Renamed rather than aliased, so a row cannot be read through both
            # its file name and the internal one and disagree with itself.
            row["target_code"] = row.pop(code_column)
            row["target_display"] = row.pop(display_column)
            code = row["mimic_code"]
            where = f"  {path.name}:{line} ({code})"
            if not code:
                sys.exit(f"{where}: blank mimic_code")
            if code in rows:
                sys.exit(f"{where}: duplicate mimic_code")
            if code not in expected:
                sys.exit(f"{where}: not in {expected_name}. The IG no longer "
                         f"has this code — delete the row.")
            if row["mimic_display"] != expected[code]:
                sys.exit(f"{where}: display drifted. Table says "
                         f"{row['mimic_display']!r}, the IG says "
                         f"{expected[code]!r}. Re-check the mapping, then "
                         f"update the row.")
            # Errors name the column as it is spelled in THIS file, not the
            # internal key, so the message points at something the reader can
            # find in the CSV they are looking at.
            if row["target_code"]:
                if not row["target_display"]:
                    sys.exit(f"{where}: {code_column} without {display_column}")
            elif not row["comment"]:
                # A blank target is a decision, so it has to carry its reason —
                # otherwise it is indistinguishable from an unfinished row.
                sys.exit(f"{where}: no {code_column} and no comment. A "
                         f"deliberate non-mapping must say why.")
            rows[code] = row
    return rows
