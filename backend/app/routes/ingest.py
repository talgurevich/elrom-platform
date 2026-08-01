"""Ingest endpoints — text body or file upload, both share the same indexing path."""
import asyncio
import hashlib
from pathlib import Path
from uuid import UUID

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, Header, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.models import Chunk, CorpusFlag, Document, IngestJob
from app.services.identity import IdentityUser, current_user
from app.routes.documents import classify_document_by_id_bg
from app.services.chunking import build_contextual_input, canonical_section_ref, chunk_document
from app.services.embedding import embed_texts
from app.services.corpus_stats import invalidate_corpus_stats
from app.services.hebrew_text import normalize_filename_for_tsvector, normalize_hebrew
from app.services.extraction import SUPPORTED_EXTENSIONS
from app.services.ingest_pipeline import IngestRejection, run_upload_pipeline
from app.services.text_dedup import find_text_duplicate, hash_normalized
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

    text_sha = hash_normalized(req.text)

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
        text_sha256=text_sha,
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

    db.execute(
        text("UPDATE documents SET title_search = to_tsvector('simple', :norm) WHERE id = :did"),
        {"did": doc.id, "norm": normalize_filename_for_tsvector(doc.filename)},
    )

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
    invalidate_corpus_stats(tenant_id)

    if text_sha:
        try:
            existing_dup = find_text_duplicate(
                db,
                tenant_id=tenant_id,
                text_sha256=text_sha,
                exclude_doc_id=doc.id,
            )
            if existing_dup is not None:
                db.add(
                    CorpusFlag(
                        tenant_id=tenant_id,
                        new_doc_id=doc.id,
                        existing_doc_id=existing_dup.id,
                        kind="duplicates",
                        topic="duplicate_text_hash",
                        explanation=(
                            "טקסט מנורמל זהה למסמך קיים "
                            f"({existing_dup.filename!r})."
                        ),
                        confidence=1.0,
                        status="pending",
                        extractor_model="text_sha256_exact",
                    )
                )
                db.commit()
                log.info(
                    "ingest.text_hash_duplicate_flagged",
                    document_id=str(doc.id),
                    duplicate_of=str(existing_dup.id),
                )
        except Exception as e:
            log.warning(
                "ingest.text_hash_flag_failed",
                document_id=str(doc.id),
                error=str(e)[:200],
            )
            db.rollback()

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

    # Read the raw upload bytes once — dedup hash check + pipeline input.
    contents = await file.read()

    # Default to OCR for PDFs — see docstring for rationale.
    use_ocr = prefer_ocr if prefer_ocr is not None else (suffix == ".pdf")

    # The shared pipeline (extraction → checks → persist → chunk → embed →
    # index) is fully synchronous and can take 30-60s on a scanned PDF. Run
    # it in a worker thread so the event loop stays free for /api/health.
    # Identical logic to the async job path — see services/ingest_pipeline.
    try:
        outcome = await asyncio.to_thread(
            run_upload_pipeline,
            db,
            tenant_id=resolved_tenant,
            filename=filename,
            suffix=suffix,
            contents=contents,
            prefer_ocr=use_ocr,
            doc_type=doc_type,
        )
    except IngestRejection as e:
        raise HTTPException(e.status_code, e.detail) from None

    # Auto-classify in the background — see /ingest for rationale.
    if auto_classify:
        background_tasks.add_task(classify_document_by_id_bg, outcome.document_id)

    response = IngestResponse(
        document_id=outcome.document_id,
        chunks_created=outcome.chunks_created,
        used_ocr=outcome.used_ocr,
        extractor=outcome.extractor,
        note=outcome.note,
        pages=outcome.pages,
        chars_extracted=outcome.chars_extracted,
        partial=outcome.partial,
    )
    record_idempotency(
        db,
        tenant_id=resolved_tenant,
        key=x_idempotency_key,
        document_id=outcome.document_id,
        response_json=response.model_dump(mode="json"),
    )
    db.commit()
    return response


# ─────────────────────────────────────────────────────────────────────────
# Async upload — job queue. POST /upload-async persists the file and
# returns 202 + job id immediately; the in-process worker (started at app
# startup) runs the same pipeline off-request. GET /jobs powers the
# server-side upload queue in the frontend.
# ─────────────────────────────────────────────────────────────────────────


