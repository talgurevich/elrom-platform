"""Tests for the cite-or-refuse guardrail and title/filename matching."""
from app.services.llm import (
    _GUARDRAIL_REFUSE_ANSWER,
    LLMResult,
    Reference,
    _enforce_cite_or_refuse,
    _guardrail_violation,
    _title_matches_any_filename,
)


def _ref(title: str, section: str = "4", source_type: str = "תקנון משנה") -> Reference:
    return Reference(title=title, section_number=section, source_type=source_type, excerpt="ציטוט")


FILENAMES = {"תקנון פנסיה 2019.pdf", "פרוטוקול אסיפת חברים 4-16 05.07.16.pdf"}


class TestTitleMatching:
    def test_exact_filename(self):
        assert _title_matches_any_filename("תקנון פנסיה 2019.pdf", FILENAMES)

    def test_stem_without_extension(self):
        assert _title_matches_any_filename("תקנון פנסיה 2019", FILENAMES)

    def test_shortened_title_substring(self):
        assert _title_matches_any_filename("תקנון פנסיה", FILENAMES)

    def test_fabricated_title(self):
        assert not _title_matches_any_filename("חוק הביטוח הלאומי", FILENAMES)

    def test_empty(self):
        assert not _title_matches_any_filename("", FILENAMES)


class TestGuardrail:
    def test_confident_with_valid_reference_passes(self):
        r = LLMResult(
            answer="לפי סעיף 4, כך וכך.",
            confidence="confident",
            references=[_ref("תקנון פנסיה 2019.pdf")],
        )
        out = _enforce_cite_or_refuse(r, retrieved_filenames=FILENAMES)
        assert out.confidence == "confident"
        assert out.answer == r.answer

    def test_confident_without_references_refused(self):
        r = LLMResult(answer="תשובה בטוחה בלי מקור.", confidence="confident", references=[])
        out = _enforce_cite_or_refuse(r, retrieved_filenames=FILENAMES)
        assert out.confidence == "refused"
        assert out.answer == _GUARDRAIL_REFUSE_ANSWER

    def test_confident_with_fabricated_titles_refused(self):
        r = LLMResult(
            answer="תשובה.",
            confidence="confident",
            references=[_ref("מסמך שלא נשלף מעולם")],
        )
        out = _enforce_cite_or_refuse(r, retrieved_filenames=FILENAMES)
        assert out.confidence == "refused"

    def test_one_valid_reference_is_enough(self):
        r = LLMResult(
            answer="תשובה.",
            confidence="confident",
            references=[_ref("מסמך מומצא"), _ref("תקנון פנסיה 2019")],
        )
        out = _enforce_cite_or_refuse(r, retrieved_filenames=FILENAMES)
        assert out.confidence == "confident"

    def test_summary_reference_with_empty_section_passes(self):
        # The document-summary flow (§4.5): title = the doc, empty section.
        r = LLMResult(
            answer="מדובר בפרוטוקול אסיפת חברים מ-5.7.2016.",
            confidence="confident",
            references=[
                _ref("פרוטוקול אסיפת חברים 4-16 05.07.16.pdf", section="", source_type="פרוטוקול")
            ],
        )
        out = _enforce_cite_or_refuse(r, retrieved_filenames=FILENAMES)
        assert out.confidence == "confident"

    def test_meta_reference_passes(self):
        r = LLMResult(
            answer="במאגר 120 מסמכים.",
            confidence="confident",
            references=[_ref("מאגר הארגון", section="", source_type="meta")],
        )
        out = _enforce_cite_or_refuse(r, retrieved_filenames=FILENAMES)
        assert out.confidence == "confident"

    def test_uncertain_passes_through_untouched(self):
        r = LLMResult(answer="חלקי.", confidence="uncertain", references=[])
        out = _enforce_cite_or_refuse(r, retrieved_filenames=FILENAMES)
        assert out is r

    def test_refused_passes_through_untouched(self):
        r = LLMResult(answer="לא מצאתי.", confidence="refused", references=[])
        out = _enforce_cite_or_refuse(r, retrieved_filenames=FILENAMES)
        assert out is r

    def test_clarifying_passes_through_untouched(self):
        r = LLMResult(answer="כדי לענות אני צריך לדעת…", confidence="clarifying", references=[])
        out = _enforce_cite_or_refuse(r, retrieved_filenames=FILENAMES)
        assert out is r


class TestGuardrailViolationCheck:
    """The pure check that drives the retry-with-feedback flow. Must agree
    with _enforce_cite_or_refuse on every case."""

    def test_no_violation_on_valid(self):
        r = LLMResult(
            answer="ת.", confidence="confident", references=[_ref("תקנון פנסיה 2019.pdf")]
        )
        assert _guardrail_violation(r, retrieved_filenames=FILENAMES) is None

    def test_no_references_kind(self):
        r = LLMResult(answer="ת.", confidence="confident", references=[])
        assert _guardrail_violation(r, retrieved_filenames=FILENAMES) == "no_references"

    def test_unmatched_titles_kind(self):
        r = LLMResult(answer="ת.", confidence="confident", references=[_ref("מומצא")])
        assert _guardrail_violation(r, retrieved_filenames=FILENAMES) == "unmatched_titles"

    def test_non_confident_never_violates(self):
        for conf in ("uncertain", "refused", "clarifying"):
            r = LLMResult(answer="ת.", confidence=conf, references=[])
            assert _guardrail_violation(r, retrieved_filenames=FILENAMES) is None

    def test_meta_reference_never_violates(self):
        r = LLMResult(
            answer="ת.",
            confidence="confident",
            references=[_ref("מאגר הארגון", section="", source_type="meta")],
        )
        assert _guardrail_violation(r, retrieved_filenames=FILENAMES) is None

    def test_agreement_with_enforce(self):
        cases = [
            LLMResult(answer="ת.", confidence="confident", references=[]),
            LLMResult(answer="ת.", confidence="confident", references=[_ref("מומצא")]),
            LLMResult(answer="ת.", confidence="confident", references=[_ref("תקנון פנסיה")]),
            LLMResult(answer="ת.", confidence="uncertain", references=[]),
        ]
        for r in cases:
            enforced = _enforce_cite_or_refuse(r, retrieved_filenames=FILENAMES)
            violation = _guardrail_violation(r, retrieved_filenames=FILENAMES)
            assert (enforced.confidence == "refused" and r.confidence == "confident") == (
                violation is not None
            )
