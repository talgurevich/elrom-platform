"""Reviewer endpoints — the HITL marking flow.

This is where the moat lives. A reviewer (Tal/Noam in MVP, eventually a
designated kibbutz reviewer) goes through the query log and marks answers
as authoritative. Marked answers bypass the LLM for future similar questions.
"""
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query as QParam
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import AuthoritativeAnswer, Lexicon, Query, Tenant

log = structlog.get_logger()
router = APIRouter()


# ─────────────────────────────────────────────────────────────────────────
# Query log — what the reviewer sees
# ─────────────────────────────────────────────────────────────────────────


class QueryListItem(BaseModel):
    id: UUID
    question: str
    answer: str | None
    confidence: str | None
    llm_used: bool
    feedback: str | None
    reviewer_action: str | None
    served_from_cache: bool
    created_at: str


@router.get("/queries", response_model=list[QueryListItem])
def list_queries(
    db: Session = Depends(get_db),
    tenant_id: UUID | None = QParam(None),
    needs_review: bool = QParam(False, description="Only show queries with no reviewer action yet"),
    feedback_only: bool = QParam(False, description="Only show queries with feedback (👎 first)"),
    limit: int = QParam(50, le=200),
) -> list[QueryListItem]:
    """List recent queries for the reviewer queue."""
    if tenant_id is None:
        tenant = db.query(Tenant).first()
        if not tenant:
            raise HTTPException(400, "No tenant exists.")
        tenant_id = tenant.id

    q = db.query(Query).filter(Query.tenant_id == tenant_id)
    if needs_review:
        q = q.filter(Query.reviewer_action.is_(None))
    if feedback_only:
        q = q.filter(Query.feedback.isnot(None))

    # Negative feedback first, then most recent
    rows = q.order_by(Query.feedback.desc().nullslast(), Query.created_at.desc()).limit(limit).all()

    return [
        QueryListItem(
            id=r.id,
            question=r.question,
            answer=r.answer,
            confidence=r.confidence,
            llm_used=r.llm_used,
            feedback=r.feedback,
            reviewer_action=r.reviewer_action,
            served_from_cache=r.authoritative_answer_id is not None,
            created_at=r.created_at.isoformat() if r.created_at else "",
        )
        for r in rows
    ]


# ─────────────────────────────────────────────────────────────────────────
# Approve / edit / reject
# ─────────────────────────────────────────────────────────────────────────


class ApproveRequest(BaseModel):
    edited_answer: str | None = None
    similarity_threshold: float = 0.92
    internal_note: str | None = None


class ApproveResponse(BaseModel):
    authoritative_answer_id: UUID
    canonical_question: str
    answer: str


@router.post("/queries/{query_id}/approve", response_model=ApproveResponse)
def approve_query(
    query_id: UUID, req: ApproveRequest, db: Session = Depends(get_db)
) -> ApproveResponse:
    """Promote a query/answer pair to an authoritative answer.

    If edited_answer is provided, use it instead of the original. Otherwise
    use the original LLM answer. The canonical question = the original question.
    """
    query = db.get(Query, query_id)
    if query is None:
        raise HTTPException(404, "Query not found")
    if query.confidence == "refused" and req.edited_answer is None:
        raise HTTPException(400, "Cannot approve a refused answer without providing edited_answer")

    final_answer = (req.edited_answer or query.answer or "").strip()
    if not final_answer:
        raise HTTPException(400, "No answer to approve")

    auth = AuthoritativeAnswer(
        tenant_id=query.tenant_id,
        canonical_question=query.question,
        canonical_question_embedding=query.question_embedding,
        answer=final_answer,
        source_chunk_ids=query.source_chunk_ids,
        internal_note=req.internal_note,
        similarity_threshold=req.similarity_threshold,
        status="active",
    )
    db.add(auth)
    db.flush()

    query.reviewer_action = "edited" if req.edited_answer else "approved"
    query.authoritative_answer_id = auth.id
    db.commit()

    log.info("reviewer.approved", query_id=str(query_id), auth_id=str(auth.id))
    return ApproveResponse(
        authoritative_answer_id=auth.id,
        canonical_question=query.question,
        answer=final_answer,
    )


@router.post("/queries/{query_id}/reject")
def reject_query(query_id: UUID, db: Session = Depends(get_db)) -> dict:
    """Mark a query/answer pair as incorrect — does NOT create an authoritative entry."""
    query = db.get(Query, query_id)
    if query is None:
        raise HTTPException(404, "Query not found")
    query.reviewer_action = "rejected"
    db.commit()
    log.info("reviewer.rejected", query_id=str(query_id))
    return {"status": "ok"}


# ─────────────────────────────────────────────────────────────────────────
# Authoritative library
# ─────────────────────────────────────────────────────────────────────────


class AuthoritativeItem(BaseModel):
    id: UUID
    canonical_question: str
    answer: str
    status: str
    similarity_threshold: float
    internal_note: str | None
    approved_at: str


