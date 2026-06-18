"""Document management endpoints — list and delete."""
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query as QParam
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Chunk, Document, Tenant

log = structlog.get_logger()
router = APIRouter()


class DocumentItem(BaseModel):
    id: UUID
    filename: str
    doc_type: str | None
    chunks: int
    chars: int
    ingested_at: str


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
        )
        for r in rows
    ]


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
