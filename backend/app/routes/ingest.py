"""Ingest endpoints — text body or file upload, both share the same indexing path."""
import tempfile
from pathlib import Path
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Chunk, Document, Tenant
from app.services.chunking import chunk_document
from app.services.embedding import embed_texts
from app.services.extraction import SUPPORTED_EXTENSIONS, extract_text as extract_file

log = structlog.get_logger()
router = APIRouter()


class IngestRequest(BaseModel):
    filename: str
    text: str
    tenant_id: UUID | None = None  # if omitted, uses the first tenant (dev convenience)
    doc_type: str | None = None  # bylaw | sub_bylaw | minutes | decision | other
    extractor: str | None = None  # set by CLI script when extraction happened client-side
    used_ocr: bool = False
    pages: int | None = None
    extraction_partial: bool = False
    extraction_note: str | None = None
    force: bool = False  # bypass density sanity check


class IngestResponse(BaseModel):
    document_id: UUID
    chunks_created: int
    used_ocr: bool = False
    extractor: str | None = None
    note: str | None = None
    pages: int | None = None
    chars_extracted: int | None = None
    partial: bool = False


# Refuse to persist a PDF that yielded fewer chars per page than this — almost
# always means OCR mostly failed or the file was scanned without OCR configured.
MIN_CHARS_PER_PAGE = 200


@router.post("", response_model=IngestResponse)
def ingest(req: IngestRequest, db: Session = Depends(get_db)) -> IngestResponse:
    """Ingest a single document.

    MVP scope: accepts text directly (no OCR yet). Splits into structural chunks,
    embeds each, persists to pgvector. Date metadata extraction comes in Week 2.
    """
    tenant_id = req.tenant_id
    if tenant_id is None:
        tenant = db.query(Tenant).first()
        if not tenant:
            raise HTTPException(400, "No tenant exists. Create one first.")
        tenant_id = tenant.id

    # Density sanity check — refuse PDFs that produced suspiciously little text
    # per page (usually means OCR was needed but didn't run, or partial OCR).
    if req.pages and req.pages > 0 and not req.force:
        density = len(req.text) / req.pages
        if density < MIN_CHARS_PER_PAGE:
            raise HTTPException(
                400,
                f"Refusing to ingest: extracted only {len(req.text)} chars across "
                f"{req.pages} pages ({density:.0f}/page < {MIN_CHARS_PER_PAGE} threshold). "
                f"Likely an OCR failure. Re-extract or pass force=true to override.",
            )
    if req.extraction_partial and not req.force:
        raise HTTPException(
            400,
            f"Refusing to ingest: extraction was partial ({req.extraction_note}). "
            f"Fix the source or pass force=true.",
        )

    doc = Document(
        tenant_id=tenant_id,
        filename=req.filename,
        doc_type=req.doc_type,
        extractor=req.extractor,
        used_ocr=req.used_ocr,
        pages=req.pages,
        chars_extracted=len(req.text),
        extraction_partial=req.extraction_partial,
        extraction_note=req.extraction_note,
    )
    db.add(doc)
    db.flush()  # get the id without committing

    structural_chunks = chunk_document(req.text)
    if not structural_chunks:
        raise HTTPException(400, "Document produced no chunks.")

    embeddings = embed_texts([sc.text for sc in structural_chunks])

    for sc, embedding in zip(structural_chunks, embeddings, strict=True):
        chunk = Chunk(
            document_id=doc.id,
            tenant_id=tenant_id,
            position=sc.position,
            section_path=sc.section_path,
            text=sc.text,
            embedding=embedding,
        )
        db.add(chunk)
        db.flush()
        db.execute(
            text("UPDATE chunks SET text_search = to_tsvector('simple', text) WHERE id = :cid"),
            {"cid": chunk.id},
        )

    doc.chunks_created = len(structural_chunks)
    db.commit()
    log.info(
        "ingest.complete",
        document_id=str(doc.id),
        chunks=len(structural_chunks),
        with_section_path=sum(1 for c in structural_chunks if c.section_path),
    )
    return IngestResponse(
        document_id=doc.id,
        chunks_created=len(structural_chunks),
        used_ocr=req.used_ocr,
        extractor=req.extractor,
        note=req.extraction_note,
        pages=req.pages,
        chars_extracted=len(req.text),
        partial=req.extraction_partial,
    )


