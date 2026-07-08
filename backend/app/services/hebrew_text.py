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
    """Tokenize + emit normalized lexemes for FTS use (index side).

    Returns a whitespace-joined string of normalized forms, suitable as input
    to ``to_tsvector('simple', …)``. A single source token can produce up to
    4 output forms (full, prefix-stripped, suffix-stripped, both-stripped).
    The tsvector deduplicates these on the way in.

    IMPORTANT: on the *query* side, do NOT feed this directly to
    ``plainto_tsquery`` — that would AND every form and destroy recall. Use
    :func:`normalize_hebrew_to_tsquery` instead, which ORs the forms of each
    source word and ANDs across source words.

    Idempotent up to set-equality on the produced lexeme set.
    """
    if not text:
        return ""
    out: list[str] = []
    for raw in _TOKEN_RE.findall(text):
        out.extend(_normalize_forms(raw))
    return " ".join(out)


# ─────────────────────────────────────────────────────────────────────────
# Query-side normalization: build a to_tsquery expression that respects
# per-source-word alternation.
# ─────────────────────────────────────────────────────────────────────────


# High-frequency Hebrew function words. Present in almost every doc and
# useless as retrieval constraints — dropping them from the AND stack keeps
# BM25 from over-filtering. Kept short on purpose; false positives here are
# harmless (they'd only reduce recall on a corner-case query where a stop
# word carries meaning), but false negatives (leaving in a real content word)
# would silently drop hits.
_QUERY_STOPWORDS: set[str] = {
    "מה", "מי", "האם", "איך", "כמה", "מתי", "איפה", "למה",
    "אם", "או", "גם", "כי", "כן", "לא", "רק", "עוד", "יש",
    "של", "את", "על", "אל", "עם", "לפי", "לגבי", "בגלל",
    "זה", "זו", "אלה", "אלו", "הוא", "היא", "הם", "הן",
    "אני", "אתה", "את", "אנחנו", "אתם", "אתן",
    # Latin question words that show up when users switch language
    "the", "and", "or", "is", "are", "what", "how",
}


# to_tsquery is picky about the alphabet. We already keep letters/digits via
# _TOKEN_RE, but defensively strip anything else a form might smuggle in.
_QUERY_SAFE_RE = re.compile(r"[^A-Za-z0-9֐-׿]")


def _to_tsquery_lexeme(form: str) -> str:
    return _QUERY_SAFE_RE.sub("", form)


def normalize_hebrew_to_tsquery(text: str) -> str:
    """Build a ``to_tsquery('simple', …)`` expression from a user question.

    Each source word produces a group ``(form1 | form2 | form3)`` covering
    its recognized normalized forms; groups are joined with ``&``. Stop words
    (question words, conjunctions) are dropped so they don't over-constrain
    the AND stack.

    Example::

        >>> normalize_hebrew_to_tsquery("מה קורה עם הפנסיה")
        '(קור | קורה) & (הפנס | פנס | פנסיה | הפנסיה)'

    An empty return value means "no queryable tokens" — the caller should
    then skip the BM25 branch entirely rather than passing "" to to_tsquery.
    """
    if not text:
        return ""
    groups: list[str] = []
    seen_groups: set[str] = set()  # dedup identical source words (e.g. "חבר חבר")
    for raw in _TOKEN_RE.findall(text):
        low = raw.lower()
        if low in _QUERY_STOPWORDS:
            continue
        forms = _normalize_forms(raw)
        if not forms:
            continue
        # Additional stop-word check on the base form — catches sofit
        # variants like "אתם" → "אתמ" that the raw check would miss.
        base = forms[0] if forms else ""
        if base in _QUERY_STOPWORDS:
            continue
        # Sanitize + dedup within a source word.
        safe_forms = []
        seen_forms: set[str] = set()
        for f in forms:
            f2 = _to_tsquery_lexeme(f)
            if f2 and f2 not in seen_forms:
                seen_forms.add(f2)
                safe_forms.append(f2)
        if not safe_forms:
            continue
        group = safe_forms[0] if len(safe_forms) == 1 else "(" + " | ".join(safe_forms) + ")"
        if group in seen_groups:
            continue
        seen_groups.add(group)
        groups.append(group)
    return " & ".join(groups)
