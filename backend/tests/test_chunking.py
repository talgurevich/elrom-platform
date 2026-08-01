"""Tests for structural chunking of Hebrew bylaws and protocols."""
from app.services.chunking import (
    _classify_decision,
    build_contextual_input,
    canonical_section_ref,
    chunk_document,
)


BYLAW = """תקנון קליטה לחברות — קיבוץ אל-רום

מסמך זה מסדיר את הליך הקליטה לחברות בקיבוץ, כפי שאושר באסיפה הכללית.

סעיף 1: הגדרות
"מועמד" — אדם שהגיש בקשה להתקבל לחברות.
"ועדת קליטה" — הוועדה שמונתה על ידי האסיפה.

סעיף 2: הגשת בקשה
מועמד יגיש בקשה בכתב לוועדת הקליטה בצירוף המסמכים הנדרשים.

סעיף 3: החלטת האסיפה
קבלת חבר טעונה אישור האסיפה הכללית ברוב של שני שלישים."""


PROTOCOL = """פרוטוקול ועד הנהלה 12/2024

נוכחים: א, ב, ג.

הוחלט: לאשר את תקציב ענף הנוי לשנת 2025.

הוחלט להעביר את נושא הרחבת חדר האוכל להצבעה בקלפי."""


class TestChunkDocument:
    def test_bylaw_sections_split(self):
        chunks = chunk_document(BYLAW)
        paths = [c.section_path for c in chunks]
        assert "סעיף 1" in paths
        assert "סעיף 2" in paths
        assert "סעיף 3" in paths

    def test_header_preserved_separately(self):
        chunks = chunk_document(BYLAW)
        header = chunks[0]
        assert header.section_path is None
        assert "תקנון קליטה" in header.text

    def test_positions_are_ordered(self):
        chunks = chunk_document(BYLAW)
        assert [c.position for c in chunks] == list(range(len(chunks)))

    def test_unstructured_falls_back_to_paragraphs(self):
        text = "פסקה ראשונה של מסמך חופשי לגמרי בלי סעיפים בכלל, עם מספיק תוכן כדי לעבור את הסף.\n\nפסקה שנייה שממשיכה את אותו רעיון בלי מבנה פורמלי כלשהו, גם היא ארוכה מספיק."
        chunks = chunk_document(text)
        assert chunks
        assert all(c.section_path is None for c in chunks)

    def test_empty_document(self):
        assert chunk_document("") == []

    def test_long_section_is_split(self):
        long_body = "\n\n".join(f"פסקה מספר {i} עם תוכן." * 20 for i in range(20))
        text = f"סעיף 1: כותרת\n{long_body}"
        chunks = chunk_document(text)
        assert len(chunks) > 1
        assert all(c.section_path == "סעיף 1" for c in chunks)
        assert all(len(c.text) <= 3500 + 100 for c in chunks)


class TestDecisionClassification:
    def test_terminal_decision(self):
        assert _classify_decision("הוחלט: לאשר את התקציב.") == "terminal"

    def test_escalation_exact_phrase(self):
        assert _classify_decision("הוחלט להעביר לאסיפה את הנושא.") == "escalation"

    def test_escalation_with_object_between(self):
        assert (
            _classify_decision("הוחלט להעביר את שלושת המשפחות להצבעה בקלפי.")
            == "escalation"
        )

    def test_midtext_escalation(self):
        text = "נדונו שמות החברים. הוחלט להעביר את הנושא להצבעה בקלפי."
        assert _classify_decision(text) == "escalation"

    def test_bylaw_prose_describing_appeal_rights_is_not_escalation(self):
        text = "חבר רשאי להביא את ערעורו בפני האסיפה הכללית."
        assert _classify_decision(text) is None

    def test_leading_terminal_with_later_escalation_stays_terminal(self):
        text = "הוחלט: לאשר את התקציב.\n\nהוחלט להעביר לאסיפה נושא אחר."
        assert _classify_decision(text) == "terminal"

    def test_protocol_chunks_get_classified(self):
        chunks = chunk_document(PROTOCOL)
        types = {c.decision_type for c in chunks}
        assert "terminal" in types
        assert "escalation" in types


class TestCanonicalSectionRef:
    def test_simple_section(self):
        assert canonical_section_ref("סעיף 44") == "44"

    def test_nested_section(self):
        assert canonical_section_ref("סעיף 45.ב") == "45.ב"

    def test_bare_number(self):
        assert canonical_section_ref("12.3") == "12.3"

    def test_chapter_is_not_amendable(self):
        assert canonical_section_ref("פרק א") is None

    def test_decision_is_not_amendable(self):
        assert canonical_section_ref("החלטה 5") is None

    def test_none(self):
        assert canonical_section_ref(None) is None


class TestBuildContextualInput:
    def test_header_prepended(self):
        out = build_contextual_input(
            text="תוכן הסעיף", section_path="סעיף 4", document_title="תקנון פנסיה.pdf"
        )
        assert out.startswith("תקנון פנסיה.pdf — סעיף 4")
        assert out.endswith("תוכן הסעיף")

    def test_no_metadata_returns_text(self):
        assert build_contextual_input(text="טקסט", section_path=None, document_title=None) == "טקסט"
