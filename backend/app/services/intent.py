"""Question-intent classification — routes the answerer to a slimmer prompt.

The full answerer system prompt is ~24K chars of rules accumulated one
incident at a time, and it has a demonstrated failure mode: the model
misses instructions buried in the wall (the §4.5 summary section was
ignored on its first deploy). Routing by intent lets each question type
carry only the sections that apply to it.

v1 is deliberately heuristic (surface patterns), not an LLM call:
  * "rules" is the default and composes the prompt EXACTLY as today —
    a misclassification into rules costs nothing.
  * "summary" / "meta" fire only on distinctive Hebrew question shapes,
    the same shapes their prompt sections were written for.

The classified intent is logged and stored in retrieval_debug so we can
measure hit rates and graduate to an LLM-assisted classifier if the
heuristics prove too coarse.
"""

# Document-overview questions — the §4.5 flow. Ordered longest-first only
# for readability; matching is substring-based.
_SUMMARY_PATTERNS = (
    "מה מסופר",
    "מה מתואר",
    "תסכם",
    "סכם לי",
    "תקציר של",
    "סיכום של",
    "על מה דנו",
    "על מה דובר",
    "אילו נושאים",
    "מה סדר היום",
    "במה עוסק",
    "במה עסק",
)

# Corpus-meta questions — answered from the injected stats block, not from
# retrieved chunks.
_META_PATTERNS = (
    "כמה מסמכים",
    "כמה פרוטוקולים",
    "כמה החלטות",
    "כמה תקנונים",
    "המסמך העדכני",
    "המסמך האחרון",
    "הפרוטוקול האחרון",
    "ההחלטה האחרונה",
    "אילו מסמכים יש",
    "אילו תקנונים קיימים",
    "אילו תקנונים יש",
    "מתי הופק",
    "מתי נקלט",
)


def classify_intent(question: str) -> str:
    """Return "rules" | "summary" | "meta" for a user question.

    A question that names a specific section (סעיף) is always rules —
    "מה כתוב בסעיף 4" asks for the rule, not a document overview, even
    though it surface-matches a summary shape.
    """
    q = (question or "").strip()
    if not q:
        return "rules"
    if "סעיף" in q:
        return "rules"
    for p in _META_PATTERNS:
        if p in q:
            return "meta"
    for p in _SUMMARY_PATTERNS:
        if p in q:
            return "summary"
    return "rules"
