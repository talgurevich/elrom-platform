"""OCR service — uses Azure Document Intelligence to extract text from scanned PDFs.

When pdfplumber returns no extractable text (i.e., the PDF is scanned image content),
fall back to this. Azure DI returns Hebrew in logical reading order with paragraph
structure preserved — no BiDi reversal issues.

Free F0 tier limits:
- 4 MB per file
- 500 pages / month quota
- Files larger than ~4 MB get split into page-batches first.
"""
import tempfile
from functools import lru_cache
from pathlib import Path

import structlog
from tenacity import retry, stop_after_attempt, wait_exponential

from app.config import settings

log = structlog.get_logger()

DEFAULT_MODEL = "prebuilt-read"

# Azure Free F0 limit is 4 MB. We split anything above 3.5 MB to leave headroom.
MAX_FILE_BYTES = 3_500_000
# Target pages per split chunk when we have to split.
PAGES_PER_CHUNK = 4
# Even small files get split when they exceed this many pages — Azure DI
# silently truncates long scanned PDFs (observed: 12-page file returned only
# page-1 text in a single call but full content when split into 4-page batches).
MAX_PAGES_PER_CALL = 4


@lru_cache(maxsize=1)
def _client():
    from azure.ai.documentintelligence import DocumentIntelligenceClient
    from azure.core.credentials import AzureKeyCredential

    if not settings.azure_di_endpoint or not settings.azure_di_key:
        raise RuntimeError(
            "Azure Document Intelligence not configured. Set AZURE_DI_ENDPOINT and AZURE_DI_KEY in .env."
        )

    return DocumentIntelligenceClient(
        endpoint=settings.azure_di_endpoint,
        credential=AzureKeyCredential(settings.azure_di_key),
    )


def is_configured() -> bool:
    return bool(settings.azure_di_endpoint and settings.azure_di_key)


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=2, max=20))
def _ocr_single(path: Path, model: str = DEFAULT_MODEL) -> tuple[str, int]:
    """OCR a single PDF that's already under the size limit. Returns (text, paragraph_count)."""
    client = _client()

    with open(path, "rb") as f:
        poller = client.begin_analyze_document(
            model_id=model,
            body=f,
            content_type="application/pdf",
        )
    result = poller.result()

    parts: list[str] = []
    paragraphs = getattr(result, "paragraphs", None) or []
    if paragraphs:
        for p in paragraphs:
            text = (getattr(p, "content", "") or "").strip()
            if text:
                parts.append(text)
    else:
        pages = getattr(result, "pages", None) or []
        for page in pages:
            lines = getattr(page, "lines", None) or []
            for line in lines:
                text = (getattr(line, "content", "") or "").strip()
                if text:
                    parts.append(text)

    return "\n\n".join(parts), len(paragraphs)


def _split_pdf_into_batches(src: Path, batch_size: int = PAGES_PER_CHUNK) -> list[Path]:
    """Split a PDF into N-page chunks; return list of temp file paths."""
    import pymupdf

    out_paths: list[Path] = []
    src_doc = pymupdf.open(src)
    total_pages = src_doc.page_count

    tmpdir = Path(tempfile.mkdtemp(prefix="ocr-split-"))
    for start in range(0, total_pages, batch_size):
        end = min(start + batch_size - 1, total_pages - 1)
        out_path = tmpdir / f"{src.stem}_p{start + 1:03d}-{end + 1:03d}.pdf"
        chunk = pymupdf.open()
        chunk.insert_pdf(src_doc, from_page=start, to_page=end)
        chunk.save(out_path)
        chunk.close()
        out_paths.append(out_path)
    src_doc.close()
    return out_paths


def ocr_pdf(path: Path, model: str = DEFAULT_MODEL) -> str:
    """Run Azure DI Read on a PDF; return logical-order text with paragraph breaks.

    If the file exceeds the Azure Free tier 4 MB limit, splits into smaller
    page batches and concatenates the OCR results.
    """
    import pymupdf

    size = path.stat().st_size
    with pymupdf.open(path) as _probe:
        page_count = _probe.page_count
    log.info("ocr.start", path=str(path), model=model, file_bytes=size, pages=page_count)

    # Single-call only when both small enough AND short enough. Long PDFs get
    # silently truncated by Azure DI on a single call.
    if size <= MAX_FILE_BYTES and page_count <= MAX_PAGES_PER_CALL:
        text, n_para = _ocr_single(path, model)
        log.info("ocr.done", path=str(path), chars=len(text), paragraphs=n_para)
        return text

    # Need to split
    batches = _split_pdf_into_batches(path)
    log.info("ocr.split", path=str(path), batches=len(batches))

    parts: list[str] = []
    for i, batch_path in enumerate(batches, 1):
        try:
            chunk_text, _ = _ocr_single(batch_path, model)
            if chunk_text.strip():
                parts.append(chunk_text)
            log.info("ocr.batch_done", batch=i, of=len(batches), chars=len(chunk_text))
        except Exception as e:
            log.warning("ocr.batch_failed", batch=i, error=str(e)[:200])
        finally:
            try:
                batch_path.unlink()
            except OSError:
                pass

    combined = "\n\n".join(parts)
    log.info("ocr.done", path=str(path), chars=len(combined), total_batches=len(batches))
    return combined
