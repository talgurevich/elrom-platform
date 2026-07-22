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
from app.models import Amendment, AuthoritativeAnswer, Chunk, Document, Lexicon, Query
from app.services.identity import IdentityUser, current_user

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
    # Thread context — lets the reviewer page surface "show full conversation"
    # without an extra round-trip per item just to discover the conversation id.
    conversation_id: UUID | None = None
    turn_index: int | None = None


@router.get("/queries", response_model=list[QueryListItem])
def list_queries(
    db: Session = Depends(get_db),
    user: IdentityUser = Depends(current_user),
    needs_review: bool = QParam(False, description="Only show queries with no reviewer action yet"),
    feedback_only: bool = QParam(False, description="Only show queries with feedback (👎 first)"),
    limit: int = QParam(50, le=200),
) -> list[QueryListItem]:
    """List recent queries for the reviewer queue."""
    q = db.query(Query).filter(Query.tenant_id == user.tenant_id)
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
            conversation_id=r.conversation_id,
            turn_index=r.turn_index,
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
    query_id: UUID,
    req: ApproveRequest,
    db: Session = Depends(get_db),
    user: IdentityUser = Depends(current_user),
) -> ApproveResponse:
    """Promote a query/answer pair to an authoritative answer.

    If edited_answer is provided, use it instead of the original. Otherwise
    use the original LLM answer. The canonical question = the original question.
    """
    query = db.get(Query, query_id)
    if query is None or query.tenant_id != user.tenant_id:
        raise HTTPException(404, "Query not found")
    if query.confidence in ("refused", "clarifying") and req.edited_answer is None:
        raise HTTPException(400, "Cannot approve a refused/clarifying answer without providing edited_answer")

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

    # Harvest lexicon candidates from the reviewer's edits. Best-effort —
    # a proposer failure must not fail the approve. See
    # services/lexicon_harvest.harvest_from_reviewer_edit for the signal
    # rationale: new noun-phrase-shaped tokens in the edit are usually
    # terms the reviewer wanted the glossary to know about.
    if req.edited_answer and req.edited_answer.strip() != (query.answer or "").strip():
        try:
            from app.services.lexicon_harvest import harvest_from_reviewer_edit

            harvest_from_reviewer_edit(
                db,
                tenant_id=query.tenant_id,
                original_answer=query.answer or "",
                edited_answer=req.edited_answer,
                source_query_id=query.id,
            )
            db.commit()
        except Exception as e:  # noqa: BLE001
            log.warning("reviewer.approve.lexicon_harvest_failed", err=str(e))
            db.rollback()

    log.info("reviewer.approved", query_id=str(query_id), auth_id=str(auth.id))
    return ApproveResponse(
        authoritative_answer_id=auth.id,
        canonical_question=query.question,
        answer=final_answer,
    )


@router.post("/queries/{query_id}/reject")
def reject_query(
    query_id: UUID,
    db: Session = Depends(get_db),
    user: IdentityUser = Depends(current_user),
) -> dict:
    """Mark a query/answer pair as incorrect — does NOT create an authoritative entry."""
    query = db.get(Query, query_id)
    if query is None or query.tenant_id != user.tenant_id:
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
    user: IdentityUser = Depends(current_user),
    include_retired: bool = QParam(False),
) -> list[AuthoritativeItem]:
    """List authoritative answers for the caller's tenant."""
    q = db.query(AuthoritativeAnswer).filter(AuthoritativeAnswer.tenant_id == user.tenant_id)
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
    auth_id: UUID,
    req: UpdateAuthoritativeRequest,
    db: Session = Depends(get_db),
    user: IdentityUser = Depends(current_user),
) -> dict:
    """Edit or retire an authoritative answer."""
    auth = db.get(AuthoritativeAnswer, auth_id)
    if auth is None or auth.tenant_id != user.tenant_id:
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
    # Matchable variants (canonical first). Reviewer edits list on the page.
    surface_forms: list[str] = []
    # definition | pointer | rule — see models.Lexicon.entry_type.
    entry_type: str = "definition"
    # Reader-facing tooltip.
    short_gloss: str | None = None
    # Answerer-facing context injection.
    answerer_expansion: str | None = None
    # Legacy free-text field — clients should render short_gloss+answerer_expansion
    # when present, and fall back to `expansion` for un-migrated rows.
    expansion: str
    notes: str | None
    source: str = "manual"  # manual | learned
    status: str = "active"  # active | pending | rejected
    confidence: float | None = None
    evidence: dict | None = None
    # 30-day match count for the stats mini-panel. Populated by list_lexicon.
    match_count_30d: int = 0
    last_matched_at: str | None = None
    updated_at: str


