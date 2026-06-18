"""Search endpoint — accepts a question, retrieves chunks, asks Claude, returns cited answer.

Pipeline:
  1. Embed the question
  2. HITL cache lookup — if a previously-approved answer matches, return it (no LLM)
  3. Otherwise: hybrid retrieve → Claude with strict citation prompt
  4. Log every query for the reviewer queue
"""
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import AuthoritativeAnswer, Chunk, Query, Tenant
from app.services.embedding import embed_texts
from app.services.hitl import find_cached_answer
from app.services.lexicon import find_relevant_terms, format_lexicon_block
from app.services.llm import answer_with_citations
from app.services.retrieval import hybrid_retrieve

log = structlog.get_logger()
router = APIRouter()


class SearchRequest(BaseModel):
    question: str
    tenant_id: UUID | None = None
    top_k: int = 5


class SourceCitation(BaseModel):
    chunk_id: UUID
    document_filename: str
    section_path: str | None
    text: str


class SearchResponse(BaseModel):
    query_id: UUID
    question: str
    answer: str
    confidence: str  # confident | uncertain | refused
    sources: list[SourceCitation]
    llm_used: bool
    served_from: str  # "hitl_cache" | "llm" | "no_documents"


def _build_sources(db: Session, chunk_ids: list[UUID]) -> list[SourceCitation]:
    if not chunk_ids:
        return []
    chunks = (
        db.query(Chunk)
        .filter(Chunk.id.in_(chunk_ids))
        .all()
    )
    # Preserve order
    by_id = {c.id: c for c in chunks}
    return [
        SourceCitation(
            chunk_id=c.id,
            document_filename=c.document.filename,
            section_path=c.section_path,
            text=c.text,
        )
        for cid in chunk_ids
        if (c := by_id.get(cid)) is not None
    ]


@router.post("", response_model=SearchResponse)
def search(req: SearchRequest, db: Session = Depends(get_db)) -> SearchResponse:
    """Run the search pipeline: HITL cache → retrieve → answer with citations."""
    tenant_id = req.tenant_id
    if tenant_id is None:
        tenant = db.query(Tenant).first()
        if not tenant:
            raise HTTPException(400, "No tenant exists. Create one first.")
        tenant_id = tenant.id

    question_embedding = embed_texts([req.question], input_type="search_query")[0]

    # 1. HITL cache lookup
    cached = find_cached_answer(db, tenant_id=tenant_id, question_embedding=question_embedding)
    if cached is not None:
        sources = _build_sources(db, list(cached.source_chunk_ids or []))
        query_log = Query(
            tenant_id=tenant_id,
            question=req.question,
            question_embedding=question_embedding,
            answer=cached.answer,
            source_chunk_ids=list(cached.source_chunk_ids or []),
            confidence="confident",
            llm_used=False,
            authoritative_answer_id=cached.id,
        )
        db.add(query_log)
        db.commit()
        db.refresh(query_log)
        return SearchResponse(
            query_id=query_log.id,
            question=req.question,
            answer=cached.answer,
            confidence="confident",
            sources=sources,
            llm_used=False,
            served_from="hitl_cache",
        )

    # 2. Hybrid retrieve (embed with corpus input_type for similarity to stored embeddings)
    retrieved = hybrid_retrieve(
        db,
        tenant_id=tenant_id,
        query=req.question,
        query_embedding=embed_texts([req.question], input_type="search_query")[0],
        top_k=req.top_k,
    )

    if not retrieved:
        query_log = Query(
            tenant_id=tenant_id,
            question=req.question,
            question_embedding=question_embedding,
            answer="לא נמצאו מסמכים רלוונטיים במאגר.",
            confidence="refused",
            llm_used=False,
        )
        db.add(query_log)
        db.commit()
        db.refresh(query_log)
        return SearchResponse(
            query_id=query_log.id,
            question=req.question,
            answer="לא נמצאו מסמכים רלוונטיים במאגר. ייתכן שהנושא לא תויק או שיש לבדוק ידנית.",
            confidence="refused",
            sources=[],
            llm_used=False,
            served_from="no_documents",
        )

    # 3. Generate answer with Claude — include lexicon expansions if any
    lexicon_entries = find_relevant_terms(db, tenant_id=tenant_id, question=req.question)
    lexicon_block = format_lexicon_block(lexicon_entries)
    llm_result = answer_with_citations(
        question=req.question, chunks=retrieved, lexicon_block=lexicon_block
    )

    sources = [
        SourceCitation(
            chunk_id=c.id,
            document_filename=c.document.filename,
            section_path=c.section_path,
            text=c.text,
        )
        for c in retrieved
    ]

    # 4. Log the query
    query_log = Query(
        tenant_id=tenant_id,
        question=req.question,
        question_embedding=question_embedding,
        answer=llm_result.answer,
        source_chunk_ids=[c.id for c in retrieved],
        confidence=llm_result.confidence,
        llm_used=True,
    )
    db.add(query_log)
    db.commit()
    db.refresh(query_log)

    return SearchResponse(
        query_id=query_log.id,
        question=req.question,
        answer=llm_result.answer,
        confidence=llm_result.confidence,
        sources=sources,
        llm_used=True,
        served_from="llm",
    )


class FeedbackRequest(BaseModel):
    feedback: str  # positive | negative


@router.post("/{query_id}/feedback")
def submit_feedback(
    query_id: UUID, req: FeedbackRequest, db: Session = Depends(get_db)
) -> dict:
    """👍 / 👎 on a returned answer — the in-flow signal Ido gives."""
    if req.feedback not in {"positive", "negative"}:
        raise HTTPException(400, "feedback must be 'positive' or 'negative'")

    query = db.get(Query, query_id)
    if query is None:
        raise HTTPException(404, "Query not found")

    query.feedback = req.feedback
    db.commit()
    return {"status": "ok"}
