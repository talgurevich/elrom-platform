"""Search endpoint — accepts a question, retrieves chunks, asks Claude, returns cited answer."""
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Query, Tenant
from app.services.embedding import embed_texts
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
    question: str
    answer: str
    confidence: str  # confident | uncertain | refused
    sources: list[SourceCitation]
    llm_used: bool


@router.post("", response_model=SearchResponse)
def search(req: SearchRequest, db: Session = Depends(get_db)) -> SearchResponse:
    """Run the search pipeline: retrieve → rerank → answer with citations.

    Today this is the bare-bones path: vector + BM25 hybrid retrieval, Claude answers.
    Refusal logic, HITL cache lookup, lexicon expansion, and reranking come in
    Weeks 2–3 of the build plan.
    """
    tenant_id = req.tenant_id
    if tenant_id is None:
        tenant = db.query(Tenant).first()
        if not tenant:
            raise HTTPException(400, "No tenant exists. Create one first.")
        tenant_id = tenant.id

    question_embedding = embed_texts([req.question])[0]
    retrieved = hybrid_retrieve(
        db, tenant_id=tenant_id, query=req.question, query_embedding=question_embedding, top_k=req.top_k
    )

    if not retrieved:
        return SearchResponse(
            question=req.question,
            answer="לא נמצאו מסמכים רלוונטיים במאגר. ייתכן שהנושא לא תויק או שיש לבדוק ידנית.",
            confidence="refused",
            sources=[],
            llm_used=False,
        )

    llm_result = answer_with_citations(question=req.question, chunks=retrieved)

    sources = [
        SourceCitation(
            chunk_id=c.id,
            document_filename=c.document.filename,
            section_path=c.section_path,
            text=c.text,
        )
        for c in retrieved
    ]

    # Log the query
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

    return SearchResponse(
        question=req.question,
        answer=llm_result.answer,
        confidence=llm_result.confidence,
        sources=sources,
        llm_used=True,
    )