@router.get("/authoritative", response_model=list[AuthoritativeItem])
def list_authoritative(
    db: Session = Depends(get_db),
    tenant_id: UUID | None = QParam(None),
    include_retired: bool = QParam(False),
) -> list[AuthoritativeItem]:
    """List authoritative answers."""
    if tenant_id is None:
        tenant = db.query(Tenant).first()
        if not tenant:
            raise HTTPException(400, "No tenant exists.")
        tenant_id = tenant.id

    q = db.query(AuthoritativeAnswer).filter(AuthoritativeAnswer.tenant_id == tenant_id)
    if not include_retired:
        q = q.filter(AuthoritativeAnswer.status == "active")
    rows = q.order_by(AuthoritativeAnswer.approved_at.desc()).all()

    return [
        AuthoritativeItem(
            id=r.id,
            canonical_question=r.canonical_question,
            answer=r.answer,
            status=r.status,
            similarity_threshold=r.similarity_threshold,
            internal_note=r.internal_note,
            approved_at=r.approved_at.isoformat() if r.approved_at else "",
        )
        for r in rows
    ]


class UpdateAuthoritativeRequest(BaseModel):
    answer: str | None = None
    similarity_threshold: float | None = None
    internal_note: str | None = None
    status: str | None = None  # active | retired


@router.patch("/authoritative/{auth_id}")
def update_authoritative(
    auth_id: UUID, req: UpdateAuthoritativeRequest, db: Session = Depends(get_db)
) -> dict:
    """Edit or retire an authoritative answer."""
    auth = db.get(AuthoritativeAnswer, auth_id)
    if auth is None:
        raise HTTPException(404, "Authoritative answer not found")

    if req.answer is not None:
        auth.answer = req.answer
    if req.similarity_threshold is not None:
        if not 0.0 < req.similarity_threshold <= 1.0:
            raise HTTPException(400, "similarity_threshold must be in (0, 1]")
        auth.similarity_threshold = req.similarity_threshold
    if req.internal_note is not None:
        auth.internal_note = req.internal_note
    if req.status is not None:
        if req.status not in {"active", "retired"}:
            raise HTTPException(400, "status must be 'active' or 'retired'")
        auth.status = req.status

    db.commit()
    log.info("reviewer.authoritative_updated", auth_id=str(auth_id))
    return {"status": "ok"}


# ─────────────────────────────────────────────────────────────────────────
# Lexicon — per-tenant domain term expansions
# ─────────────────────────────────────────────────────────────────────────


class LexiconItem(BaseModel):
    id: UUID
    term: str
    expansion: str
    notes: str | None
    updated_at: str


class CreateLexiconRequest(BaseModel):
    term: str
    expansion: str
    notes: str | None = None
    tenant_id: UUID | None = None


class UpdateLexiconRequest(BaseModel):
    term: str | None = None
    expansion: str | None = None
    notes: str | None = None


@router.get("/lexicon", response_model=list[LexiconItem])
def list_lexicon(
    db: Session = Depends(get_db),
    tenant_id: UUID | None = QParam(None),
) -> list[LexiconItem]:
    """List lexicon entries for a tenant."""
    if tenant_id is None:
        tenant = db.query(Tenant).first()
        if not tenant:
            raise HTTPException(400, "No tenant exists.")
        tenant_id = tenant.id

    rows = (
        db.query(Lexicon)
        .filter(Lexicon.tenant_id == tenant_id)
        .order_by(Lexicon.term)
        .all()
    )
    return [
        LexiconItem(
            id=r.id,
            term=r.term,
            expansion=r.expansion,
            notes=r.notes,
            updated_at=r.updated_at.isoformat() if r.updated_at else "",
        )
        for r in rows
    ]


@router.post("/lexicon", response_model=LexiconItem)
def create_lexicon(req: CreateLexiconRequest, db: Session = Depends(get_db)) -> LexiconItem:
    """Add a new lexicon entry."""
    tenant_id = req.tenant_id
    if tenant_id is None:
        tenant = db.query(Tenant).first()
        if not tenant:
            raise HTTPException(400, "No tenant exists.")
        tenant_id = tenant.id

    if not req.term.strip() or not req.expansion.strip():
        raise HTTPException(400, "term and expansion are required")

    entry = Lexicon(
        tenant_id=tenant_id,
        term=req.term.strip(),
        expansion=req.expansion.strip(),
        notes=req.notes,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    log.info("lexicon.created", term=entry.term)
    return LexiconItem(
        id=entry.id,
        term=entry.term,
        expansion=entry.expansion,
        notes=entry.notes,
        updated_at=entry.updated_at.isoformat() if entry.updated_at else "",
    )


@router.patch("/lexicon/{lex_id}")
def update_lexicon(
    lex_id: UUID, req: UpdateLexiconRequest, db: Session = Depends(get_db)
) -> dict:
    """Edit a lexicon entry."""
    entry = db.get(Lexicon, lex_id)
    if entry is None:
        raise HTTPException(404, "Lexicon entry not found")
    if req.term is not None:
        entry.term = req.term.strip()
    if req.expansion is not None:
        entry.expansion = req.expansion.strip()
    if req.notes is not None:
        entry.notes = req.notes
    db.commit()
    log.info("lexicon.updated", lex_id=str(lex_id))
    return {"status": "ok"}


@router.delete("/lexicon/{lex_id}")
def delete_lexicon(lex_id: UUID, db: Session = Depends(get_db)) -> dict:
    """Delete a lexicon entry."""
    entry = db.get(Lexicon, lex_id)
    if entry is None:
        raise HTTPException(404, "Lexicon entry not found")
    db.delete(entry)
    db.commit()
    log.info("lexicon.deleted", lex_id=str(lex_id))
    return {"status": "ok"}
