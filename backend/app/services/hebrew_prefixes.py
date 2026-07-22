"""Naive Hebrew prefix expansion — no NLP library, just a lookup table.

Hebrew nouns commonly appear with one-letter prefixes glued to them:

    ה   definite article ("the")     ← השיוך
    ל   "to"                          ← לשיוך
    ב   "in"                          ← בשיוך
    מ   "from"                        ← משיוך
    ש   "that / which"                ← ששיוך
    ו   "and"                         ← ושיוך
    כ   "as / like"                   ← כשיוך

Combinations are common too: והשיוך ("and the-שיוך"), מהשיוך ("from-the-שיוך").
Substring matching against the bare "שיוך" catches none of these because the
prefix letters are wedged between whatever precedes and the noun.

This module produces a **candidate list** of surface forms for a canonical
term. It's intentionally over-generative — reviewers trim what doesn't fit.
Precision is a UX problem, not a matcher problem: the matcher already checks
word boundaries so "שיוך" matched inside "שיוכה" (unrelated) won't fire.

Plural is handled naïvely: masculine ים suffix + feminine ות suffix. This
misses irregular plurals; reviewers add those manually.
"""
from __future__ import annotations

_SINGLE_PREFIXES = ("ה", "ל", "ב", "מ", "ש", "ו", "כ")
_DOUBLE_PREFIXES = ("וה", "לה", "בה", "מה", "שה", "וב", "ול", "ומ")
_PLURAL_SUFFIXES = ("ים", "ות")

# Hebrew "final form" letters — appear only at the end of a word. Before
# adding a suffix (plural, prefix that becomes non-final), swap to the
# medial form: שיוך → שיוכ, ילדים → ילדימ, etc.
_FINAL_TO_MEDIAL = {"ך": "כ", "ם": "מ", "ן": "נ", "ף": "פ", "ץ": "צ"}


def _demote_final(word: str) -> str:
    """Swap trailing final-form letter to its medial form. Only touches
    the last character — a word can only end in one final-form letter."""
    if word and word[-1] in _FINAL_TO_MEDIAL:
        return word[:-1] + _FINAL_TO_MEDIAL[word[-1]]
    return word


def expand_hebrew_prefixes(term: str) -> list[str]:
    """Return canonical + prefixed + plural forms, deduped, canonical first."""
    term = (term or "").strip()
    if not term:
        return []
    forms: list[str] = [term]
    for p in _SINGLE_PREFIXES:
        forms.append(p + term)
    for p in _DOUBLE_PREFIXES:
        forms.append(p + term)
    # Very naïve plurals — apply only if the term looks like a noun (no space
    # inside; multi-word terms don't get pluralized this way). Demote a
    # trailing final-form letter before suffixing (שיוך → שיוכים, not שיוךים).
    if " " not in term and len(term) >= 2:
        stem = _demote_final(term)
        for suf in _PLURAL_SUFFIXES:
            plural = stem + suf
            forms.append(plural)
            for p in _SINGLE_PREFIXES:
                forms.append(p + plural)
            for p in _DOUBLE_PREFIXES:
                forms.append(p + plural)
    seen: set[str] = set()
    out: list[str] = []
    for f in forms:
        if f and f not in seen:
            seen.add(f)
            out.append(f)
    return out
