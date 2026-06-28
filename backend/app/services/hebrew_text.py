"""Hebrew text normalization for FTS / BM25.

Postgres' ``to_tsvector('simple', …)`` is whitespace-based — no stemming, no
morphology. For Hebrew this collapses recall: ``ירושה`` ≠ ``הירושה`` ≠
``ירושת``, and a query like ``מה דין הירושה`` returns zero hits against a
corpus that only uses ``ירושה``.

We apply *light* morphological normalization in Python before text hits
``to_tsvector``, and apply the *identical* normalization to user queries
before they hit ``plainto_tsquery``. The FTS index then stores and looks up
normalized lexemes — recovering most of the prefix/suffix attachment gap with
zero external dependencies.

This is option (a) from ROADMAP-v0.3.md (Hebrew BM25). Not full morphology —
just enough to make hybrid retrieval actually hybrid for Hebrew.

Apply identically to indexed text and query text.
"""
import re
import unicodedata

# Hebrew prefix clusters that *attach* to nouns/verbs. Try longer combos first
# (greedy) so ``וה``/``כש`` strip as one unit rather than letter-by-letter.
_PREFIXES_3 = ("לכש", "מהש", "וכש")
_PREFIXES_2 = (
    "וה", "שה", "מה", "כה", "לה",
    "וב", "שב", "מב", "כב", "לב",
    "ול", "של", "מל", "כל",
    "ומ", "שמ", "כמ", "למ",
    "וכ", "שכ", "מכ", "לכ",
    "וש", "כש", "מש", "לש",
    "הו",
)
_PREFIXES_1 = ("ה", "ב", "ל", "ו", "מ", "כ", "ש")

# Common pronoun / inflection suffixes (longest first).
# NOTE: listed in their POST-sofit-normalized form (ם→מ, ן→נ, ך→כ) because
# the normalizer applies sofit folding *before* suffix stripping.
_SUFFIXES = (
    "ותיהמ", "ותיהנ", "ותינו", "ותיכמ", "ותיכנ",
    "יהמ", "יהנ",
    "המ", "הנ", "כמ", "כנ", "נו", "תי", "תמ", "תנ",
    "יו", "יה", "יכ", "ימ", "ות", "ינו",
    "מ", "נ", "ה", "ו", "כ", "י", "ת",
)

# Sofit → base form: so ``בית`` and ``בתים`` share a stem under the prefix
# stripper, and so a word that loses a sofit-final to a suffix-strip still
# matches its plural variant.
_SOFIT = str.maketrans({"ך": "כ", "ם": "מ", "ן": "נ", "ף": "פ", "ץ": "צ"})

# Minimum stem length we require after stripping. Below this, false positives
# (``ברק`` → ``רק``) dominate. 3 is a reasonable Hebrew minimum.
_MIN_STEM = 3

_HEB_RE = re.compile(r"[֐-׿]")
_TOKEN_RE = re.compile(r"[A-Za-z0-9֐-׿]+", re.UNICODE)


def _strip_niqqud(s: str) -> str:
    """Remove combining marks (niqqud / cantillation) so vocalized text matches
    unvocalized text. Niqqud is rare in our corpus but defensive."""
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def _strip_marks(s: str) -> str:
    # Geresh / gershayim used in Hebrew acronyms — drop for matching purposes.
    for ch in ("׳", "״", "'", '"'):
        s = s.replace(ch, "")
    return s


def _strip_one_prefix(t: str) -> str | None:
    """Strip a single prefix cluster from t (greedy 3→2→1). Returns the
    stripped form if stripping is safe (stem stays ≥ _MIN_STEM), else None."""
    for pfx in _PREFIXES_3:
        if t.startswith(pfx) and len(t) - len(pfx) >= _MIN_STEM:
            return t[len(pfx):]
    for pfx in _PREFIXES_2:
        if t.startswith(pfx) and len(t) - len(pfx) >= _MIN_STEM:
            return t[len(pfx):]
    for pfx in _PREFIXES_1:
        if t.startswith(pfx) and len(t) - 1 >= _MIN_STEM:
            return t[1:]
    return None


def _strip_one_suffix(t: str) -> str | None:
    for sfx in _SUFFIXES:
        if t.endswith(sfx) and len(t) - len(sfx) >= _MIN_STEM:
            return t[: -len(sfx)]
    return None


def _normalize_forms(tok: str) -> list[str]:
    """Return all normalized forms for a single token.

    We emit multiple forms because rule-based Hebrew morphology can't reliably
    distinguish a real prefix (``ה``, ``ב``) from a word-initial letter that
    looks like one (``שיוך`` starts with ``ש`` but ``ש`` is part of the root).
    Indexing every safe form lets either side of an ambiguous case match the
    other:

        ``השיוך`` → {השיוכ, שיוכ, שיו}
        ``שיוך``   → {שיוכ, יוכ}
        intersect = {שיוכ} → BM25 hit.
    """
    if not tok:
        return []
    if not _HEB_RE.search(tok):
        return [tok.lower()]

    base = _strip_marks(_strip_niqqud(tok)).translate(_SOFIT)
    forms: set[str] = {base}

    pre = _strip_one_prefix(base)
    if pre:
        forms.add(pre)

    suf = _strip_one_suffix(base)
    if suf:
        forms.add(suf)

    if pre:
        suf_of_pre = _strip_one_suffix(pre)
        if suf_of_pre:
            forms.add(suf_of_pre)

    return [f for f in forms if len(f) >= 2]


def normalize_hebrew(text: str) -> str:
    """Tokenize + emit normalized lexemes for FTS use.

    Returns a whitespace-joined string of normalized forms, suitable as input
    to ``to_tsvector('simple', …)`` and ``plainto_tsquery('simple', …)``.

    A single source token can produce up to 4 output forms (full, prefix-
    stripped, suffix-stripped, both-stripped). This expands recall at the cost
    of a slightly larger index — the rerank stage trims false-positive hits.

    Idempotent up to set-equality on the produced lexeme set.
    """
    if not text:
        return ""
    out: list[str] = []
    for raw in _TOKEN_RE.findall(text):
        out.extend(_normalize_forms(raw))
    return " ".join(out)
