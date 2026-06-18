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


def extract_text(path: Path) -> ExtractionResult:
    """Extract text from a file. Falls back to Azure OCR if a PDF has no native text."""
    suffix = path.suffix.lower()

    if suffix in {".txt", ".md"}:
        return ExtractionResult(text=path.read_text(encoding="utf-8"), used_ocr=False, extractor="txt")

    if suffix == ".docx":
        return ExtractionResult(text=_extract_docx(path), used_ocr=False, extractor="docx")

    if suffix == ".pdf":
        native = _extract_pdf_native(path)
        if native.strip():
            return ExtractionResult(text=native, used_ocr=False, extractor="pdfplumber")

        if not ocr_service.is_configured():
            return ExtractionResult(
                text="",
                used_ocr=False,
                extractor="pdfplumber",
                note="PDF has no extractable text (likely scanned). Azure OCR not configured.",
            )

        ocr_text = ocr_service.ocr_pdf(path)
        return ExtractionResult(
            text=ocr_text,
            used_ocr=True,
            extractor="azure_ocr",
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
