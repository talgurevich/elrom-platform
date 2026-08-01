"""Tests for the Hebrew FTS normalization pipeline.

These lock down the invariant that broke retrieval twice already: for any
chunk text T containing term X and any query Q containing X (possibly with
a prefix/suffix variant), the query tsquery must match the indexed lexemes.
See memory notes project-bm25-hebrew-gap for the incident history.
"""
from app.services.hebrew_text import (
    normalize_filename_for_tsvector,
    normalize_hebrew,
    normalize_hebrew_to_tsquery,
)


def _tsquery_matches_index(tsquery: str, indexed: str) -> bool:
    """Mini-evaluator for the subset of to_tsquery syntax we generate:
    groups of (a | b | c) joined by &. Matches Postgres 'simple' semantics
    for our generated queries (single lexemes, no phrase ops)."""
    lexemes = set(indexed.split())
    if not tsquery:
        return False
    for group in tsquery.split("&"):
        alts = {a.strip(" ()") for a in group.split("|")}
        alts.discard("")
        if not (alts & lexemes):
            return False
    return True


class TestQueryIndexAgreement:
    """The core invariant: query-side and index-side normalization agree."""

    def test_exact_term_matches(self):
        q = normalize_hebrew_to_tsquery("טורבינות רוח")
        idx = normalize_hebrew("הותקנו טורבינות רוח באל-רום")
        assert _tsquery_matches_index(q, idx)

    def test_prefixed_index_matches_bare_query(self):
        q = normalize_hebrew_to_tsquery("פנסיה")
        idx = normalize_hebrew("עדכון הפנסיה של חברי הקיבוץ")
        assert _tsquery_matches_index(q, idx)

    def test_prefixed_query_matches_bare_index(self):
        q = normalize_hebrew_to_tsquery("מה קורה עם הפנסיה")
        idx = normalize_hebrew("פנסיה תקציבית לחברים ותיקים")
        assert _tsquery_matches_index(q, idx)

    def test_construct_state_bridges_via_shared_stem(self):
        # טורבינת (construct) vs טורבינות (plural) share stem טורבינ.
        q = normalize_hebrew_to_tsquery("טורבינות רוח")
        idx = normalize_hebrew("אישור הקמת טורבינת רוח בשטח המשבצת")
        assert _tsquery_matches_index(q, idx)

    def test_cider_branch(self):
        q = normalize_hebrew_to_tsquery("ענף הסיידר")
        idx = normalize_hebrew("דיון על עתיד ענף הסיידר של הקיבוץ")
        assert _tsquery_matches_index(q, idx)

    def test_unrelated_text_does_not_match(self):
        q = normalize_hebrew_to_tsquery("טורבינות רוח")
        idx = normalize_hebrew("תקציב חינוך לשנת הלימודים")
        assert not _tsquery_matches_index(q, idx)


class TestQueryShape:
    def test_stopwords_dropped(self):
        q = normalize_hebrew_to_tsquery("מה קורה עם הפנסיה")
        # Question word "מה" and preposition "עם" must not constrain the AND.
        assert "מה" not in q.replace("המ", "")  # guard against substring luck
        assert "עמ " not in q
        assert "פנס" in q

    def test_or_within_word_and_across_words(self):
        q = normalize_hebrew_to_tsquery("טורבינות רוח")
        assert "&" in q  # two content words → AND
        assert "|" in q  # multiple forms of טורבינות → OR

    def test_empty_and_stopword_only_queries(self):
        assert normalize_hebrew_to_tsquery("") == ""
        assert normalize_hebrew_to_tsquery("מה זה") == ""

    def test_duplicate_source_words_dedup(self):
        q = normalize_hebrew_to_tsquery("חבר חבר")
        assert q.count("&") == 0


class TestNormalizeHebrew:
    def test_sofit_folding(self):
        out = normalize_hebrew("ארגון")
        assert "ארגונ" in out.split()

    def test_niqqud_stripped(self):
        assert normalize_hebrew("שָׁלוֹם") == normalize_hebrew("שלום")

    def test_gershayim_acronyms(self):
        out = normalize_hebrew('יו"ר האסיפה')
        assert "יור" in out.split()

    def test_idempotent_lexeme_set(self):
        once = set(normalize_hebrew("הפנסיה של החברים").split())
        twice = set(normalize_hebrew(" ".join(once)).split())
        assert once <= twice

    def test_empty(self):
        assert normalize_hebrew("") == ""


class TestFilenameNormalization:
    def test_extension_stripped(self):
        out = normalize_filename_for_tsvector("תקנון פנסיה 2019.pdf")
        assert "pdf" not in out
        assert "2019" in out.split()

    def test_separators_become_spaces(self):
        out = normalize_filename_for_tsvector("פרוטוקול_ועד_הנהלה_2024-03-14.docx")
        toks = out.split()
        assert "פרוטוקול" in toks
        assert "2024" in toks

    def test_matches_query_for_known_failure_case(self):
        # The original failing production query: file named for the cider
        # branch, query asks about it.
        q = normalize_hebrew_to_tsquery("ענף הסיידר")
        idx = normalize_filename_for_tsvector("אחסניית אל-רום, ענף הסיידר.docx")
        assert _tsquery_matches_index(q, idx)

    def test_empty(self):
        assert normalize_filename_for_tsvector("") == ""