@router.post("/upload", response_model=IngestResponse)
async def ingest_upload(
    file: UploadFile = File(...),
    tenant_id: UUID | None = Form(None),
    doc_type: str | None = Form(None),
    db: Session = Depends(get_db),
) -> IngestResponse:
    """Accept a file upload (txt/md/docx/pdf), extract text (with OCR fallback for scanned PDFs),
    chunk + embed + store. Returns chunks_created + extractor metadata.
    """
    filename = file.filename or "uploaded"
    suffix = Path(filename).suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise HTTPException(
            400, f"Unsupported file type: {suffix}. Supported: {sorted(SUPPORTED_EXTENSIONS)}"
        )

    resolved_tenant = tenant_id
    if resolved_tenant is None:
        tenant = db.query(Tenant).first()
        if not tenant:
            raise HTTPException(400, "No tenant exists. Create one first.")
        resolved_tenant = tenant.id

    # Save to a temp file so the existing extraction service can use Path-based APIs
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        contents = await file.read()
        tmp.write(contents)
        tmp_path = Path(tmp.name)

    try:
        extraction = extract_file(tmp_path)
    finally:
        try:
            tmp_path.unlink()
        except OSError:
            pass

    if not extraction.text.strip():
        raise HTTPException(
            400,
            extraction.note or "No text could be extracted from the file.",
        )

    # Density sanity check
    if extraction.pages and extraction.pages > 0:
        density = len(extraction.text) / extraction.pages
        if density < MIN_CHARS_PER_PAGE:
            raise HTTPException(
                400,
                f"Refusing to ingest {filename}: {len(extraction.text)} chars across "
                f"{extraction.pages} pages ({density:.0f}/page < {MIN_CHARS_PER_PAGE}). "
                f"Likely OCR failure. {extraction.note or ''}".strip(),
            )
    if extraction.partial:
        raise HTTPException(
            400,
            f"Refusing to ingest {filename}: extraction was partial. {extraction.note}",
        )

    doc = Document(
        tenant_id=resolved_tenant,
        filename=filename,
        doc_type=doc_type,
        extractor=extraction.extractor,
        used_ocr=extraction.used_ocr,
        pages=extraction.pages,
        chars_extracted=len(extraction.text),
        extraction_partial=extraction.partial,
        extraction_note=extraction.note,
    )
    db.add(doc)
    db.flush()

    structural_chunks = chunk_document(extraction.text)
    if not structural_chunks:
        raise HTTPException(400, "Document produced no chunks.")

    embeddings = embed_texts([sc.text for sc in structural_chunks])

    for sc, embedding in zip(structural_chunks, embeddings, strict=True):
        chunk = Chunk(
            document_id=doc.id,
            tenant_id=resolved_tenant,
            position=sc.position,
            section_path=sc.section_path,
            text=sc.text,
            embedding=embedding,
        )
        db.add(chunk)
        db.flush()
        db.execute(
            text("UPDATE chunks SET text_search = to_tsvector('simple', text) WHERE id = :cid"),
            {"cid": chunk.id},
        )

    doc.chunks_created = len(structural_chunks)
    db.commit()
    log.info(
        "ingest.upload_complete",
        document_id=str(doc.id),
        chunks=len(structural_chunks),
        extractor=extraction.extractor,
        used_ocr=extraction.used_ocr,
        pages=extraction.pages,
        chars=len(extraction.text),
    )
    return IngestResponse(
        document_id=doc.id,
        chunks_created=len(structural_chunks),
        used_ocr=extraction.used_ocr,
        extractor=extraction.extractor,
        note=extraction.note,
        pages=extraction.pages,
        chars_extracted=len(extraction.text),
        partial=extraction.partial,
    )