class CreateLexiconRequest(BaseModel):
    term: str
    expansion: str | None = None
    surface_forms: list[str] | None = None
    entry_type: str | None = None
    short_gloss: str | None = None
    answerer_expansion: str | None = None
    notes: str | None = None


class UpdateLexiconRequest(BaseModel):
    term: str | None = None
    surface_forms: list[str] | None = None
    entry_type: str | None = None
    short_gloss: str | None = None
    answerer_expansion: str | None = None
    expansion: str | None = None
    notes: str | None = None
    # Reviewer-only: approve / reject / re-activate learned entries.
    status: str | None = None


@router.get("/lexicon", response_model=list[LexiconItem])
def list_lexicon(
    db: Session = Depends(get_db),
    user: IdentityUser = Depends(current_user),
    status: str | None = None,
) -> list[LexiconItem]:
    """List lexicon entries for the caller's tenant.

    Without ``status``, returns active + pending entries (so the reviewer
    sees both their curated lexicon and the queue of learner-proposed
    additions). Pass ``status=rejected`` to inspect what's been suppressed.
    """
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import func as sa_func

    from app.models import LexiconMatchEvent

    q = db.query(Lexicon).filter(Lexicon.tenant_id == user.tenant_id)
    if status is not None:
        q = q.filter(Lexicon.status == status)
    else:
        q = q.filter(Lexicon.status.in_(["active", "pending"]))
    rows = q.order_by(Lexicon.status.desc(), Lexicon.term).all()

    # Aggregate 30d match stats in one query — cheap and keeps the stats
    # panel from N+1'ing.
    since = datetime.now(timezone.utc) - timedelta(days=30)
    lex_ids = [r.id for r in rows]
    stats: dict[UUID, tuple[int, datetime | None]] = {}
    if lex_ids:
        agg = (
            db.query(
                LexiconMatchEvent.lexicon_id,
                sa_func.count(LexiconMatchEvent.id),
                sa_func.max(LexiconMatchEvent.created_at),
            )
            .filter(LexiconMatchEvent.lexicon_id.in_(lex_ids))
            .filter(LexiconMatchEvent.created_at >= since)
            .group_by(LexiconMatchEvent.lexicon_id)
            .all()
        )
        stats = {row[0]: (row[1], row[2]) for row in agg}

    return [
        LexiconItem(
            id=r.id,
            term=r.term,
            surface_forms=r.surface_forms or [],
            entry_type=r.entry_type or "definition",
            short_gloss=r.short_gloss,
            answerer_expansion=r.answerer_expansion,
            expansion=r.expansion,
            notes=r.notes,
            source=r.source or "manual",
            status=r.status or "active",
            confidence=r.confidence,
            evidence=r.evidence,
            match_count_30d=stats.get(r.id, (0, None))[0],
            last_matched_at=(
                stats.get(r.id, (0, None))[1].isoformat()
                if stats.get(r.id, (0, None))[1]
                else None
            ),
            updated_at=r.updated_at.isoformat() if r.updated_at else "",
        )
        for r in rows
    ]


