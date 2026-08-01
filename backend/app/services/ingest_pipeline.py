"""Shared upload-ingestion pipeline — one implementation for two callers.

Callers:
  * routes/ingest.py POST /upload         — the legacy synchronous path.
  * services/ingest_worker.py             — the async job queue (POST
    /upload-async enqueues, the worker processes off-request).

Extracting this from the endpoint is what makes the job queue safe to
introduce: both paths run byte-identical logic, so moving a client from
sync to async cannot change ingestion semantics.

Raises IngestRejection for business-rule refusals (dedup hit, empty
extraction, low OCR density, partial extraction). The sync endpoint maps
it to an HTTPException with the carried status code; the worker maps it
to job.status='failed' with the Hebrew detail as the error message.
"""
import hashlib
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from uuid import UUID

import structlog
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Chunk, CorpusFlag, Document
from app.services.chunking import (
    build_contextual_input,
    canonical_section_ref,
    chunk_document,
)
from app.services.corpus_stats import invalidate_corpus_stats
from app.services.embedding import current_embedding_model, embed_texts
from app.services.extraction import extract_text as extract_file
from app.services.hebrew_text import normalize_filename_for_tsvector, normalize_hebrew
from app.services.storage import save_original
from app.services.text_dedup import find_text_duplicate, hash_normalized
from app.services.upload_dedup import find_by_sha256, handle_sha256_race

log = structlog.get_logger()

# Refuse to persist a PDF that yielded fewer chars per page than this — almost
# always means OCR mostly failed or the file was scanned without OCR configured.
MIN_CHARS_PER_PAGE = 200


class IngestRejection(Exception):
    """A business-rule refusal (not an infrastructure error)."""

    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


@dataclass
class UploadOutcome:
    document_id: UUID
    chunks_created: int
    used_ocr: bool
    extractor: str | None
    note: str | None
    pages: int | None
    chars_extracted: int
    partial: bool


def run_upload_pipeline(
    db: Session,
    *,
    tenant_id: UUID,
    filename: str,
    suffix: str,
    contents: bytes,
    prefer_ocr: bool,
    doc_type: str | None = None,
    stage_cb: Callable[[str], None] | None = None,
) -> UploadOutcome:
    """Extract → validate → persist → chunk → embed → index. Synchronous;
    callers run it off the event loop (asyncio.to_thread / worker thread).

    ``stage_cb`` — invoked with "extracting" / "chunking" / "embedding" /
    "finalizing" as the pipeline advances; the job worker uses it to update
    the job row so the UI can show real progress.
    """

    def _stage(name: str) -> None:
        if stage_cb is not None:
            try:
                stage_cb(name)
            except Exception:  # noqa: BLE001 — progress reporting must not kill the job
                pass

    # Server-computed content hash dedup (Layer 3 in the endpoint's terms —
    # layers 1-2 are request-shaped and stay in the route).
    content_sha256 = hashlib.sha256(contents).hexdigest()
    existing = find_by_sha256(db, tenant_id=tenant_id, content_sha256=content_sha256)
    if existing is not None:
        raise IngestRejection(
            409,
            f"קובץ עם תוכן זהה כבר קיים במאגר: {existing.filename!r} "
            f"(מזהה {existing.id}). לא בוצעה קליטה כפולה.",
        )

    _stage("extracting")
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(contents)
        tmp_path = Path(tmp.name)
    try:
        extraction = extract_file(tmp_path, prefer_ocr=prefer_ocr)
    finally:
        try:
            tmp_path.unlink()
        except OSError:
            pass

    if not extraction.text.strip():
        raise IngestRejection(
            400, extraction.note or "No text could be extracted from the file."
        )

    if extraction.pages and extraction.pages > 0:
        density = len(extraction.text) / extraction.pages
        if density < MIN_CHARS_PER_PAGE:
            raise IngestRejection(
                400,
                f"Refusing to ingest {filename}: {len(extraction.text)} chars across "
                f"{extraction.pages} pages ({density:.0f}/page < {MIN_CHARS_PER_PAGE}). "
                f"Likely OCR failure. {extraction.note or ''}".strip(),
            )
    if extraction.partial:
        raise IngestRejection(
            400,
            f"Refusing to ingest {filename}: extraction was partial. {extraction.note}",
        )

    # Cross-format duplicate detection: hash the normalized extracted text.
    text_sha = hash_normalized(extraction.text)

    doc = Document(
        tenant_id=tenant_id,
        filename=filename,
        doc_type=doc_type,
        extractor=extraction.extractor,
        used_ocr=extraction.used_ocr,
        pages=extraction.pages,
        chars_extracted=len(extraction.text),
        extraction_partial=extraction.partial,
        extraction_note=extraction.note,
        content_sha256=content_sha256,
        text_sha256=text_sha,
        embedding_model=current_embedding_model(),
    )
    db.add(doc)
    try:
        db.flush()
    except IntegrityError:
        winner = handle_sha256_race(
            db, tenant_id=tenant_id, content_sha256=content_sha256
        )
        if winner is not None:
            raise IngestRejection(
                409,
                f"קובץ עם תוכן זהה נקלט על ידי בקשה מקבילה: {winner.filename!r} "
                f"(מזהה {winner.id}).",
            ) from None
        raise

    db.execute(
        text("UPDATE documents SET title_search = to_tsvector('simple', :norm) WHERE id = :did"),
        {"did": doc.id, "norm": normalize_filename_for_tsvector(doc.filename)},
    )

    # Persist the original file for later in-browser viewing. Non-fatal.
    try:
        doc.source_uri = save_original(
            tenant_id=tenant_id,
            document_id=doc.id,
            suffix=suffix,
            contents=contents,
        )
    except OSError as e:
        log.warning("ingest_pipeline.save_original_failed", error=str(e), doc_id=str(doc.id))

    _stage("chunking")
    structural_chunks = chunk_document(extraction.text)
    if not structural_chunks:
        raise IngestRejection(400, "Document produced no chunks.")

    _stage("embedding")
    contextual_inputs = [
        build_contextual_input(
            text=sc.text, section_path=sc.section_path, document_title=filename
        )
        for sc in structural_chunks
    ]
    embeddings = embed_texts(contextual_inputs)

    _stage("finalizing")
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

    # Cross-format dup flag — soft, reviewer-confirmed, never a reject.
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
                            f"({existing_dup.filename!r}). ייתכנו גרסאות "
                            "PDF/DOCX של אותו מסמך, סריקה חוזרת, או ייצוא חוזר."
                        ),
                        confidence=1.0,
                        status="pending",
                        extractor_model="text_sha256_exact",
                    )
                )
                db.commit()
                log.info(
                    "ingest_pipeline.text_hash_duplicate_flagged",
                    document_id=str(doc.id),
                    duplicate_of=str(existing_dup.id),
                )
        except Exception as e:  # noqa: BLE001 — flagging is best-effort
            log.warning(
                "ingest_pipeline.text_hash_flag_failed",
                document_id=str(doc.id),
                error=str(e)[:200],
            )
            db.rollback()

    log.info(
        "ingest_pipeline.complete",
        document_id=str(doc.id),
        chunks=len(structural_chunks),
        extractor=extraction.extractor,
        used_ocr=extraction.used_ocr,
        pages=extraction.pages,
        chars=len(extraction.text),
    )
    return UploadOutcome(
        document_id=doc.id,
        chunks_created=len(structural_chunks),
        used_ocr=extraction.used_ocr,
        extractor=extraction.extractor,
        note=extraction.note,
        pages=extraction.pages,
        chars_extracted=len(extraction.text),
        partial=extraction.partial,
    )
