"""Document management endpoints — list, delete, and AI-classify."""
import json
import re
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query as QParam
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.models import Chunk, Document, Tenant, User
from app.routes.auth import current_user

log = structlog.get_logger()
router = APIRouter()


HEBREW_RE = re.compile(r"[֐-׿]")


def _has_meaningful_name(filename: str) -> bool:
    """Heuristic: a 'good' filename has ≥3 Hebrew chars and isn't dominated by hex."""
    if not filename:
        return False
    hebrew_chars = len(HEBREW_RE.findall(filename))
    return hebrew_chars >= 3


class DocumentItem(BaseModel):
    id: UUID
    filename: str
    doc_type: str | None
    chunks: int
    chars: int
    ingested_at: str
    summary: str | None = None
    ai_classified: bool = False
    # Extraction telemetry — populated on ingest, lets the UI flag bad ingests.
    extractor: str | None = None
    used_ocr: bool = False
    pages: int | None = None
    chars_extracted: int | None = None
    extraction_partial: bool = False
    extraction_note: str | None = None
    quality: str = "unknown"  # ok | low_density | partial | suspect | unknown


def _quality_verdict(
    *,
    chars_extracted: int | None,
    pages: int | None,
    extraction_partial: bool,
    chunks: int,
) -> str:
    """Cheap quality summary from telemetry. Returns one of:
       ok | partial | low_density | suspect | unknown.
    """
    if chars_extracted is None and pages is None:
        return "unknown"  # legacy doc, ingested before telemetry
    if extraction_partial:
        return "partial"
    if pages and chars_extracted is not None:
        density = chars_extracted / pages if pages else 0
        if density < 200:
            return "low_density"
    if chunks == 0:
        return "suspect"
    return "ok"


