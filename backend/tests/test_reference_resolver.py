"""Tests for binding LLM-emitted references to real documents."""
from dataclasses import dataclass
from uuid import uuid4

from app.services.reference_resolver import (
    ACCEPT_SCORE,
    _score,
    resolve_references,
)


@dataclass
class FakeSource:
    document_id: object
    document_filename: str
    has_file: bool = True


@dataclass
class FakeRef:
    title: str
    section_number: str = ""
    source_type: str = "תקנון משנה"
    excerpt: str = "ציטוט"


class TestScore:
    def test_exact_match(self):
        assert _score("תקנון פנסיה.pdf", "תקנון פנסיה.pdf") == 100.0

    def test_whitespace_drift(self):
        # 38% of the corpus has double-spaced filenames; the model collapses
        # them when echoing. Must still match at high confidence.
        assert _score("תקנון  פנסיה.pdf", "תקנון פנסיה.pdf") >= 95.0

    def test_extension_swap(self):
        assert _score("תקנון פנסיה.docx", "תקנון פנסיה.pdf") >= 90.0

    def test_shortened_title(self):
        assert _score("תקנון פנסיה", "תקנון פנסיה 2019.pdf") >= ACCEPT_SCORE

    def test_dash_variants(self):
        assert _score("אל–רום החלטות.pdf", "אל-רום החלטות.pdf") >= 95.0

    def test_unrelated_titles_rejected(self):
        assert _score("תקנון בריכת השחייה", "פרוטוקול אסיפה 4-16.pdf") < ACCEPT_SCORE


class TestResolveReferences:
    def test_binds_to_canonical_filename(self):
        doc_id = uuid4()
        sources = [FakeSource(doc_id, "תקנון  שיוך  דירות.pdf")]
        refs = [FakeRef(title="תקנון שיוך דירות.pdf")]
        resolved, dropped = resolve_references(refs, sources)
        assert dropped == 0
        assert resolved[0].title == "תקנון  שיוך  דירות.pdf"  # canonical, not model's
        assert resolved[0].document_id == doc_id
        assert resolved[0].resolved is True

    def test_fabricated_title_dropped_and_counted(self):
        sources = [FakeSource(uuid4(), "תקנון פנסיה.pdf")]
        refs = [FakeRef(title="חוק העמותות התשמ׳׳א")]
        resolved, dropped = resolve_references(refs, sources)
        assert resolved == []
        assert dropped == 1

    def test_meta_reference_passes_without_document(self):
        refs = [FakeRef(title="מאגר הארגון", source_type="meta")]
        resolved, dropped = resolve_references(refs, [])
        assert dropped == 0
        assert resolved[0].document_id is None
        assert resolved[0].resolved is False

    def test_chunk_count_breaks_ties(self):
        # Two near-duplicate docs; the one that contributed more chunks wins.
        a, b = uuid4(), uuid4()
        sources = [
            FakeSource(a, "פרוטוקול אסיפה 4-16.pdf"),
            FakeSource(b, "פרוטוקול אסיפה 4-16.docx"),
            FakeSource(b, "פרוטוקול אסיפה 4-16.docx"),
        ]
        refs = [FakeRef(title="פרוטוקול אסיפה 4-16")]
        resolved, dropped = resolve_references(refs, sources)
        assert dropped == 0
        assert resolved[0].document_id == b

    def test_order_preserved(self):
        d1, d2 = uuid4(), uuid4()
        sources = [FakeSource(d1, "תקנון א.pdf"), FakeSource(d2, "תקנון ב.pdf")]
        refs = [FakeRef(title="תקנון ב.pdf"), FakeRef(title="תקנון א.pdf")]
        resolved, _ = resolve_references(refs, sources)
        assert [r.document_id for r in resolved] == [d2, d1]

    def test_empty_title_dropped(self):
        sources = [FakeSource(uuid4(), "תקנון פנסיה.pdf")]
        resolved, dropped = resolve_references([FakeRef(title="")], sources)
        assert resolved == []
        assert dropped == 1