class IngestJobOut(BaseModel):
    job_id: UUID
    filename: str
    status: str  # queued | processing | done | failed
    stage: str | None = None
    error: str | None = None
    document_id: UUID | None = None
    chunks_created: int | None = None
    created_at: str | None = None
    finished_at: str | None = None


def _job_out(j: IngestJob, *, chunks_created: int | None = None) -> IngestJobOut:
    return IngestJobOut(
        job_id=j.id,
        filename=j.filename,
        status=j.status,
        stage=j.stage,
        error=j.error,
        document_id=j.document_id,
        chunks_created=chunks_created,
        created_at=j.created_at.isoformat() if j.created_at else None,
        finished_at=j.finished_at.isoformat() if j.finished_at else None,
    )


def _chunks_for_job(db: Session, j: IngestJob) -> int | None:
    if j.document_id is None:
        return None
    doc = db.get(Document, j.document_id)
    return doc.chunks_created if doc else None


@router.post("/upload-async", response_model=IngestJobOut, status_code=202)
async def ingest_upload_async(
    file: UploadFile = File(...),
    doc_type: str | None = Form(None),
    prefer_ocr: bool | None = Form(None),
    auto_classify: bool = Form(True),
    x_content_sha256: str | None = Header(None),
    db: Session = Depends(get_db),
    user: IdentityUser = Depends(current_user),
) -> IngestJobOut:
    """Enqueue an upload for background processing. Returns immediately
    with a job id; poll GET /api/ingest/jobs/{job_id} for status.

    Duplicate rejection happens twice: cheaply here (content hash against
    existing documents) and authoritatively in the pipeline when the job
    runs — so racing identical uploads resolve to one document."""
    filename = file.filename or "uploaded"
    suffix = Path(filename).suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise HTTPException(
            400, f"Unsupported file type: {suffix}. Supported: {sorted(SUPPORTED_EXTENSIONS)}"
        )

    contents = await file.read()
    content_sha256 = hashlib.sha256(contents).hexdigest()
    existing = find_by_sha256(
        db, tenant_id=user.tenant_id, content_sha256=content_sha256
    )
    if existing is not None:
        raise HTTPException(
            409,
            f"קובץ עם תוכן זהה כבר קיים במאגר: {existing.filename!r} "
            f"(מזהה {existing.id}). לא בוצעה קליטה כפולה.",
        )

    queue_dir = Path(settings.storage_dir) / "ingest-queue"
    queue_dir.mkdir(parents=True, exist_ok=True)

    job = IngestJob(
        tenant_id=user.tenant_id,
        filename=filename,
        suffix=suffix,
        stored_path="",  # set below once we know the job id
        content_sha256=content_sha256,
        prefer_ocr=prefer_ocr if prefer_ocr is not None else (suffix == ".pdf"),
        auto_classify=auto_classify,
        doc_type=doc_type,
    )
    db.add(job)
    db.flush()
    stored = queue_dir / f"{job.id}{suffix}"
    stored.write_bytes(contents)
    job.stored_path = str(stored)
    db.commit()

    log.info(
        "ingest.job_enqueued",
        job_id=str(job.id),
        filename=filename,
        bytes=len(contents),
    )
    return _job_out(job)


@router.get("/jobs/{job_id}", response_model=IngestJobOut)
def get_ingest_job(
    job_id: UUID,
    db: Session = Depends(get_db),
    user: IdentityUser = Depends(current_user),
) -> IngestJobOut:
    job = db.get(IngestJob, job_id)
    if job is None or job.tenant_id != user.tenant_id:
        raise HTTPException(404, "Job not found")
    return _job_out(job, chunks_created=_chunks_for_job(db, job))


@router.get("/jobs", response_model=list[IngestJobOut])
def list_ingest_jobs(
    db: Session = Depends(get_db),
    user: IdentityUser = Depends(current_user),
    limit: int = 30,
) -> list[IngestJobOut]:
    """Recent jobs for the tenant, newest first — the server-side truth
    behind the upload queue UI (survives page reloads, unlike the old
    client-side queue)."""
    rows = (
        db.query(IngestJob)
        .filter(IngestJob.tenant_id == user.tenant_id)
        .order_by(IngestJob.created_at.desc())
        .limit(min(limit, 100))
        .all()
    )
    return [_job_out(j, chunks_created=_chunks_for_job(db, j)) for j in rows]