@router.get("", response_model=list[DocumentItem])
def list_documents(
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> list[DocumentItem]:
    """List documents for the caller's tenant with chunk + char counts."""
    tenant_id = user.tenant_id

    stmt = (
        select(
            Document.id,
            Document.filename,
            Document.doc_type,
            Document.ingested_at,
            Document.doc_metadata,
            Document.extractor,
            Document.used_ocr,
            Document.pages,
            Document.chars_extracted,
            Document.extraction_partial,
            Document.extraction_note,
            func.count(Chunk.id).label("chunks"),
            func.coalesce(func.sum(func.length(Chunk.text)), 0).label("chars"),
        )
        .join(Chunk, Chunk.document_id == Document.id, isouter=True)
        .where(Document.tenant_id == tenant_id)
        .group_by(Document.id)
        .order_by(Document.ingested_at.desc())
    )
    rows = db.execute(stmt).all()

    return [
        DocumentItem(
            id=r.id,
            filename=r.filename,
            doc_type=r.doc_type,
            chunks=int(r.chunks),
            chars=int(r.chars),
            ingested_at=r.ingested_at.isoformat() if r.ingested_at else "",
            summary=(r.doc_metadata or {}).get("summary") if r.doc_metadata else None,
            ai_classified=bool((r.doc_metadata or {}).get("ai_classified")) if r.doc_metadata else False,
            extractor=r.extractor,
            used_ocr=bool(r.used_ocr),
            pages=r.pages,
            chars_extracted=r.chars_extracted,
            extraction_partial=bool(r.extraction_partial),
            extraction_note=r.extraction_note,
            quality=_quality_verdict(
                chars_extracted=r.chars_extracted,
                pages=r.pages,
                extraction_partial=bool(r.extraction_partial),
                chunks=int(r.chunks),
            ),
        )
        for r in rows
    ]


@router.delete("")
def delete_all_documents(
    confirm: bool = QParam(False, description="Must be true to actually delete."),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict:
    """Wipe every document (and its chunks via cascade) for the caller's tenant.

    Requires confirm=true. Returns how many docs/chunks were deleted.
    """
    if not confirm:
        raise HTTPException(400, "Pass confirm=true to actually delete all documents.")
    tenant_id = user.tenant_id

    docs = db.query(Document).filter(Document.tenant_id == tenant_id).all()
    n_docs = len(docs)
    n_chunks = (
        db.query(func.count(Chunk.id)).filter(Chunk.tenant_id == tenant_id).scalar() or 0
    )
    for d in docs:
        db.delete(d)
    db.commit()
    log.info("documents.delete_all", tenant_id=str(tenant_id), docs=n_docs, chunks=n_chunks)
    return {"status": "ok", "documents_deleted": n_docs, "chunks_deleted": int(n_chunks)}


class ClassifyResult(BaseModel):
    document_id: UUID
    old_filename: str
    new_filename: str
    doc_type: str | None
    summary: str | None
    skipped: bool
    reason: str | None = None


class ClassifySummary(BaseModel):
    total: int
    classified: int
    skipped: int
    results: list[ClassifyResult]


_CLASSIFY_SYSTEM = """אתה מסווג מסמכים של קיבוץ אל-רום. קבל קטע מתחילת המסמך וחזור JSON תקין (ללא markdown) עם 3 שדות:
{
  "title": "כותרת קצרה בעברית, 3-8 מילים, שמתארת את התוכן (למשל: 'תקנון שיוך דירות', 'פרוטוקול אסיפה 23.11.2022', 'החלטה על נוהל הקדמה לקומה שנייה')",
  "doc_type": "אחד מ: bylaw, sub_bylaw, minutes, decision, other",
  "summary": "משפט אחד עד שניים על מה המסמך, בעברית"
}
אם זה תקנון משנה ספציפי (שיוך דירות / שיוך נכסים / פירות נכסים / סיעוד / קליטה / רווחה / פנסיה וכד') — doc_type = sub_bylaw.
אם זה התקנון הראשי הכללי — doc_type = bylaw.
אם זה פרוטוקול אסיפה — doc_type = minutes.
אם זו החלטה ספציפית — doc_type = decision.
אחרת — other.
JSON בלבד, ללא הסברים, ללא ```fences."""


def classify_one_document(db: Session, doc: Document, *, force: bool = False) -> dict:
    """Classify a single document — extract title, doc_type, summary via Claude.

    Mutates `doc` in place and commits. Used both by the bulk classify endpoint
    and by the post-upload background task. Returns a small dict for logging.

    Errors are caught and logged — never raised — because this runs in a
    background task where there's no caller to surface the error to.
    """
    from anthropic import Anthropic

    meta = doc.doc_metadata or {}
    already = bool(meta.get("ai_classified"))
    has_name = _has_meaningful_name(doc.filename)

    if not force and already:
        return {"status": "skipped", "reason": "already_classified"}

    chunks = (
        db.query(Chunk)
        .filter(Chunk.document_id == doc.id)
        .order_by(Chunk.position)
        .limit(8)
        .all()
    )
    sample = "\n\n".join(c.text for c in chunks)[:4000]
    if not sample.strip():
        return {"status": "skipped", "reason": "no_text"}

    try:
        client = Anthropic(api_key=settings.anthropic_api_key)
        resp = client.messages.create(
            model=settings.claude_extract_model,
            max_tokens=400,
            system=_CLASSIFY_SYSTEM,
            messages=[{"role": "user", "content": sample}],
        )
        raw = resp.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.strip("`").lstrip("json").strip()
        data = json.loads(raw)
        title = str(data.get("title") or "").strip()
        doc_type = str(data.get("doc_type") or "").strip() or doc.doc_type
        summary = str(data.get("summary") or "").strip()

        new_filename = doc.filename
        original_filename = meta.get("original_filename") or doc.filename
        if title and not has_name:
            ext = "." + doc.filename.rsplit(".", 1)[1] if "." in doc.filename else ""
            new_filename = f"{title}{ext}"
            doc.filename = new_filename
        if doc_type:
            doc.doc_type = doc_type
        doc.doc_metadata = {
            **meta,
            "ai_classified": True,
            "ai_title": title,
            "summary": summary,
            "original_filename": original_filename,
        }
        db.commit()
        return {
            "status": "ok",
            "old_filename": original_filename,
            "new_filename": new_filename,
            "doc_type": doc.doc_type,
        }
    except Exception as e:
        log.warning("documents.classify_failed", doc_id=str(doc.id), err=str(e))
        return {"status": "error", "error": str(e)[:200]}


def classify_document_by_id_bg(document_id: UUID) -> None:
    """Background-task entrypoint: opens its own DB session so it survives the
    request lifecycle, then classifies the document.
    """
    from app.db import SessionLocal

    db: Session = SessionLocal()
    try:
        doc = db.get(Document, document_id)
        if doc is None:
            log.warning("documents.classify_bg.doc_missing", document_id=str(document_id))
            return
        result = classify_one_document(db, doc)
        log.info(
            "documents.classify_bg.done",
            document_id=str(document_id),
            **{k: v for k, v in result.items() if k != "status"},
            status=result["status"],
        )
    except Exception as e:
        log.error("documents.classify_bg.crashed", document_id=str(document_id), err=str(e))
    finally:
        db.close()


@router.post("/classify", response_model=ClassifySummary)
def classify_documents(
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
    force: bool = QParam(False, description="Re-classify even already-classified docs"),
) -> ClassifySummary:
    """Walk every document in the caller's tenant and classify any that need it.
    Mostly a manual backstop / reclassify-everything button — new uploads
    classify themselves automatically via a background task in /ingest/upload."""
    docs = db.query(Document).filter(Document.tenant_id == user.tenant_id).all()
    results: list[ClassifyResult] = []
    classified = 0

    for doc in docs:
        original_filename = (doc.doc_metadata or {}).get("original_filename") or doc.filename
        outcome = classify_one_document(db, doc, force=force)
        if outcome["status"] == "ok":
            classified += 1
            results.append(
                ClassifyResult(
                    document_id=doc.id,
                    old_filename=outcome["old_filename"],
                    new_filename=outcome["new_filename"],
                    doc_type=outcome["doc_type"],
                    summary=(doc.doc_metadata or {}).get("summary"),
                    skipped=False,
                )
            )
        else:
            results.append(
                ClassifyResult(
                    document_id=doc.id,
                    old_filename=original_filename,
                    new_filename=doc.filename,
                    doc_type=doc.doc_type,
                    summary=(doc.doc_metadata or {}).get("summary"),
                    skipped=True,
                    reason=outcome.get("reason") or outcome.get("error"),
                )
            )

    return ClassifySummary(
        total=len(docs),
        classified=classified,
        skipped=len(docs) - classified,
        results=results,
    )


_HEBREW_RE = re.compile(r"[֐-׿]")
_LTR_TOKEN = re.compile(r"[0-9A-Za-z\.\-_/]+")


def _fix_rtl_line(line: str) -> str:
    """Reverse a visually-LTR-ordered RTL line back to logical order.

    Azure OCR sometimes emits Hebrew PDFs in visual order: each line is read
    left-to-right character-by-character, so the Hebrew words end up reversed.
    Embedded LTR runs (digits, Latin, punctuation) are also visually reversed
    by the OCR, so after we flip the whole line we re-reverse those runs.
    """
    reversed_line = line[::-1]
    reversed_line = _LTR_TOKEN.sub(lambda m: m.group(0)[::-1], reversed_line)
    reversed_line = re.sub(r" +", " ", reversed_line).strip()
    return reversed_line


def _fix_rtl_text(text: str) -> str:
    return "\n".join(_fix_rtl_line(line) for line in text.split("\n"))


class FixRtlSummary(BaseModel):
    document_id: UUID
    chunks_fixed: int
    sample_before: str
    sample_after: str


@router.post("/{document_id}/fix-rtl", response_model=FixRtlSummary)
def fix_rtl(
    document_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> FixRtlSummary:
    """Repair an RTL-reversed document in place: reverse each line of every
    chunk's text, then re-embed so the chunks become findable in search."""
    from app.services.embedding import embed_texts

    doc = db.get(Document, document_id)
    if doc is None or doc.tenant_id != user.tenant_id:
        raise HTTPException(404, "Document not found")

    chunks = (
        db.query(Chunk)
        .filter(Chunk.document_id == document_id)
        .order_by(Chunk.position)
        .all()
    )
    if not chunks:
        raise HTTPException(400, "Document has no chunks")

    sample_before = chunks[0].text[:200]
    new_texts: list[str] = []
    for c in chunks:
        fixed = _fix_rtl_text(c.text or "")
        c.text = fixed
        new_texts.append(fixed)

    # Re-embed with the corpus input type so retrieval matches future query
    # embeddings correctly.
    new_embeddings = embed_texts(new_texts, input_type="search_document")
    for c, emb in zip(chunks, new_embeddings, strict=True):
        c.embedding = emb

    db.commit()
    return FixRtlSummary(
        document_id=doc.id,
        chunks_fixed=len(chunks),
        sample_before=sample_before,
        sample_after=chunks[0].text[:200],
    )


class ChunkPreview(BaseModel):
    position: int
    section_path: str | None
    chars: int
    text: str


@router.get("/{document_id}/chunks", response_model=list[ChunkPreview])
def get_chunks(
    document_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> list[ChunkPreview]:
    """Return all chunks of a document with their text. For debugging chunking
    + OCR quality."""
    doc = db.get(Document, document_id)
    if doc is None or doc.tenant_id != user.tenant_id:
        raise HTTPException(404, "Document not found")
    chunks = (
        db.query(Chunk)
        .filter(Chunk.document_id == document_id)
        .order_by(Chunk.position)
        .all()
    )
    return [
        ChunkPreview(
            position=c.position,
            section_path=c.section_path,
            chars=len(c.text or ""),
            text=c.text or "",
        )
        for c in chunks
    ]


@router.delete("/{document_id}")
def delete_document(
    document_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict:
    """Delete a document and its chunks (queries that reference its chunks become orphaned but stay)."""
    doc = db.get(Document, document_id)
    if doc is None or doc.tenant_id != user.tenant_id:
        raise HTTPException(404, "Document not found")
    db.delete(doc)
    db.commit()
    log.info("documents.deleted", document_id=str(document_id))
    return {"status": "ok"}
