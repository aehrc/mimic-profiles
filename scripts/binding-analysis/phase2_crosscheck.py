#!/usr/bin/env python3
"""Phase 2 / step 3: offline coverage cross-check of observed MIMIC codes vs the IG ValueSets.

Stdlib only. Reads the built IG package (output/package.tgz) via tarfile (no extraction),
resolves ValueSet membership offline, and produces:
  - scripts/binding-analysis/binding-report.json  (machine-readable)
  - scripts/binding-analysis/binding-report.md     (human review)
"""
import json
import os
import re
import tarfile
from collections import defaultdict

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
BA = os.path.join(REPO, "scripts", "binding-analysis")
DISTINCT = os.path.join(BA, "distinct-codes.ndjson")
SUMMARY = os.path.join(BA, "extract-summary.json")
WORKITEMS = os.path.join(BA, "work-items.json")
PKG = os.path.join(REPO, "output", "package.tgz")
ALIASES = os.path.join(REPO, "input", "fsh", "AL_ValueSets.fsh")
OUT_JSON = os.path.join(BA, "binding-report.json")
OUT_MD = os.path.join(BA, "binding-report.md")

MIMIC_PREFIX = "http://mimic.mit.edu/fhir/mimic/"


# ---------------------------------------------------------------------------
# Load package: CodeSystems and ValueSets
# ---------------------------------------------------------------------------
def collect_concept_codes(concepts):
    """Recursively collect codes including nested concept.concept children."""
    codes = set()
    for c in concepts or []:
        if "code" in c:
            codes.add(c["code"])
        if c.get("concept"):
            codes |= collect_concept_codes(c["concept"])
    return codes


def load_package():
    codesystems = {}   # url -> set(codes)
    valuesets = {}     # url -> raw json
    with tarfile.open(PKG, "r:gz") as t:
        for m in t.getmembers():
            n = m.name
            base = os.path.basename(n)
            if not (base.startswith("ValueSet-") or base.startswith("CodeSystem-")):
                continue
            d = json.load(t.extractfile(m))
            rt = d.get("resourceType")
            url = d.get("url")
            if rt == "CodeSystem" and url:
                codesystems[url] = collect_concept_codes(d.get("concept"))
            elif rt == "ValueSet" and url:
                valuesets[url] = d
    return codesystems, valuesets


def resolve_valuesets(codesystems, valuesets):
    """Return url -> {systems:set, members:{system:set(codes)|None}, partial:bool}.

    members[system] == None  -> whole system included but CS not in package (unknown offline)
    """
    resolved = {}
    for url, vs in valuesets.items():
        systems = set()
        members = {}          # system -> set of codes (or None if unknown)
        partial = False
        include = vs.get("compose", {}).get("include", [])
        for inc in include:
            sys = inc.get("system")
            if not sys:
                continue  # value-set-references not used by MIMIC VSs; ignore
            systems.add(sys)
            if "concept" in inc:
                codes = {c["code"] for c in inc["concept"] if "code" in c}
                members.setdefault(sys, set())
                if members[sys] is not None:
                    members[sys] |= codes
            else:
                # whole system
                if sys in codesystems:
                    members[sys] = set(codesystems[sys])
                else:
                    members[sys] = None
                    partial = True
        resolved[url] = {"systems": systems, "members": members, "partial": partial}
    return resolved


# ---------------------------------------------------------------------------
# Aliases: canonical URL -> $Alias
# ---------------------------------------------------------------------------
def load_aliases():
    url_to_alias = {}
    pat = re.compile(r"^Alias:\s*\$(\S+)\s*=\s*(\S+)\s*$")
    for line in open(ALIASES):
        m = pat.match(line.strip())
        if m:
            name, url = m.group(1), m.group(2)
            url_to_alias.setdefault(url, name)  # first wins
    return url_to_alias


# ---------------------------------------------------------------------------
# Observed codes per (profile_id, element_id)
# ---------------------------------------------------------------------------
def load_observed():
    obs = defaultdict(list)  # key -> list of rows
    for line in open(DISTINCT):
        line = line.strip()
        if not line:
            continue
        r = json.loads(line)
        obs[(r["profile_id"], r["element_id"])].append(r)
    return obs