@router.post("/lexicon", response_model=LexiconItem)
def create_lexicon(
    req: CreateLexiconRequest,
    db: Session = Depends(get_db),
    user: IdentityUser = Depends(current_user),
) -> LexiconItem:
    """Add a new lexicon entry in the caller's tenant."""
    from app.services.hebrew_prefixes import expand_hebrew_prefixes

    term = (req.term or "").strip()
    if not term:
        raise HTTPException(400, "term is required")
    # answerer_expansion is the canonical "what the LLM should know" field.
    # `expansion` (legacy NOT NULL) mirrors it so old readers keep working.
    answerer_exp = (req.answerer_expansion or req.expansion or "").strip()
    short = (req.short_gloss or "").strip()
    if not answerer_exp and not short:
        raise HTTPException(400, "provide at least one of expansion / answerer_expansion / short_gloss")
    surface_forms = req.surface_forms or expand_hebrew_prefixes(term)

    entry = Lexicon(
        tenant_id=user.tenant_id,
        term=term,
        surface_forms=surface_forms,
        entry_type=req.entry_type or "definition",
        short_gloss=short or None,
        answerer_expansion=answerer_exp or None,
        expansion=answerer_exp or short or term,
        notes=req.notes,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    log.info("lexicon.created", term=entry.term)
    return LexiconItem(
        id=entry.id,
        term=entry.term,
        surface_forms=entry.surface_forms or [],
        entry_type=entry.entry_type or "definition",
        short_gloss=entry.short_gloss,
        answerer_expansion=entry.answerer_expansion,
        expansion=entry.expansion,
        notes=entry.notes,
        source=entry.source or "manual",
        status=entry.status or "active",
        updated_at=entry.updated_at.isoformat() if entry.updated_at else "",
    )


@router.patch("/lexicon/{lex_id}")
def update_lexicon(
    lex_id: UUID,
    req: UpdateLexiconRequest,
    db: Session = Depends(get_db),
    user: IdentityUser = Depends(current_user),
) -> dict:
    """Edit a lexicon entry."""
    entry = db.get(Lexicon, lex_id)
    if entry is None or entry.tenant_id != user.tenant_id:
        raise HTTPException(404, "Lexicon entry not found")
    if req.term is not None:
        entry.term = req.term.strip()
    if req.surface_forms is not None:
        entry.surface_forms = [s.strip() for s in req.surface_forms if s.strip()]
    if req.entry_type is not None:
        if req.entry_type not in {"definition", "pointer", "rule"}:
            raise HTTPException(400, "entry_type must be definition|pointer|rule")
        entry.entry_type = req.entry_type
    if req.short_gloss is not None:
        entry.short_gloss = req.short_gloss.strip() or None
    if req.answerer_expansion is not None:
        entry.answerer_expansion = req.answerer_expansion.strip() or None
    if req.expansion is not None:
        entry.expansion = req.expansion.strip()
    else:
        # Keep legacy `expansion` in sync with answerer_expansion when the
        # reviewer edits the new field but not the old one, so downstream
        # readers that still consult `expansion` see the fresh value.
        if req.answerer_expansion is not None and entry.answerer_expansion:
            entry.expansion = entry.answerer_expansion
    if req.notes is not None:
        entry.notes = req.notes
    if req.status is not None:
        if req.status not in {"active", "pending", "rejected"}:
            raise HTTPException(400, "status must be active|pending|rejected")
        entry.status = req.status
    db.commit()
    # Regex cache in lexicon_matcher is keyed by (surface_forms tuple), so
    # editing surface_forms invalidates automatically on next call. No
    # explicit purge needed.
    log.info("lexicon.updated", lex_id=str(lex_id))
    return {"status": "ok"}


@router.delete("/lexicon/{lex_id}")
def delete_lexicon(
    lex_id: UUID,
    db: Session = Depends(get_db),
    user: IdentityUser = Depends(current_user),
) -> dict:
    """Delete a lexicon entry."""
    entry = db.get(Lexicon, lex_id)
    if entry is None or entry.tenant_id != user.tenant_id:
        raise HTTPException(404, "Lexicon entry not found")
    db.delete(entry)
    db.commit()
    log.info("lexicon.deleted", lex_id=str(lex_id))
    return {"status": "ok"}


class LexiconSuggestion(BaseModel):
    term: str
    expansion: str
    why: str
    source_question: str
    source_query_id: str


@router.post("/lexicon/suggestions", response_model=list[LexiconSuggestion])
def lexicon_suggestions(
    db: Session = Depends(get_db),
    user: IdentityUser = Depends(current_user),
) -> list[LexiconSuggestion]:
    """Propose lexicon entries from recent failed queries (Claude Haiku-driven)."""
    from app.services.lexicon import suggest_lexicon_entries_from_failures

    items = suggest_lexicon_entries_from_failures(db, tenant_id=user.tenant_id, limit=10)
    return [LexiconSuggestion(**i) for i in items]


# ─────────────────────────────────────────────────────────────────────────
# Amendments — cross-document supersession graph
# ─────────────────────────────────────────────────────────────────────────


class AmendmentItem(BaseModel):
    id: UUID
    amendment_doc_id: UUID
    amendment_doc_filename: str
    target_doc_id: UUID
    target_doc_filename: str
    target_section: str
    action: str
    old_text: str | None
    new_text: str | None
    effective_date: str | None
    rationale: str | None
    evidence_span: str | None
    extractor_confidence: float | None
    needs_review: bool
    created_at: str


def _amendment_to_item(a: Amendment, docs: dict[UUID, Document]) -> AmendmentItem:
    return AmendmentItem(
        id=a.id,
        amendment_doc_id=a.amendment_doc_id,
        amendment_doc_filename=docs[a.amendment_doc_id].filename if a.amendment_doc_id in docs else "?",
        target_doc_id=a.target_doc_id,
        target_doc_filename=docs[a.target_doc_id].filename if a.target_doc_id in docs else "?",
        target_section=a.target_section,
        action=a.action,
        old_text=a.old_text,
        new_text=a.new_text,
        effective_date=a.effective_date.isoformat() if a.effective_date else None,
        rationale=a.rationale,
        evidence_span=a.evidence_span,
        extractor_confidence=a.extractor_confidence,
        needs_review=a.needs_review,
        created_at=a.created_at.isoformat(),
    )


@router.get("/amendments", response_model=list[AmendmentItem])
def list_amendments(
    db: Session = Depends(get_db),
    user: IdentityUser = Depends(current_user),
    needs_review: bool | None = QParam(None, description="Filter by needs_review flag"),
    limit: int = QParam(100, le=500),
) -> list[AmendmentItem]:
    q = db.query(Amendment).filter(Amendment.tenant_id == user.tenant_id)
    if needs_review is not None:
        q = q.filter(Amendment.needs_review.is_(needs_review))
    rows = q.order_by(Amendment.needs_review.desc(), Amendment.created_at.desc()).limit(limit).all()
    doc_ids = {a.amendment_doc_id for a in rows} | {a.target_doc_id for a in rows}
    docs = {d.id: d for d in db.query(Document).filter(Document.id.in_(doc_ids)).all()}
    return [_amendment_to_item(a, docs) for a in rows]


class UpdateAmendmentRequest(BaseModel):
    target_section: str | None = None
    action: str | None = None
    new_text: str | None = None
    effective_date: str | None = None  # YYYY-MM-DD
    rationale: str | None = None


@router.patch("/amendments/{amendment_id}")
def update_amendment(
    amendment_id: UUID,
    req: UpdateAmendmentRequest,
    db: Session = Depends(get_db),
    user: IdentityUser = Depends(current_user),
) -> dict:
    """Reviewer edits to a pending amendment. Does NOT change ``needs_review``
    — call /approve or /reject once the row is right."""
    from datetime import date as _date

    from app.services.amendment_extractor import looks_like_real_section_ref

    a = db.get(Amendment, amendment_id)
    if a is None or a.tenant_id != user.tenant_id:
        raise HTTPException(404, "Amendment not found")

    if req.target_section is not None:
        if not looks_like_real_section_ref(req.target_section):
            raise HTTPException(400, "target_section must be a section number like '44' or '45.ב'")
        a.target_section = req.target_section
    if req.action is not None:
        if req.action not in {"replace", "add_after", "add_before", "delete", "clarify"}:
            raise HTTPException(400, "invalid action")
        a.action = req.action
    if req.new_text is not None:
        a.new_text = req.new_text
    if req.effective_date is not None:
        try:
            a.effective_date = _date.fromisoformat(req.effective_date)
        except ValueError:
            raise HTTPException(400, "effective_date must be YYYY-MM-DD")
    if req.rationale is not None:
        a.rationale = req.rationale
    db.commit()
    return {"status": "ok"}


@router.post("/amendments/{amendment_id}/approve")
def approve_amendment(
    amendment_id: UUID,
    db: Session = Depends(get_db),
    user: IdentityUser = Depends(current_user),
) -> dict:
    """Clear ``needs_review`` and run the supersession pass so any matching
    chunk gets flipped. Safe to call on an already-active amendment (no-op)."""
    from app.services.amendment_extractor import _apply_supersession

    a = db.get(Amendment, amendment_id)
    if a is None or a.tenant_id != user.tenant_id:
        raise HTTPException(404, "Amendment not found")
    if a.effective_date is None:
        raise HTTPException(400, "Set effective_date before approving")
    a.needs_review = False
    superseded = _apply_supersession(db, a)
    db.commit()
    log.info("reviewer.amendment_approved", amendment_id=str(amendment_id), superseded=superseded)
    return {"status": "ok", "chunks_superseded": superseded}


@router.post("/amendments/{amendment_id}/reject")
def reject_amendment(
    amendment_id: UUID,
    db: Session = Depends(get_db),
    user: IdentityUser = Depends(current_user),
) -> dict:
    """Delete an incorrect amendment row and unlink any chunk it flipped."""
    a = db.get(Amendment, amendment_id)
    if a is None or a.tenant_id != user.tenant_id:
        raise HTTPException(404, "Amendment not found")
    db.query(Chunk).filter(Chunk.superseded_by_amendment_id == a.id).update(
        {Chunk.superseded_by_amendment_id: None}
    )
    db.delete(a)
    db.commit()
    log.info("reviewer.amendment_rejected", amendment_id=str(amendment_id))
    return {"status": "ok"}
