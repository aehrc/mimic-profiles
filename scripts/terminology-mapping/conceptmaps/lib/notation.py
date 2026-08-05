"""Dot insertion and code-shape predicates.

THE ONLY PLACE THESE RULES EXIST. Where the dot goes depends on BOTH the
revision and whether the code is a diagnosis or a procedure — which is why the
dot-less form alone can never tell you what it is. MIMIC stores every ICD code
dot-less, and the dot-less form is genuinely ambiguous: '4019' is both diagnosis
401.9 and procedure 40.19.

Both the diagnosis and the procedure builder target ICD-9-CM, so these live in
one module rather than in each builder. If you find yourself writing
`code[:3] + "." + code[3:]` anywhere else in this repo, that is the bug.
"""


def dot_icd10cm(code):
    """ICD-10-CM: dot after the 3rd character, only when longer than 3."""
    return code[:3] + "." + code[3:] if len(code) > 3 else code


def dot_icd9_diagnosis(code):
    """ICD-9-CM Vol 1-2: E-codes after the 4th (E8500 -> E850.0), numeric and
    V-codes after the 3rd (20500 -> 205.00)."""
    if code[:1] in ("E", "e"):
        return code[:4] + "." + code[4:] if len(code) > 4 else code
    return code[:3] + "." + code[3:] if len(code) > 3 else code


def dot_icd9_procedure(code):
    """ICD-9-CM Vol 3: two digits before the dot (3226 -> 32.26)."""
    return code[:2] + "." + code[2:] if len(code) > 2 else code


def no_dot(code):
    """ICD-10-PCS: seven characters, no dot, ever. Also the identity rule for
    codes that are already standard terminology."""
    return code


def is_pcs_leaf(code, props):
    """Only the 7-character leaves are real PCS codes; the 1/2/3/4-character
    tiers are navigational and carry notSelectable.

    Load-bearing: 64 of MIMIC's 2,544 ICD-9 procedure codes are verbatim valid
    4-character PCS body-part groupers. MIMIC procedure 0095 means ICD-9 00.95,
    but as a raw string it matches PCS 0095 'Subarachnoid Space, Intracranial'.
    """
    return len(code) == 7 and not props.get("notSelectable")


def concept_properties(concept):
    """Flatten CodeSystem.concept.property into a plain dict."""
    out = {}
    for prop in concept.get("property", []):
        for key in ("valueBoolean", "valueCode", "valueString"):
            if key in prop:
                out[prop["code"]] = prop[key]
                break
    return out
