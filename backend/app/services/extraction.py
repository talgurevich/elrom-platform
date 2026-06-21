"""Text extraction service — used by both the upload endpoint and the CLI script.

Returns (text, used_ocr) so the caller can flag OCR-derived documents.
"""
from dataclasses import dataclass
from pathlib import Path

import structlog

from app.services import ocr as ocr_service

log = structlog.get_logger()

SUPPORTED_EXTENSIONS = {".txt", ".md", ".docx", ".pdf"}


@dataclass
class ExtractionResult:
    text: str
    used_ocr: bool
    extractor: str  # which path was taken: "txt" | "docx" | "pdfplumber" | "azure_ocr"
    note: str | None = None  # human-readable diagnostic, e.g. "scanned PDF — no OCR configured"
    pages: int | None = None  # source page count when known (PDFs)
    failed_ocr_batches: list[int] | None = None  # set when OCR partially failed
    partial: bool = False  # True when extractor returned incomplete content


def extract_text(path: Path, prefer_ocr: bool = False) -> ExtractionResult:
    """Extract text from a file. Falls back to Azure OCR if a PDF has no native text.

    prefer_ocr: for PDFs, skip pdfplumber and go straight to Azure OCR. Useful
    for scanned Hebrew PDFs where pdfplumber returns reversed RTL text that
    looks valid (passes density check) but is unusable for embedding/search.
    """
    suffix = path.suffix.lower()

    if suffix in {".txt", ".md"}:
        return ExtractionResult(text=path.read_text(encoding="utf-8"), used_ocr=False, extractor="txt")

    if suffix == ".docx":
        return ExtractionResult(text=_extract_docx(path), used_ocr=False, extractor="docx")

    if suffix == ".pdf":
        page_count = _pdf_page_count(path)
        if not prefer_ocr:
            native = _extract_pdf_native(path)
            if native.strip():
                return ExtractionResult(
                    text=native, used_ocr=False, extractor="pdfplumber", pages=page_count
                )

        if not ocr_service.is_configured():
            return ExtractionResult(
                text="",
                used_ocr=False,
                extractor="pdfplumber",
                pages=page_count,
                note="PDF has no extractable text (likely scanned). Azure OCR not configured.",
            )

        try:
            ocr_text = ocr_service.ocr_pdf(path)
        except ocr_service.PartialOcrError as e:
            return ExtractionResult(
                text=e.partial_text,
                used_ocr=True,
                extractor="azure_ocr",
                pages=page_count,
                failed_ocr_batches=e.failed_batches,
                partial=True,
                note=(
                    f"Azure OCR failed on {len(e.failed_batches)}/{e.total_batches} batches "
                    f"({e.failed_batches}); partial text returned."
                ),
            )
        return ExtractionResult(
            text=ocr_text,
            used_ocr=True,
            extractor="azure_ocr",
            pages=page_count,
            note=None if ocr_text.strip() else "Azure OCR returned no text",
        )

    return ExtractionResult(
        text="",
        used_ocr=False,
        extractor="unsupported",
        note=f"Unsupported file type: {suffix}",
    )


def _extract_docx(path: Path) -> str:
    from docx import Document  # type: ignore[import-not-found]

    doc = Document(path)
    parts: list[str] = []
    for para in doc.paragraphs:
        if para.text.strip():
            parts.append(para.text)
    for table in doc.tables:
        for row in table.rows:
            row_text = " | ".join(cell.text.strip() for cell in row.cells if cell.text.strip())
            if row_text:
                parts.append(row_text)
    return "\n\n".join(parts)


def _extract_pdf_native(path: Path) -> str:
    import pdfplumber  # type: ignore[import-not-found]

    pages: list[str] = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            if text.strip():
                pages.append(text)
    return "\n\n".join(pages)


def _pdf_page_count(path: Path) -> int | None:
    try:
        import pymupdf  # type: ignore[import-not-found]

        with pymupdf.open(path) as doc:
            return doc.page_count
    except Exception:
        return None
