"""Ingest endpoints — text body or file upload, both share the same indexing path."""
import asyncio
import hashlib
import tempfile
from pathlib import Path
from uuid import UUID

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, Header, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Chunk, Document
from app.services.identity import IdentityUser, current_user
from app.routes.documents import classify_document_by_id_bg
from app.services.chunking import build_contextual_input, canonical_section_ref, chunk_document
from app.services.embedding import embed_texts
from app.services.hebrew_text import normalize_hebrew
from app.services.extraction import SUPPORTED_EXTENSIONS, extract_text as extract_file
from app.services.storage import save_original
from app.services.upload_dedup import (
    find_by_idempotency_key,
    find_by_sha256,
    handle_sha256_race,
    record_idempotency,
)

log = structlog.get_logger()
router = APIRouter()


class IngestRequest(BaseModel):
    filename: str
    text: str
    doc_type: str | None = None  # bylaw | sub_bylaw | minutes | decision | other
    extractor: str | None = None  # set by CLI script when extraction happened client-side
    used_ocr: bool = False
    pages: int | None = None
    extraction_partial: bool = False
    extraction_note: str | None = None
    force: bool = False  # bypass density sanity check
    auto_classify: bool = True  # background AI rename + summary + doc_type after ingest
    # Optional dedup key. If provided (typically the raw file bytes'
    # sha256 computed by the CLI extractor), it dedupes against the same
    # column /upload uses. Otherwise we fall back to hashing `text` — same
    # semantic but only catches other JSON-ingest of the same text.
    content_sha256: str | None = None
    # Optional idempotency key so retries of the same attempt don't
    # create duplicates. See services/upload_dedup for the model.
    idempotency_key: str | None = None


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
def ingest(
    req: IngestRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user: IdentityUser = Depends(current_user),
) -> IngestResponse:
    """Ingest a single document into the caller's tenant."""
    tenant_id = user.tenant_id

    # Idempotency: same attempt replayed → return stored response.
    idem_hit = find_by_idempotency_key(db, tenant_id=tenant_id, key=req.idempotency_key or "")
    if idem_hit is not None and idem_hit.response_json:
        log.info("ingest.idempotency_hit", key=(req.idempotency_key or "")[:16] + "…")
        return IngestResponse(**idem_hit.response_json)

    # Content dedup: same file already ingested.
    content_sha256 = req.content_sha256 or hashlib.sha256(req.text.encode("utf-8")).hexdigest()
    existing = find_by_sha256(db, tenant_id=tenant_id, content_sha256=content_sha256)
    if existing is not None:
        raise HTTPException(
            409,
            f"מסמך עם תוכן זהה כבר קיים במאגר: {existing.filename!r} "
            f"(מזהה {existing.id}). לא בוצעה קליטה כפולה.",
        )

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
        content_sha256=content_sha256,
    )
    db.add(doc)
    try:
        db.flush()  # get the id without committing
    except IntegrityError:
        # Race: two callers passed the SELECT above, one lost the insert.
        # Return the winner's doc as a 409 — same shape the pre-check emits.
        winner = handle_sha256_race(db, tenant_id=tenant_id, content_sha256=content_sha256)
        if winner is not None:
            raise HTTPException(
                409,
                f"מסמך עם תוכן זהה נקלט על ידי בקשה מקבילה: {winner.filename!r} "
                f"(מזהה {winner.id}).",
            ) from None
        raise

    structural_chunks = chunk_document(req.text)
    if not structural_chunks:
        raise HTTPException(400, "Document produced no chunks.")

    embeddings = embed_texts(
        [
            build_contextual_input(
                text=sc.text, section_path=sc.section_path, document_title=req.filename
            )
            for sc in structural_chunks
        ]
    )

    for sc, embedding in zip(structural_chunks, embeddings, strict=True):
        chunk = Chunk(
            document_id=doc.id,
            tenant_id=tenant_id,
            position=sc.position,
            section_path=sc.section_path,
            section_ref=canonical_section_ref(sc.section_path),
            text=sc.text,
            embedding=embedding,
            chunk_metadata={"decision_type": sc.decision_type} if sc.decision_type else None,
        )
        db.add(chunk)
        db.flush()
        db.execute(
            text("UPDATE chunks SET text_search = to_tsvector('simple', :norm) WHERE id = :cid"),
            {"cid": chunk.id, "norm": normalize_hebrew(sc.text)},
        )

    doc.chunks_created = len(structural_chunks)
    db.commit()

    # Auto-classify in the background so cryptic filenames get human Hebrew
    # titles + a summary + doc_type without the user having to click anything.
    if req.auto_classify:
        background_tasks.add_task(classify_document_by_id_bg, doc.id)

    log.info(
        "ingest.complete",
        document_id=str(doc.id),
        chunks=len(structural_chunks),
        with_section_path=sum(1 for c in structural_chunks if c.section_path),
        auto_classify=req.auto_classify,
    )
    response = IngestResponse(
        document_id=doc.id,
        chunks_created=len(structural_chunks),
        used_ocr=req.used_ocr,
        extractor=req.extractor,
        note=req.extraction_note,
        pages=req.pages,
        chars_extracted=len(req.text),
        partial=req.extraction_partial,
    )
    record_idempotency(
        db,
        tenant_id=tenant_id,
        key=req.idempotency_key,
        document_id=doc.id,
        response_json=response.model_dump(mode="json"),
    )
    db.commit()
    return response


