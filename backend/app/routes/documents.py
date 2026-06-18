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
from app.models import Chunk, Document, Tenant

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


@router.get("", response_model=list[DocumentItem])
def list_documents(
    db: Session = Depends(get_db),
    tenant_id: UUID | None = QParam(None),
) -> list[DocumentItem]:
    """List documents for a tenant with chunk + char counts."""
    if tenant_id is None:
        tenant = db.query(Tenant).first()
        if not tenant:
            raise HTTPException(400, "No tenant exists.")
        tenant_id = tenant.id

    stmt = (
        select(
            Document.id,
            Document.filename,
            Document.doc_type,
            Document.ingested_at,
            Document.doc_metadata,
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
        )
        for r in rows
    ]


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


@router.post("/classify", response_model=ClassifySummary)
def classify_documents(
    db: Session = Depends(get_db),
    force: bool = QParam(False, description="Re-classify even already-classified docs"),
) -> ClassifySummary:
    """Walk every document. For each one without a Hebrew title or not yet
    classified, read its first ~4000 chars of chunk text and ask Claude Haiku
    to title + type + summarize it. Writes results into Document.filename,
    Document.doc_type, and Document.doc_metadata."""
    from anthropic import Anthropic

    tenant = db.query(Tenant).first()
    if not tenant:
        raise HTTPException(400, "No tenant exists.")

    docs = db.query(Document).filter(Document.tenant_id == tenant.id).all()
    client = Anthropic(api_key=settings.anthropic_api_key)
    results: list[ClassifyResult] = []
    classified = 0

    for doc in docs:
        meta = doc.doc_metadata or {}
        already = bool(meta.get("ai_classified"))
        has_name = _has_meaningful_name(doc.filename)

        if not force and already:
            results.append(
                ClassifyResult(
                    document_id=doc.id,
                    old_filename=doc.filename,
                    new_filename=doc.filename,
                    doc_type=doc.doc_type,
                    summary=meta.get("summary"),
                    skipped=True,
                    reason="already_classified",
                )
            )
            continue

        # Already has a meaningful Hebrew name AND a doc_type — keep, but still
        # generate a summary if missing so the UI has something.
        chunks = (
            db.query(Chunk)
            .filter(Chunk.document_id == doc.id)
            .order_by(Chunk.position)
            .limit(8)
            .all()
        )
        sample = "\n\n".join(c.text for c in chunks)[:4000]

        if not sample.strip():
            results.append(
                ClassifyResult(
                    document_id=doc.id,
                    old_filename=doc.filename,
                    new_filename=doc.filename,
                    doc_type=doc.doc_type,
                    summary=None,
                    skipped=True,
                    reason="no_text_extracted",
                )
            )
            continue

        try:
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
            if title and not has_name:
                # Preserve the original extension for traceability.
                ext = ""
                if "." in doc.filename:
                    ext = "." + doc.filename.rsplit(".", 1)[1]
                new_filename = f"{title}{ext}"
                doc.filename = new_filename

            if doc_type:
                doc.doc_type = doc_type

            doc.doc_metadata = {
                **(doc.doc_metadata or {}),
                "ai_classified": True,
                "ai_title": title,
                "summary": summary,
                "original_filename": meta.get("original_filename") or doc.filename,
            }

            results.append(
                ClassifyResult(
                    document_id=doc.id,
                    old_filename=meta.get("original_filename") or doc.filename,
                    new_filename=new_filename,
                    doc_type=doc.doc_type,
                    summary=summary,
                    skipped=False,
                )
            )
            classified += 1
        except Exception as e:
            log.warning("documents.classify_failed", doc_id=str(doc.id), err=str(e))
            results.append(
                ClassifyResult(
                    document_id=doc.id,
                    old_filename=doc.filename,
                    new_filename=doc.filename,
                    doc_type=doc.doc_type,
                    summary=None,
                    skipped=True,
                    reason=f"error: {str(e)[:80]}",
                )
            )

    db.commit()
    return ClassifySummary(
        total=len(docs),
        classified=classified,
        skipped=len(docs) - classified,
        results=results,
    )


@router.delete("/{document_id}")
def delete_document(document_id: UUID, db: Session = Depends(get_db)) -> dict:
    """Delete a document and its chunks (queries that reference its chunks become orphaned but stay)."""
    doc = db.get(Document, document_id)
    if doc is None:
        raise HTTPException(404, "Document not found")
    db.delete(doc)
    db.commit()
    log.info("documents.deleted", document_id=str(document_id))
    return {"status": "ok"}