# ---------------------------------------------------------------------------
# Coverage of an element's observed codes against a resolved ValueSet
# ---------------------------------------------------------------------------
def compute_coverage(rows, vs_res):
    """Return dict with distinct/row coverage and missing rows for one VS."""
    total_distinct = len(rows)
    total_rows = sum(r["n"] for r in rows)
    covered_distinct = 0
    covered_rows = 0
    unknown_distinct = 0
    unknown_rows = 0
    missing = []
    for r in rows:
        sys, code, n = r["system"], r["code"], r["n"]
        mem = vs_res["members"].get(sys, set())
        if mem is None:
            unknown_distinct += 1
            unknown_rows += n
            continue
        if code in mem:
            covered_distinct += 1
            covered_rows += n
        else:
            missing.append(r)
    return {
        "total_distinct": total_distinct,
        "total_rows": total_rows,
        "covered_distinct": covered_distinct,
        "covered_rows": covered_rows,
        "unknown_distinct": unknown_distinct,
        "unknown_rows": unknown_rows,
        "pct_distinct": (covered_distinct / total_distinct * 100) if total_distinct else 0.0,
        "pct_rows": (covered_rows / total_rows * 100) if total_rows else 0.0,
        "missing": sorted(missing, key=lambda r: -r["n"]),
    }


# ---------------------------------------------------------------------------
# FSH element path
# ---------------------------------------------------------------------------
def fsh_path(element_id, resource_type):
    # strip "ResourceType." prefix
    p = element_id
    if p.startswith(resource_type + "."):
        p = p[len(resource_type) + 1:]
    return p


# External-terminology suggestions for known HL7 systems
EXTERNAL_VS_SUGGEST = {
    "http://terminology.hl7.org/CodeSystem/v3-ActPriority":
        "http://terminology.hl7.org/ValueSet/v3-ActPriority",
    "http://terminology.hl7.org/CodeSystem/v3-ObservationInterpretation":
        "http://hl7.org/fhir/ValueSet/observation-interpretation",
    "http://terminology.hl7.org/CodeSystem/v3-NullFlavor":
        "http://terminology.hl7.org/ValueSet/v3-NullFlavor",
    "http://terminology.hl7.org/CodeSystem/organization-type":
        "http://hl7.org/fhir/ValueSet/organization-type",
    "http://terminology.hl7.org/CodeSystem/location-physical-type":
        "http://hl7.org/fhir/ValueSet/location-physical-type",
    "http://loinc.org":
        "(LOINC - external; validate against terminology server)",
}