@router.post("/upload", response_model=IngestResponse)
async def ingest_upload(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    doc_type: str | None = Form(None),
    prefer_ocr: bool | None = Form(None),
    auto_classify: bool = Form(True),
    x_content_sha256: str | None = Header(None),
    x_idempotency_key: str | None = Header(None),
    db: Session = Depends(get_db),
    user: IdentityUser = Depends(current_user),
) -> IngestResponse:
    """Accept a file upload (txt/md/docx/pdf), extract text (with OCR fallback for scanned PDFs),
    chunk + embed + store. Returns chunks_created + extractor metadata.

    For PDFs we default prefer_ocr=True: this corpus is overwhelmingly scanned
    Hebrew documents where pdfplumber returns either nothing or RTL-reversed
    garbage. Callers can pass prefer_ocr=false to override for clean native PDFs.
    """
    filename = file.filename or "uploaded"
    suffix = Path(filename).suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise HTTPException(
            400, f"Unsupported file type: {suffix}. Supported: {sorted(SUPPORTED_EXTENSIONS)}"
        )

    resolved_tenant = user.tenant_id

    # Layer 1 — Idempotency key. Same *attempt* replayed (network flake,
    # double-click) → return the stored response without re-processing.
    idem_hit = find_by_idempotency_key(
        db, tenant_id=resolved_tenant, key=x_idempotency_key or ""
    )
    if idem_hit is not None and idem_hit.response_json:
        log.info(
            "ingest_upload.idempotency_hit",
            key=(x_idempotency_key or "")[:16] + "…",
        )
        return IngestResponse(**idem_hit.response_json)

    # Layer 2 — Client-provided content hash. If the browser hashed the
    # file before POSTing, we can reject 409 without reading the multipart
    # body (saves bandwidth on retries of large PDFs).
    if x_content_sha256:
        existing = find_by_sha256(
            db, tenant_id=resolved_tenant, content_sha256=x_content_sha256.strip().lower()
        )
        if existing is not None:
            raise HTTPException(
                409,
                f"קובץ עם תוכן זהה כבר קיים במאגר: {existing.filename!r} "
                f"(מזהה {existing.id}). לא בוצעה קליטה כפולה.",
            )

    # Read the raw upload bytes once — we need them for the dedup hash check
    # BEFORE spending 30-60s on extraction, and again later to persist the
    # original file to disk via save_original().
    contents = await file.read()

    # Layer 3 — Server-computed hash. Recheck (in case client didn't send
    # X-Content-SHA256, or sent it wrong) BEFORE spending 30-60s on extraction.
    content_sha256 = hashlib.sha256(contents).hexdigest()
    existing = find_by_sha256(
        db, tenant_id=resolved_tenant, content_sha256=content_sha256
    )
    if existing is not None:
        raise HTTPException(
            409,
            f"קובץ עם תוכן זהה כבר קיים במאגר: {existing.filename!r} "
            f"(מזהה {existing.id}). לא בוצעה קליטה כפולה.",
        )

    # Save to a temp file so the existing extraction service can use Path-based APIs
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(contents)
        tmp_path = Path(tmp.name)

    # Default to OCR for PDFs — see docstring for rationale.
    use_ocr = prefer_ocr if prefer_ocr is not None else (suffix == ".pdf")

    # Extraction is fully synchronous (Azure SDK + pymupdf + pdfplumber) and can
    # take 30-60s on a multi-page scanned PDF. Run it in a worker thread so the
    # event loop stays free to answer /api/health — otherwise Render thinks the
    # instance is dead and restarts the worker mid-upload.
    try:
        extraction = await asyncio.to_thread(extract_file, tmp_path, prefer_ocr=use_ocr)
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
        content_sha256=content_sha256,
    )
    db.add(doc)
    try:
        db.flush()
    except IntegrityError:
        # Layer 3-final — the DB unique constraint (migration 0018, held
        # until existing duplicates are cleaned) rejected our insert
        # because a concurrent request slipped between our pre-check and
        # this flush. Return the winner as a 409.
        winner = handle_sha256_race(
            db, tenant_id=resolved_tenant, content_sha256=content_sha256
        )
        if winner is not None:
            raise HTTPException(
                409,
                f"קובץ עם תוכן זהה נקלט על ידי בקשה מקבילה: {winner.filename!r} "
                f"(מזהה {winner.id}).",
            ) from None
        raise

    # Persist the original file for later in-browser viewing (click-a-citation
    # → open the source). Runs after extraction sanity-checks so failed
    # uploads don't fill the disk. Non-fatal — if the disk isn't reachable
    # for some reason we still ingest the text.
    try:
        doc.source_uri = save_original(
            tenant_id=resolved_tenant,
            document_id=doc.id,
            suffix=suffix,
            contents=contents,
        )
    except OSError as e:
        log.warning("ingest.save_original_failed", error=str(e), doc_id=str(doc.id))

    # Chunking + embedding are also synchronous and can be slow (Cohere call
    # latency + tokenizer). Push them off the event loop too.
    structural_chunks = await asyncio.to_thread(chunk_document, extraction.text)
    if not structural_chunks:
        raise HTTPException(400, "Document produced no chunks.")

    contextual_inputs = [
        build_contextual_input(
            text=sc.text, section_path=sc.section_path, document_title=filename
        )
        for sc in structural_chunks
    ]
    embeddings = await asyncio.to_thread(embed_texts, contextual_inputs)

    for sc, embedding in zip(structural_chunks, embeddings, strict=True):
        chunk = Chunk(
            document_id=doc.id,
            tenant_id=resolved_tenant,
            position=sc.position,
            section_path=sc.section_path,
            section_ref=canonical_section_ref(sc.section_path),
            text=sc.text,
            embedding=embedding,
            chunk_metadata={"decision_type": sc.decision_type} if sc.decision_type else None,
        )
        db.add(chunk)
        db.flush()
        db.execute(
            text("UPDATE chunks SET text_search = to_tsvector('simple', :norm) WHERE id = :cid"),
            {"cid": chunk.id, "norm": normalize_hebrew(sc.text)},
        )

    doc.chunks_created = len(structural_chunks)
    db.commit()

    # Auto-classify in the background — see /ingest for rationale.
    if auto_classify:
        background_tasks.add_task(classify_document_by_id_bg, doc.id)

    log.info(
        "ingest.upload_complete",
        document_id=str(doc.id),
        chunks=len(structural_chunks),
        extractor=extraction.extractor,
        used_ocr=extraction.used_ocr,
        pages=extraction.pages,
        chars=len(extraction.text),
        auto_classify=auto_classify,
    )
    response = IngestResponse(
        document_id=doc.id,
        chunks_created=len(structural_chunks),
        used_ocr=extraction.used_ocr,
        extractor=extraction.extractor,
        note=extraction.note,
        pages=extraction.pages,
        chars_extracted=len(extraction.text),
        partial=extraction.partial,
    )
    record_idempotency(
        db,
        tenant_id=resolved_tenant,
        key=x_idempotency_key,
        document_id=doc.id,
        response_json=response.model_dump(mode="json"),
    )
    db.commit()
    return response
