"""Ingest endpoint — accepts a document, chunks it, embeds, stores in pgvector."""
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Chunk, Document, Tenant
from app.services.chunking import chunk_document
from app.services.embedding import embed_texts

log = structlog.get_logger()
router = APIRouter()


class IngestRequest(BaseModel):
    filename: str
    text: str
    tenant_id: UUID | None = None  # if omitted, uses the first tenant (dev convenience)
    doc_type: str | None = None  # bylaw | sub_bylaw | minutes | decision | other


class IngestResponse(BaseModel):
    document_id: UUID
    chunks_created: int


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

    doc = Document(
        tenant_id=tenant_id,
        filename=req.filename,
        doc_type=req.doc_type,
    )
    db.add(doc)
    db.flush()  # get the id without committing

    chunk_texts = chunk_document(req.text)
    if not chunk_texts:
        raise HTTPException(400, "Document produced no chunks.")

    embeddings = embed_texts(chunk_texts)

    for i, (chunk_text, embedding) in enumerate(zip(chunk_texts, embeddings, strict=True)):
        chunk = Chunk(
            document_id=doc.id,
            tenant_id=tenant_id,
            position=i,
            text=chunk_text,
            embedding=embedding,
        )
        db.add(chunk)
        db.flush()
        # Populate text_search via Postgres FTS (basic for now; lemmatization comes later)
        db.execute(
            text("UPDATE chunks SET text_search = to_tsvector('simple', text) WHERE id = :cid"),
            {"cid": chunk.id},
        )

    db.commit()
    log.info("ingest.complete", document_id=str(doc.id), chunks=len(chunk_texts))
    return IngestResponse(document_id=doc.id, chunks_created=len(chunk_texts))