def main():
    codesystems, valuesets = load_package()
    resolved = resolve_valuesets(codesystems, valuesets)
    url_to_alias = load_aliases()
    observed = load_observed()
    summary = json.load(open(SUMMARY))
    workitems = {(c["profile_id"], c["element_id"]): c
                 for c in json.load(open(WORKITEMS))["candidates"]}

    ok_items = [i for i in summary["items"] if i["status"] == "ok"]
    no_data_items = [i for i in summary["items"] if i["status"] == "no_data"]

    report_elements = []

    for item in ok_items:
        key = (item["profile_id"], item["element_id"])
        rows = observed.get(key, [])
        rtype = item["resource_type"]
        observed_systems = {r["system"] for r in rows}
        wi = workitems.get(key, {})
        efsh = fsh_path(item["element_id"], rtype)

        mimic_obs = {s for s in observed_systems if s.startswith(MIMIC_PREFIX)}
        external_obs = observed_systems - mimic_obs

        # Candidate VSs cover all *MIMIC* observed systems (external systems may
        # remain uncovered -> they show up as missing/unknown codes). This lets a
        # VS that covers the MIMIC codes but not a small external tail (e.g. a
        # stray v3-NullFlavor code) surface as a repair_candidate rather than
        # being hidden. If there are no MIMIC systems at all, require the VS to
        # cover all observed (external) systems so we still find enumerated-concept VSs.
        gate = mimic_obs if mimic_obs else observed_systems
        candidates = []
        for url, vs_res in resolved.items():
            if gate <= vs_res["systems"]:
                cov = compute_coverage(rows, vs_res)
                candidates.append({
                    "value_set": url,
                    "alias": url_to_alias.get(url),
                    "partial": vs_res["partial"],
                    "n_systems": len(vs_res["systems"]),
                    "coverage": cov,
                })
        # sort: highest row coverage, then highest distinct, then smallest VS
        candidates.sort(key=lambda c: (-c["coverage"]["pct_rows"],
                                       -c["coverage"]["pct_distinct"],
                                       c["n_systems"]))

        verdict = None
        fsh_line = None
        winning = candidates[0] if candidates else None
        other_full = []

        full_covers = [c for c in candidates
                       if c["coverage"]["pct_distinct"] >= 100.0
                       and c["coverage"]["unknown_distinct"] == 0]
        if full_covers:
            verdict = "bind"
            # prefer smallest covering VS
            full_covers.sort(key=lambda c: (c["n_systems"], c["value_set"]))
            winning = full_covers[0]
            other_full = [c["value_set"] for c in full_covers[1:]]
            if winning["alias"]:
                fsh_line = "* %s from $%s (required)" % (efsh, winning["alias"])
            else:
                fsh_line = "* %s from %s (required)" % (efsh, winning["value_set"])
        elif winning and winning["coverage"]["pct_rows"] >= 95.0 \
                and winning["coverage"]["unknown_rows"] == 0:
            verdict = "repair_candidate"
        else:
            # external_terminology only when observed systems are all non-MIMIC
            # AND their membership is unresolvable offline (no candidate can
            # actually resolve any observed code -- i.e. every observed code is
            # "unknown" in the best candidate, or there is no candidate at all).
            # If a candidate enumerates explicit external concepts (resolvable),
            # then coverage is real and the verdict is no_binding / repair.
            all_external = (not mimic_obs) and bool(external_obs)
            unresolvable = (winning is None) or \
                (winning["coverage"]["unknown_distinct"] ==
                 winning["coverage"]["total_distinct"])
            if all_external and unresolvable:
                verdict = "external_terminology"
            else:
                verdict = "no_binding"

        # for external_terminology, the "winning" package VS (if any) is not a
        # real candidate -- suppress it to avoid a misleading best-VS display.
        if verdict == "external_terminology":
            winning = None

        # external suggestions
        ext_suggestions = {}
        for s in external_obs:
            if s in EXTERNAL_VS_SUGGEST:
                ext_suggestions[s] = EXTERNAL_VS_SUGGEST[s]

        report_elements.append({
            "profile_id": item["profile_id"],
            "element_id": item["element_id"],
            "resource_type": rtype,
            "type": wi.get("type"),
            "fsh_element_path": efsh,
            "existing_binding": wi.get("existing_binding"),
            "distinct_count": item["distinct_count"],
            "row_count": item["row_count"],
            "observed_systems": sorted(observed_systems),
            "mimic_systems": sorted(mimic_obs),
            "external_systems": sorted(external_obs),
            "verdict": verdict,
            "recommended_fsh": fsh_line,
            "winning_value_set": winning["value_set"] if winning else None,
            "winning_alias": winning["alias"] if winning else None,
            "other_full_covering_value_sets": other_full,
            "external_vs_suggestions": ext_suggestions,
            "candidates": [
                {
                    "value_set": c["value_set"],
                    "alias": c["alias"],
                    "partial_resolvable": c["partial"],
                    "n_systems": c["n_systems"],
                    "pct_distinct": round(c["coverage"]["pct_distinct"], 2),
                    "pct_rows": round(c["coverage"]["pct_rows"], 4),
                    "covered_distinct": c["coverage"]["covered_distinct"],
                    "total_distinct": c["coverage"]["total_distinct"],
                    "covered_rows": c["coverage"]["covered_rows"],
                    "total_rows": c["coverage"]["total_rows"],
                    "unknown_distinct": c["coverage"]["unknown_distinct"],
                    "unknown_rows": c["coverage"]["unknown_rows"],
                }
                for c in candidates
            ],
            "missing_codes": [
                {"system": r["system"], "code": r["code"],
                 "display": r.get("display"), "n": r["n"]}
                for r in (winning["coverage"]["missing"] if winning else [])
            ],
        })

    report = {
        "generated_from": json.load(open(WORKITEMS)).get("generated_from"),
        "summary": {
            "total_items": summary["total_items"],
            "ok": summary["ok"],
            "no_data": summary["no_data"],
            "errors": summary["errors"],
        },
        "elements": report_elements,
        "no_data_elements": [
            {"profile_id": i["profile_id"], "element_id": i["element_id"]}
            for i in no_data_items
        ],
    }

    with open(OUT_JSON, "w") as f:
        json.dump(report, f, indent=2)

    write_md(report)
    print("Wrote", OUT_JSON)
    print("Wrote", OUT_MD)

    # brief console summary
    print("\nVERDICTS:")
    for e in report_elements:
        w = e["winning_value_set"] or "-"
        print("  [%-20s] %-40s %-18s best=%s" % (
            e["verdict"], e["element_id"], e["profile_id"],
            w.rsplit("/", 1)[-1] if w != "-" else "-"))


