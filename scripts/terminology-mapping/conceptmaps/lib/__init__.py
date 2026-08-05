"""Shared machinery for the per-population ConceptMap + ValueSet builders.

One builder script per bound element (see build_condition_cm_vs.py,
build_procedure_cm_vs.py). Each declares its own sources, resolvers and resource
metadata; everything executable lives here, so two builders cannot drift apart
on a rule they share. ICD-9-CM is a target of both the diagnosis and the
procedure map, which is exactly the duplication that once produced three
disagreeing copies of the dot-insertion rules.

What each builder owns: its `SOURCES` declaration and its `META`.
What this package owns: everything that computes, assembles or writes.
"""
