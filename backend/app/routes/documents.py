"""Document management endpoints — list, delete, and AI-classify."""
import json
import re
from datetime import date
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query as QParam
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.models import Chunk, Document, Tenant, User
from app.routes.auth import current_user
from app.services.storage import guess_content_type, resolve_stored_file

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
    folder: str | None = None  # AI-assigned topical folder
    # Extraction telemetry — populated on ingest, lets the UI flag bad ingests.
    extractor: str | None = None
    used_ocr: bool = False
    pages: int | None = None
    chars_extracted: int | None = None
    extraction_partial: bool = False
    extraction_note: str | None = None
    quality: str = "unknown"  # ok | low_density | partial | suspect | unknown
    # AI-extracted / user-editable metadata surfaced for the review dialog and
    # the retrieval-time date filters.
    effective_date: str | None = None  # canonical column, ISO YYYY-MM-DD
    document_date: str | None = None   # date printed on the doc
    meeting_number: str | None = None
    decision_number: str | None = None
    bylaw_section_range: str | None = None
    parties: list[str] | None = None
    metadata_reviewed: bool = False  # user confirmed via the review dialog
    has_file: bool = False  # true if the original upload is stored & viewable


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
            Document.folder,
            Document.effective_date,
            Document.source_uri,
            func.count(Chunk.id).label("chunks"),
            func.coalesce(func.sum(func.length(Chunk.text)), 0).label("chars"),
        )
        .join(Chunk, Chunk.document_id == Document.id, isouter=True)
        .where(Document.tenant_id == tenant_id)
        .group_by(Document.id)
        .order_by(Document.ingested_at.desc())
    )
    rows = db.execute(stmt).all()

    def _md(r) -> dict:
        return r.doc_metadata or {}

    return [
        DocumentItem(
            id=r.id,
            filename=r.filename,
            doc_type=r.doc_type,
            chunks=int(r.chunks),
            chars=int(r.chars),
            ingested_at=r.ingested_at.isoformat() if r.ingested_at else "",
            summary=_md(r).get("summary"),
            ai_classified=bool(_md(r).get("ai_classified")),
            folder=r.folder,
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
            effective_date=r.effective_date.isoformat() if r.effective_date else None,
            document_date=_md(r).get("document_date"),
            meeting_number=_md(r).get("meeting_number"),
            decision_number=_md(r).get("decision_number"),
            bylaw_section_range=_md(r).get("bylaw_section_range"),
            parties=_md(r).get("parties"),
            metadata_reviewed=bool(_md(r).get("metadata_reviewed")),
            has_file=bool(r.source_uri and str(r.source_uri).startswith("file://")),
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


_CLASSIFY_SYSTEM_BASE = """אתה מסווג מסמכים של קיבוץ אל-רום. קבל קטע מתחילת המסמך וחזור JSON תקין (ללא markdown) עם השדות הבאים. שדות שאינם רלוונטיים או שלא נמצאו במסמך — החזר null.
{
  "title": "כותרת קצרה בעברית, 3-8 מילים, שמתארת את התוכן (למשל: 'תקנון שיוך דירות', 'פרוטוקול אסיפה 23.11.2022', 'החלטה על נוהל הקדמה לקומה שנייה')",
  "doc_type": "אחד מ: bylaw, sub_bylaw, minutes, decision, other",
  "folder": "שם תיקייה נושאית קצרה (1-2 מילים) בעברית — לדוגמה: 'פנסיה', 'קליטה', 'סיעוד', 'מבנה ארגוני', 'שיוך דירות'. לא 'תקנון פנסיה' (זה כותרת, לא תיקייה).",
  "summary": "משפט אחד עד שניים על מה המסמך, בעברית",
  "document_date": "התאריך המופיע על המסמך (תאריך חתימה / הדפסה / כתיבה), פורמט ISO YYYY-MM-DD. null אם לא מופיע.",
  "effective_date": "תאריך תוקף של המסמך (מתי הוא נכנס לתוקף / קיבל אישור). לרוב שווה ל-document_date עבור החלטות ופרוטוקולים. פורמט YYYY-MM-DD. null אם לא ניתן להסיק.",
  "meeting_number": "מספר ישיבה (רק ל-minutes) — לדוגמה '234' עבור 'ישיבת מזכירות מס' 234'. null אחרת.",
  "decision_number": "מספר החלטה (רק ל-decision) — לדוגמה '47/22'. null אחרת.",
  "bylaw_section_range": "טווח סעיפים (רק ל-bylaw / sub_bylaw) — לדוגמה 'סעיפים 12-18'. null אחרת.",
  "parties": "רשימת צדדים לחוזה (רק ל-other כשמדובר בחוזה/הסכם) — מערך מחרוזות. null אחרת."
}

doc_type:
- אם זה תקנון משנה ספציפי (שיוך דירות / שיוך נכסים / פירות נכסים / סיעוד / קליטה / רווחה / פנסיה וכד') — doc_type = sub_bylaw.
- אם זה התקנון הראשי הכללי — doc_type = bylaw.
- אם זה פרוטוקול אסיפה — doc_type = minutes.
- אם זו החלטה ספציפית — doc_type = decision.
- אחרת — other.

תאריכים עבריים (למשל "כ״ב בחשוון תשפ״ג") — המר לגרגוריאני אם ברור, אחרת null.

JSON בלבד, ללא הסברים, ללא ```fences."""


def _classify_system_prompt(existing_folders: list[str]) -> str:
    """The classifier prompt + a hint about already-used folder names so the
    model reuses them instead of inventing synonyms (פנסיה / פנסיוני /
    תקנון פנסיה)."""
    if not existing_folders:
        return _CLASSIFY_SYSTEM_BASE
    folder_list = "[" + ", ".join(f'"{f}"' for f in existing_folders) + "]"
    return (
        _CLASSIFY_SYSTEM_BASE
        + f"\n\nתיקיות קיימות במאגר: {folder_list}\n"
        + "אם המסמך שייך לאחת מהתיקיות הקיימות — השתמש בשם הקיים בדיוק. "
        + "רק אם הוא על נושא שאינו מיוצג — הצע שם חדש קצר."
    )


def _reembed_document_chunks(db: Session, doc: Document) -> int:
    """Regenerate embeddings for every chunk of `doc` using the current
    contextual format (document title + section_path prepended). Returns
    the number of chunks re-embedded.
    """
    from app.services.chunking import build_contextual_input
    from app.services.embedding import embed_texts

    chunks = (
        db.query(Chunk)
        .filter(Chunk.document_id == doc.id)
        .order_by(Chunk.position)
        .all()
    )
    if not chunks:
        return 0
    inputs = [
        build_contextual_input(
            text=c.text or "",
            section_path=c.section_path,
            document_title=doc.filename,
        )
        for c in chunks
    ]
    new_vecs = embed_texts(inputs, input_type="search_document")
    for c, v in zip(chunks, new_vecs, strict=True):
        c.embedding = v
    db.commit()
    return len(chunks)


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

    # Gather existing folders in this tenant so the model can reuse names.
    existing_folders = sorted(
        {
            f
            for (f,) in db.query(Document.folder)
            .filter(Document.tenant_id == doc.tenant_id)
            .filter(Document.folder.isnot(None))
            .distinct()
            .all()
            if f
        }
    )

    try:
        client = Anthropic(api_key=settings.anthropic_api_key)
        resp = client.messages.create(
            model=settings.claude_extract_model,
            max_tokens=500,
            system=_classify_system_prompt(existing_folders),
            messages=[{"role": "user", "content": sample}],
        )
        raw = resp.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.strip("`").lstrip("json").strip()
        data = json.loads(raw)
        title = str(data.get("title") or "").strip()
        doc_type = str(data.get("doc_type") or "").strip() or doc.doc_type
        folder = str(data.get("folder") or "").strip() or None
        summary = str(data.get("summary") or "").strip()

        # New structured metadata fields (all optional, all can be null).
        def _iso_date(v) -> str | None:
            if not v:
                return None
            s = str(v).strip()
            try:
                date.fromisoformat(s)
                return s
            except ValueError:
                return None

        document_date = _iso_date(data.get("document_date"))
        effective_date = _iso_date(data.get("effective_date")) or document_date
        meeting_number = (str(data.get("meeting_number")).strip() if data.get("meeting_number") else None)
        decision_number = (str(data.get("decision_number")).strip() if data.get("decision_number") else None)
        bylaw_section_range = (
            str(data.get("bylaw_section_range")).strip() if data.get("bylaw_section_range") else None
        )
        parties_raw = data.get("parties")
        parties = (
            [str(p).strip() for p in parties_raw if str(p).strip()]
            if isinstance(parties_raw, list)
            else None
        )

        new_filename = doc.filename
        original_filename = meta.get("original_filename") or doc.filename
        filename_changed = False
        if title and not has_name:
            ext = "." + doc.filename.rsplit(".", 1)[1] if "." in doc.filename else ""
            new_filename = f"{title}{ext}"
            doc.filename = new_filename
            filename_changed = original_filename != new_filename
        if doc_type:
            doc.doc_type = doc_type
        if folder:
            doc.folder = folder
        # effective_date lives on its own column — populate it if we extracted
        # something and it isn't already set by a human. (Never overwrite a
        # user-confirmed value with a fresh AI guess on re-classify.)
        user_reviewed = bool(meta.get("metadata_reviewed"))
        if effective_date and not user_reviewed:
            try:
                doc.effective_date = date.fromisoformat(effective_date)
            except ValueError:
                pass
        doc.doc_metadata = {
            **meta,
            "ai_classified": True,
            "ai_title": title,
            "summary": summary,
            "original_filename": original_filename,
            # Only overwrite structured fields when the user hasn't confirmed
            # them yet. Once metadata_reviewed=True, the user's edits win over
            # any future re-classification.
            **(
                {}
                if user_reviewed
                else {
                    "document_date": document_date,
                    "meeting_number": meeting_number,
                    "decision_number": decision_number,
                    "bylaw_section_range": bylaw_section_range,
                    "parties": parties,
                }
            ),
        }
        # Denormalize the doc's effective_date onto its chunks so retrieval
        # can filter/rank by date without a join. Chunks always mirror the
        # parent doc — no per-chunk overrides here.
        if doc.effective_date is not None:
            db.execute(
                update(Chunk)
                .where(Chunk.document_id == doc.id)
                .values(effective_date=doc.effective_date)
            )
        db.commit()

        # If the filename just changed from a cryptic hash to a real Hebrew
        # title, the contextual embeddings we built at ingest time are stale
        # (they bound the chunk to e.g. "505308920_90409efb1_1217.pdf" instead
        # of "תקנון פנסיה"). Re-embed in place so retrieval benefits from the
        # better title.
        reembedded = False
        if filename_changed:
            try:
                _reembed_document_chunks(db, doc)
                reembedded = True
            except Exception as e:
                log.warning(
                    "documents.classify.reembed_failed",
                    doc_id=str(doc.id),
                    err=str(e)[:200],
                )

        return {
            "status": "ok",
            "old_filename": original_filename,
            "new_filename": new_filename,
            "doc_type": doc.doc_type,
            "reembedded": reembedded,
        }
    except Exception as e:
        log.warning("documents.classify_failed", doc_id=str(doc.id), err=str(e))
        return {"status": "error", "error": str(e)[:200]}


def classify_document_by_id_bg(document_id: UUID) -> None:
    """Background-task entrypoint: opens its own DB session so it survives the
    request lifecycle, then classifies the document and — as a chained step —
    extracts any amendment edges to prior docs.

    Amendment extraction runs *after* classification so it sees the human
    Hebrew title + doc_type, which materially help the extractor recognise
    "this is a תקנון משנה that amends the main בבנון". If classification
    fails, we still attempt extraction against whatever state the doc is in.
    """
    from app.db import SessionLocal
    from app.services.amendment_extractor import extract_amendments

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
        # Chained amendment extraction — same background task, so it never
        # gets exposed as a separate button. Re-fetch the doc because
        # classify_one_document commits and may have mutated fields.
        doc = db.get(Document, document_id)
        if doc is not None:
            try:
                extract_result = extract_amendments(db, doc)
                log.info(
                    "documents.extract_bg.done",
                    document_id=str(document_id),
                    **extract_result,
                )
            except Exception as e:
                log.error(
                    "documents.extract_bg.crashed",
                    document_id=str(document_id),
                    err=str(e)[:300],
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


@router.get("/{document_id}/file")
def get_document_file(
    document_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> FileResponse:
    """Stream the original uploaded file back to the browser so users can
    click a citation and open the source PDF. Tenant-scoped; super-admins in
    switch-mode inherit the switched tenant's tenant_id via current_user.

    Only documents ingested after storage was wired up have a source_uri —
    older docs return 404 with a clear message and the frontend disables the
    open button for them.
    """
    doc = db.get(Document, document_id)
    if doc is None or doc.tenant_id != user.tenant_id:
        raise HTTPException(404, "Document not found")

    path = resolve_stored_file(doc.source_uri)
    if path is None:
        raise HTTPException(
            404,
            "אין קובץ מקור שמור למסמך זה. יש להעלות מחדש כדי לצפות במקור.",
        )

    return FileResponse(
        path=str(path),
        media_type=guess_content_type(path),
        filename=doc.filename,
        # Content-Disposition: inline → browser renders the PDF in its
        # built-in viewer instead of downloading it. Frontend opens in a
        # new tab so the user can keep the answer in the original window.
        headers={"Content-Disposition": f'inline; filename="{doc.filename}"'},
    )


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


class MetadataPatch(BaseModel):
    doc_type: str | None = None
    folder: str | None = None
    effective_date: str | None = None  # ISO YYYY-MM-DD or ""/null to clear
    document_date: str | None = None
    meeting_number: str | None = None
    decision_number: str | None = None
    bylaw_section_range: str | None = None
    parties: list[str] | None = None
    summary: str | None = None


@router.patch("/{document_id}/metadata")
def update_document_metadata(
    document_id: UUID,
    patch: MetadataPatch,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict:
    """User-confirms/edits the AI-extracted metadata. Sets metadata_reviewed=True
    so future re-classify runs won't overwrite the human's values.
    """
    doc = db.get(Document, document_id)
    if doc is None or doc.tenant_id != user.tenant_id:
        raise HTTPException(404, "Document not found")

    meta = dict(doc.doc_metadata or {})
    fields = patch.model_dump(exclude_unset=True)

    if "doc_type" in fields and fields["doc_type"] is not None:
        doc.doc_type = fields["doc_type"] or None
    if "folder" in fields:
        doc.folder = fields["folder"] or None
    if "effective_date" in fields:
        raw = (fields["effective_date"] or "").strip()
        if raw:
            try:
                doc.effective_date = date.fromisoformat(raw)
            except ValueError:
                raise HTTPException(400, "effective_date must be YYYY-MM-DD")
        else:
            doc.effective_date = None
    for k in ("document_date", "meeting_number", "decision_number", "bylaw_section_range", "summary"):
        if k in fields:
            v = fields[k]
            meta[k] = (v or None) if isinstance(v, str) else v
    if "parties" in fields:
        meta["parties"] = fields["parties"] or None

    meta["metadata_reviewed"] = True
    doc.doc_metadata = meta

    if doc.effective_date is not None:
        db.execute(
            update(Chunk)
            .where(Chunk.document_id == doc.id)
            .values(effective_date=doc.effective_date)
        )
    db.commit()
    log.info("documents.metadata_patched", document_id=str(document_id))
    return {"status": "ok"}


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