def write_md(report):
    L = []
    L.append("# Phase 2 / Step 3 - Binding Coverage Cross-Check\n")
    s = report["summary"]
    L.append("Offline coverage of observed MIMIC codes vs the IG's ValueSets "
             "(package.tgz). Stdlib-only, no terminology server.\n")
    L.append("Total candidate elements: %d | ok (populated): %d | no_data: %d | errors: %d\n"
             % (s["total_items"], s["ok"], s["no_data"], s["errors"]))

    # summary table
    L.append("## Summary\n")
    L.append("| Element | Profile | Verdict | Best VS | %dist | %rows | #missing |")
    L.append("|---|---|---|---|--:|--:|--:|")
    for e in report["elements"]:
        best = e["candidates"][0] if e["candidates"] else None
        bvs = (e["winning_value_set"] or "-")
        bvs = bvs.rsplit("/", 1)[-1] if bvs != "-" else "-"
        pd = "%.1f" % best["pct_distinct"] if best else "-"
        pr = "%.2f" % best["pct_rows"] if best else "-"
        L.append("| %s | %s | %s | %s | %s | %s | %d |" % (
            e["element_id"], e["profile_id"], e["verdict"], bvs, pd, pr,
            len(e["missing_codes"])))
    L.append("")

    for e in report["elements"]:
        L.append("## %s  (`%s`)\n" % (e["element_id"], e["profile_id"]))
        L.append("- **Verdict:** `%s`" % e["verdict"])
        L.append("- **Type:** %s | distinct=%d, rows=%d" %
                 (e.get("type"), e["distinct_count"], e["row_count"]))
        if e["existing_binding"]:
            eb = e["existing_binding"]
            L.append("- **Existing binding:** %s / %s" %
                     (eb.get("strength"), eb.get("value_set")))
        L.append("- **Observed systems:** %s" % ", ".join(e["observed_systems"]))
        if e["external_systems"]:
            L.append("- **External (non-MIMIC) systems:** %s" %
                     ", ".join(e["external_systems"]))
        if e["external_vs_suggestions"]:
            for sys, vs in e["external_vs_suggestions"].items():
                L.append("  - suggest for `%s` -> `%s`" % (sys, vs))
        if e["recommended_fsh"]:
            L.append("- **Recommended FSH:**\n  ```fsh\n  %s\n  ```" % e["recommended_fsh"])
        if e["other_full_covering_value_sets"]:
            L.append("- Other fully-covering VSs: %s" %
                     ", ".join(e["other_full_covering_value_sets"]))

        if e["candidates"]:
            L.append("\n**Candidate ValueSets** (systems superset of observed):\n")
            L.append("| ValueSet | alias | %dist | %rows | dist cov | row cov | unknown | partial |")
            L.append("|---|---|--:|--:|--:|--:|--:|:-:|")
            for c in e["candidates"][:15]:
                L.append("| %s | %s | %.1f | %.2f | %d/%d | %d/%d | %d | %s |" % (
                    c["value_set"].rsplit("/", 1)[-1],
                    ("$" + c["alias"]) if c["alias"] else "-",
                    c["pct_distinct"], c["pct_rows"],
                    c["covered_distinct"], c["total_distinct"],
                    c["covered_rows"], c["total_rows"],
                    c["unknown_distinct"],
                    "yes" if c["partial_resolvable"] else "no"))
        else:
            L.append("\n_No package ValueSet covers all observed systems._")

        if e["missing_codes"]:
            L.append("\n**Missing codes** (top 20 by n; full list in JSON):\n")
            L.append("| system | code | display | n |")
            L.append("|---|---|---|--:|")
            for m in e["missing_codes"][:20]:
                disp = (m["display"] or "").replace("|", "/")
                L.append("| %s | %s | %s | %d |" % (
                    m["system"].rsplit("/", 1)[-1], m["code"], disp, m["n"]))
            if len(e["missing_codes"]) > 20:
                L.append("\n_... %d more missing codes in JSON._" %
                         (len(e["missing_codes"]) - 20))
        L.append("")

    L.append("## no_data elements (%d)\n" % len(report["no_data_elements"]))
    L.append("These candidate elements had zero rows in MIMIC; carried forward as their own bucket.\n")
    for i in report["no_data_elements"]:
        L.append("- `%s` (%s)" % (i["element_id"], i["profile_id"]))
    L.append("")

    with open(OUT_MD, "w") as f:
        f.write("\n".join(L))


if __name__ == "__main__":
    main()
