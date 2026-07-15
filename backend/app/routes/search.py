"""Search endpoint — accepts a question, retrieves chunks, asks Claude, returns cited answer.

Pipeline:
  1. Embed the question
  2. HITL cache lookup — if a previously-approved answer matches, return it (no LLM)
  3. Otherwise: hybrid retrieve → Claude with strict citation prompt
  4. Log every query for the reviewer queue

Two endpoints, one pipeline:
  - POST /api/search — returns the final SearchResponse as JSON (legacy / simple).
  - POST /api/search/stream — Server-Sent Events; emits stage + detail events
    as the pipeline progresses, ending with a "done" event carrying the same
    SearchResponse. The UI uses this to drive a real progress bar.
"""
import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query as QParam
from fastapi.responses import StreamingResponse
from sqlalchemy import func
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import SessionLocal, get_db
from app.models import AuthoritativeAnswer, Chunk, Conversation, Document, Query
from app.services.identity import (
    IdentityUser,
    current_user,
    get_tenant_cached,
    identity_service,
)
from app.services.mail import send_broken_answer_alert
from app.services.chat_triage import triage_turn
from app.services.embedding import embed_texts
from app.services.hitl import find_cached_answer, find_near_misses
from app.services.lexicon import find_relevant_terms, format_lexicon_block
from app.services.llm import answer_with_citations
from app.services.query_rewriter import PriorTurn
from app.services.retrieval import hybrid_retrieve

log = structlog.get_logger()
router = APIRouter()


class SearchRequest(BaseModel):
    question: str
    top_k: int = 5
    # Conversation thread for chat-style refinement. If supplied, prior turns
    # in the same conversation are used to build a canonical query before
    # retrieval (see services.query_rewriter). If omitted, a new single-turn
    # conversation is created behind the scenes so every query is still
    # addressable as part of a thread.
    conversation_id: UUID | None = None
    # When the caller is running this question as a test of a specific
    # golden (e.g. the "run golden" panel), pass the golden's id so that
    # 👍/👎 on the answer aggregates into the per-golden pass-rate report.
    golden_id: UUID | None = None


class SourceCitation(BaseModel):
    chunk_id: UUID
    document_id: UUID | None = None
    document_filename: str
    section_path: str | None
    text: str
    # True when the original uploaded file is stored on disk and can be
    # opened in the browser via GET /api/documents/{document_id}/file.
    has_file: bool = False


class StructuredReference(BaseModel):
    title: str
    section_number: str
    source_type: str
    excerpt: str


class NearMiss(BaseModel):
    authoritative_answer_id: UUID
    canonical_question: str
    answer: str
    similarity: float


class SearchResponse(BaseModel):
    query_id: UUID
    conversation_id: UUID
    turn_index: int
    # Clarification-first chat: when the triage step decides the question is
    # ambiguous, it short-circuits the answer pipeline and returns a single
    # clarifying question to the user. mode="clarify" means there are no
    # sources / no LLM answer yet — the next turn from the user resolves the
    # ambiguity and gets answered.
    mode: str = "answer"  # "answer" | "clarify"
    canonical_query: str | None = None  # rewritten query used for retrieval (or best-guess on clarify)
    clarifying_message: str | None = None  # set when mode == "clarify"
    candidate_docs: list[str] = []  # optional doc-title hints rendered with the clarification
    question: str
    answer: str
    confidence: str  # confident | uncertain | refused | clarifying
    sources: list[SourceCitation]
    references: list[StructuredReference] = []
    llm_used: bool
    served_from: str  # "hitl_cache" | "llm" | "no_documents" | "clarify"
    retrieval_debug: dict | None = None
    near_misses: list[NearMiss] = []


# Phrases that show up when the answerer LLM realizes mid-generation that it
# doesn't have enough context. If we detect any of these, the right reflex is
# to surface the response as a clarification turn instead of an answer turn —
# the LLM is telling us the triage upstream missed an ambiguity.
_SELF_CLARIFICATION_MARKERS = (
    "אינה ברורה",
    "השאלה לא ברורה",
    "אינה ברורה דיה",
    "השאלה אינה ברורה דיה",
    "אנא פרט",
    "פרט את שאלתך",
    "הכוונה אינה ברורה",
    "לא ברור לי",
    "לא ברורה לי",
    "אנא הבהר",
)


def _looks_like_self_clarification(answer: str) -> bool:
    """Heuristic: did the answerer LLM produce a 'I need clarification' answer?

    Triggered ONLY by explicit Hebrew clarification asks. Substring matching
    is fine here — these phrases don't appear in legitimate substantive
    answers about kibbutz bylaws.
    """
    if not answer:
        return False
    return any(marker in answer for marker in _SELF_CLARIFICATION_MARKERS)


def _build_sources(db: Session, chunk_ids: list[UUID]) -> list[SourceCitation]:
    if not chunk_ids:
        return []
    chunks = (
        db.query(Chunk)
        .filter(Chunk.id.in_(chunk_ids))
        .all()
    )
    by_id = {c.id: c for c in chunks}
    return [
        SourceCitation(
            chunk_id=c.id,
            document_id=c.document.id,
            document_filename=c.document.filename,
            section_path=c.section_path,
            text=c.text,
            has_file=bool(
                c.document.source_uri
                and str(c.document.source_uri).startswith("file://")
            ),
        )
        for cid in chunk_ids
        if (c := by_id.get(cid)) is not None
    ]


def _get_or_create_conversation(
    db: Session, *, tenant_id: UUID, user_id: UUID | None, conversation_id: UUID | None
) -> Conversation:
    """Resolve the Conversation for this search request.

    Cases:
      - conversation_id provided + belongs to tenant → reuse.
      - conversation_id provided but not found or wrong tenant → 404. We
        prefer surfacing the mismatch loudly over silently spawning a new
        conversation (would lose chat history from the user's POV).
      - conversation_id omitted → start a fresh single-turn conversation.
    """
    if conversation_id is not None:
        conv = db.get(Conversation, conversation_id)
        if conv is None or conv.tenant_id != tenant_id:
            raise HTTPException(404, "Conversation not found")
        return conv
    conv = Conversation(tenant_id=tenant_id, user_id=user_id)
    db.add(conv)
    db.flush()
    return conv


def _load_prior_turns(db: Session, conversation_id: UUID) -> list[PriorTurn]:
    rows = (
        db.query(Query)
        .filter(Query.conversation_id == conversation_id)
        .order_by(Query.turn_index.asc().nulls_last(), Query.created_at.asc())
        .all()
    )
    out: list[PriorTurn] = []
    for r in rows:
        if r.question:
            out.append(PriorTurn(role="user", text=r.question))
        if r.answer:
            out.append(PriorTurn(role="assistant", text=r.answer))
    return out


async def search_pipeline(
    db: Session,
    *,
    tenant_id: UUID,
    user_id: UUID | None,
    question: str,
    top_k: int,
    conversation_id: UUID | None = None,
    golden_id: UUID | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """The single search pipeline, expressed as an async generator that yields
    progress events as it runs. Both the JSON endpoint and the SSE endpoint
    consume this — guaranteeing identical behavior.

    Event shapes:
      {"type": "stage",  "stage": "analyzing" | "searching" | "ranking" | "generating"}
      {"type": "detail", "text": "..."}   # human-readable side info
      {"type": "done",   "response": SearchResponse-as-dict}
      {"type": "error",  "detail": "..."}

    The heavy steps (embedding, retrieve, LLM) are pushed to a thread via
    asyncio.to_thread so the event loop stays free to flush events to the
    client and answer health checks.
    """

    def _emit_dict(payload: dict[str, Any]) -> dict[str, Any]:
        # Serialize Pydantic models inside the response.
        return payload

    try:
        yield {"type": "stage", "stage": "analyzing"}

        # Load the tenant from identity (cached ~5min per worker) so we
        # can inject its identity + system_context block into the
        # answerer's prompt. Degrades to sensible defaults if identity
        # is unreachable rather than failing the query.
        tenant = get_tenant_cached(tenant_id)
        tenant_name = (tenant or {}).get("name") or "הארגון"
        tenant_context = (tenant or {}).get("system_context")

        # Resolve / create the conversation thread up front so prior turns
        # (if any) inform the rewrite, and so the final Query row can be
        # written with the right conversation_id + turn_index.
        conv = _get_or_create_conversation(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            conversation_id=conversation_id,
        )
        prior_turns = _load_prior_turns(db, conv.id) if conversation_id is not None else []
        next_turn_index = sum(1 for t in prior_turns if t.role == "user")

        # Lexicon hits + doc index for the triage step. Triage decides
        # answer-vs-clarify and produces the canonical query.
        lexicon_entries = await asyncio.to_thread(
            find_relevant_terms, db, tenant_id=tenant_id, question=question
        )
        lexicon_block = format_lexicon_block(lexicon_entries)
        lexicon_expansions = [(e.term, e.expansion) for e in lexicon_entries]

        # Cheap doc index for triage: just titles, capped to keep prompt size
        # bounded. The triage uses these to surface "did you mean doc X?".
        doc_titles_rows = (
            db.query(Document.filename)
            .filter(Document.tenant_id == tenant_id)
            .order_by(Document.ingested_at.desc())
            .limit(60)
            .all()
        )
        doc_titles = [r[0] for r in doc_titles_rows if r[0]]

        triage = await asyncio.to_thread(
            triage_turn,
            question=question,
            prior_turns=prior_turns,
            lexicon_expansions=lexicon_expansions,
            doc_titles=doc_titles,
        )

        # Clarify mode: short-circuit. No retrieval, no LLM-answer. We persist
        # the clarification as a Query turn so it shows up in the conversation
        # thread and feeds the lexicon-learning job later.
        if triage.mode == "clarify" and triage.clarifying_message:
            yield {"type": "stage", "stage": "generating"}
            yield {"type": "detail", "text": "מבקש הבהרה לפני שמחפש"}
            clar_message = triage.clarifying_message
            if triage.candidate_docs:
                clar_message += "\n\n" + "המסמכים שעולים בראש: " + ", ".join(triage.candidate_docs)
            query_log = Query(
                tenant_id=tenant_id,
                user_id=user_id,
                conversation_id=conv.id,
                turn_index=next_turn_index,
                question=question,
                answer=clar_message,
                confidence="clarifying",
                llm_used=True,
                golden_id=golden_id,
                retrieval_debug={
                    "triage_reason": triage.reason,
                    "canonical_query_guess": triage.canonical_query,
                    "candidate_docs": triage.candidate_docs,
                },
            )
            db.add(query_log)
            db.commit()
            db.refresh(query_log)
            response = SearchResponse(
                query_id=query_log.id,
                conversation_id=conv.id,
                turn_index=next_turn_index,
                mode="clarify",
                canonical_query=triage.canonical_query,
                clarifying_message=triage.clarifying_message,
                candidate_docs=triage.candidate_docs,
                question=question,
                answer=clar_message,
                confidence="clarifying",
                sources=[],
                llm_used=True,
                served_from="clarify",
            )
            yield {"type": "done", "response": response.model_dump(mode="json")}
            return

        retrieval_query = triage.canonical_query or question
        if retrieval_query != question:
            yield {
                "type": "detail",
                "text": "ניסוח השאלה הורחב בהתבסס על השיחה והמילון",
            }

        question_embedding = await asyncio.to_thread(
            lambda: embed_texts([retrieval_query], input_type="search_query")[0]
        )

        # HITL cache check — counts as part of "analyzing" since it's fast.
        cached = await asyncio.to_thread(
            find_cached_answer,
            db,
            tenant_id=tenant_id,
            question_embedding=question_embedding,
        )
        if cached is not None:
            yield {"type": "detail", "text": "נמצאה תשובה מאושרת קרובה במאגר"}
            sources = _build_sources(db, list(cached.source_chunk_ids or []))
            query_log = Query(
                tenant_id=tenant_id,
                user_id=user_id,
                conversation_id=conv.id,
                turn_index=next_turn_index,
                question=question,
                question_embedding=question_embedding,
                answer=cached.answer,
                source_chunk_ids=list(cached.source_chunk_ids or []),
                confidence="confident",
                llm_used=False,
                authoritative_answer_id=cached.id,
                golden_id=golden_id,
                retrieval_debug={"canonical_query": retrieval_query} if retrieval_query != question else None,
            )
            db.add(query_log)
            db.commit()
            db.refresh(query_log)
            response = SearchResponse(
                query_id=query_log.id,
                conversation_id=conv.id,
                turn_index=next_turn_index,
                canonical_query=retrieval_query if retrieval_query != question else None,
                question=question,
                answer=cached.answer,
                confidence="confident",
                sources=sources,
                llm_used=False,
                served_from="hitl_cache",
            )
            yield {"type": "done", "response": response.model_dump(mode="json")}
            return

        yield {"type": "stage", "stage": "searching"}
        retrieved, debug, amendment_context = await asyncio.to_thread(
            hybrid_retrieve,
            db,
            tenant_id=tenant_id,
            query=retrieval_query,
            query_embedding=question_embedding,
            top_k=top_k,
        )
        debug_dict = debug.to_dict()
        if retrieval_query != question:
            debug_dict["canonical_query"] = retrieval_query

        if not retrieved:
            query_log = Query(
                tenant_id=tenant_id,
                user_id=user_id,
                conversation_id=conv.id,
                turn_index=next_turn_index,
                question=question,
                question_embedding=question_embedding,
                answer="לא נמצאו מסמכים רלוונטיים במאגר.",
                confidence="refused",
                llm_used=False,
                golden_id=golden_id,
                retrieval_debug=debug_dict,
            )
            db.add(query_log)
            db.commit()
            db.refresh(query_log)
            response = SearchResponse(
                query_id=query_log.id,
                conversation_id=conv.id,
                turn_index=next_turn_index,
                canonical_query=retrieval_query if retrieval_query != question else None,
                question=question,
                answer="לא נמצאו מסמכים רלוונטיים במאגר. ייתכן שהנושא לא תויק או שיש לבדוק ידנית.",
                confidence="refused",
                sources=[],
                llm_used=False,
                served_from="no_documents",
                retrieval_debug=debug_dict,
            )
            yield {"type": "done", "response": response.model_dump(mode="json")}
            return

        # hybrid_retrieve runs vector + BM25 + RRF + Cohere rerank internally.
        # We emit a "ranking" stage event after it returns so the UI advances.
        yield {"type": "detail", "text": f"מצאתי {len(retrieved)} קטעים רלוונטיים"}
        yield {"type": "stage", "stage": "ranking"}
        await asyncio.sleep(0)  # let the event flush before the LLM call

        yield {"type": "stage", "stage": "generating"}
        amendment_notes = [ac.format_for_prompt() for ac in amendment_context]
        llm_result = await asyncio.to_thread(
            answer_with_citations,
            question=question,
            chunks=retrieved,
            tenant_name=tenant_name,
            tenant_context=tenant_context,
            lexicon_block=lexicon_block,
            prior_turns=prior_turns,
            amendment_notes=amendment_notes or None,
        )

        # Post-hoc safety net: if the answerer itself signals it didn't have
        # enough to go on ("השאלה אינה ברורה" / "אנא פרט" / similar), the
        # triage upstream missed an ambiguity. Convert this turn to a
        # clarification instead of persisting a "tried but confused" answer.
        # Cheaper than re-prompting; protects against future triage regressions.
        if _looks_like_self_clarification(llm_result.answer):
            log.info(
                "search_pipeline.answer_self_clarifies",
                question=question[:120],
                snippet=llm_result.answer[:160],
            )
            yield {"type": "detail", "text": "התשובה לא הספיקה — מבקש הבהרה"}
            clar_message = (
                llm_result.answer
                if llm_result.answer.strip()
                else "השאלה לא ברורה לי דיה — אפשר להבהיר על מה בדיוק אתה שואל?"
            )
            query_log = Query(
                tenant_id=tenant_id,
                user_id=user_id,
                conversation_id=conv.id,
                turn_index=next_turn_index,
                question=question,
                question_embedding=question_embedding,
                answer=clar_message,
                confidence="clarifying",
                llm_used=True,
                golden_id=golden_id,
                retrieval_debug={**debug_dict, "self_clarification": True},
            )
            db.add(query_log)
            db.commit()
            db.refresh(query_log)
            response = SearchResponse(
                query_id=query_log.id,
                conversation_id=conv.id,
                turn_index=next_turn_index,
                mode="clarify",
                canonical_query=retrieval_query if retrieval_query != question else None,
                clarifying_message=clar_message,
                candidate_docs=triage.candidate_docs,
                question=question,
                answer=clar_message,
                confidence="clarifying",
                sources=[],
                llm_used=True,
                served_from="clarify",
                retrieval_debug={**debug_dict, "self_clarification": True},
            )
            yield {"type": "done", "response": response.model_dump(mode="json")}
            return

        near_miss_rows = await asyncio.to_thread(
            find_near_misses, db, tenant_id=tenant_id, question_embedding=question_embedding
        )
        near_misses = [
            NearMiss(
                authoritative_answer_id=a.id,
                canonical_question=a.canonical_question,
                answer=a.answer,
                similarity=round(sim, 3),
            )
            for a, sim in near_miss_rows
        ]

        sources = [
            SourceCitation(
                chunk_id=c.id,
                document_id=c.document.id,
                document_filename=c.document.filename,
                section_path=c.section_path,
                text=c.text,
                has_file=bool(
                    c.document.source_uri
                    and str(c.document.source_uri).startswith("file://")
                ),
            )
            for c in retrieved
        ]

        query_log = Query(
            tenant_id=tenant_id,
            user_id=user_id,
            conversation_id=conv.id,
            turn_index=next_turn_index,
            question=question,
            question_embedding=question_embedding,
            answer=llm_result.answer,
            source_chunk_ids=[c.id for c in retrieved],
            confidence=llm_result.confidence,
            llm_used=True,
            golden_id=golden_id,
            retrieval_debug=debug_dict,
        )
        db.add(query_log)
        db.commit()
        db.refresh(query_log)

        references = [
            StructuredReference(
                title=r.title,
                section_number=r.section_number,
                source_type=r.source_type,
                excerpt=r.excerpt,
            )
            for r in llm_result.references
        ]

        response = SearchResponse(
            query_id=query_log.id,
            conversation_id=conv.id,
            turn_index=next_turn_index,
            canonical_query=retrieval_query if retrieval_query != question else None,
            question=question,
            answer=llm_result.answer,
            confidence=llm_result.confidence,
            sources=sources,
            references=references,
            llm_used=True,
            served_from="llm",
            retrieval_debug=debug_dict,
            near_misses=near_misses,
        )
        yield {"type": "done", "response": response.model_dump(mode="json")}
    except Exception as e:
        log.exception("search_pipeline.failed", err=str(e))
        yield {"type": "error", "detail": str(e)}


@router.post("", response_model=SearchResponse)
async def search(
    req: SearchRequest,
    db: Session = Depends(get_db),
    user: IdentityUser = Depends(current_user),
) -> SearchResponse:
    """JSON endpoint — runs the pipeline to completion and returns the final
    SearchResponse. Identical behavior to /search/stream, just without the
    intermediate progress events."""
    last_event: dict[str, Any] | None = None
    async for ev in search_pipeline(
        db,
        tenant_id=user.tenant_id,
        user_id=user.id,
        question=req.question,
        top_k=req.top_k,
        conversation_id=req.conversation_id,
        golden_id=req.golden_id,
    ):
        if ev["type"] in ("done", "error"):
            last_event = ev
    if last_event is None or last_event["type"] == "error":
        raise HTTPException(500, last_event["detail"] if last_event else "Pipeline produced no result")
    return SearchResponse(**last_event["response"])


@router.post("/stream")
async def search_stream(
    req: SearchRequest,
    user: IdentityUser = Depends(current_user),
):
    """Server-Sent Events endpoint — emits progress events as the pipeline
    runs, ending with a "done" event carrying the full SearchResponse JSON.

    The client opens this via fetch() with a ReadableStream body parser
    (EventSource doesn't support POST). Each SSE message is one JSON event.
    """
    # SSE handlers can't use Depends(get_db) because the request-scoped session
    # closes before the generator finishes streaming. Open our own session.
    db: Session = SessionLocal()

    async def event_stream() -> AsyncIterator[bytes]:
        try:
            async for ev in search_pipeline(
                db,
                tenant_id=user.tenant_id,
                user_id=user.id,
                question=req.question,
                top_k=req.top_k,
                conversation_id=req.conversation_id,
                golden_id=req.golden_id,
            ):
                payload = json.dumps(ev, ensure_ascii=False)
                yield f"data: {payload}\n\n".encode("utf-8")
        finally:
            db.close()

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            # Disable any buffering between FastAPI and the client (nginx, Render's
            # proxy, etc.) — otherwise events get held until the response ends.
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.get("/recent", response_model=list[str])
def recent_questions(
    db: Session = Depends(get_db),
    user: IdentityUser = Depends(current_user),
    limit: int = QParam(8, ge=1, le=25),
) -> list[str]:
    """Distinct recent questions for the caller's tenant — drives the
    "recently asked" list on the search page. Same-text repeats collapse
    to one entry showing the most recent occurrence."""
    rows = (
        db.query(Query.question, func.max(Query.created_at).label("last_at"))
        .filter(Query.tenant_id == user.tenant_id)
        .filter(Query.question.isnot(None))
        .group_by(Query.question)
        .order_by(func.max(Query.created_at).desc())
        .limit(limit)
        .all()
    )
    return [r.question for r in rows]


class FeedbackRequest(BaseModel):
    feedback: str  # positive | negative


@router.post("/{query_id}/feedback")
def submit_feedback(
    query_id: UUID,
    req: FeedbackRequest,
    db: Session = Depends(get_db),
    user: IdentityUser = Depends(current_user),
) -> dict:
    """👍 / 👎 on a returned answer — the in-flow signal Ido gives.

    A 👎 on an answer served from the authoritative cache also retires that
    cached answer, so the next ask of a similar question falls through to
    fresh retrieve+LLM instead of returning the same wrong cached answer.
    """
    if req.feedback not in {"positive", "negative"}:
        raise HTTPException(400, "feedback must be 'positive' or 'negative'")

    query = db.get(Query, query_id)
    if query is None or query.tenant_id != user.tenant_id:
        # 404 (not 403) so we don't leak existence of other tenants' queries.
        raise HTTPException(404, "Query not found")

    query.feedback = req.feedback

    cached_answer_retired = False
    if req.feedback == "negative" and query.authoritative_answer_id:
        from app.models import AuthoritativeAnswer

        authoritative = db.get(AuthoritativeAnswer, query.authoritative_answer_id)
        if authoritative is not None and authoritative.status == "active":
            authoritative.status = "retired"
            cached_answer_retired = True

    db.commit()
    return {"status": "ok", "cached_answer_retired": cached_answer_retired}


class FailureModeRequest(BaseModel):
    failure_mode: str  # retrieval_miss | wrong_generation | other


@router.post("/{query_id}/failure-mode")
def tag_failure_mode(
    query_id: UUID,
    req: FailureModeRequest,
    db: Session = Depends(get_db),
    user: IdentityUser = Depends(current_user),
) -> dict:
    """Tag *why* an answer was wrong, so we can route the fix correctly."""
    valid = {"retrieval_miss", "wrong_generation", "other"}
    if req.failure_mode not in valid:
        raise HTTPException(400, f"failure_mode must be one of {valid}")
    query = db.get(Query, query_id)
    if query is None or query.tenant_id != user.tenant_id:
        raise HTTPException(404, "Query not found")
    query.failure_mode = req.failure_mode
    if not query.feedback:
        query.feedback = "negative"
    db.commit()
    return {"status": "ok"}


# ─────────────────────────────────────────────────────────────────────────
# Simplified end-user feedback: two buttons, no follow-up dialog.
#   mark-good   → promote to authoritative answer immediately (auto-approve)
#   mark-broken → flag for the super-admin's debug queue (retrieval_miss)
# Replaces the old positive/negative → follow-up failure-mode picker.
# ─────────────────────────────────────────────────────────────────────────


class MarkGoodResponse(BaseModel):
    status: str
    authoritative_answer_id: UUID | None = None


@router.post("/{query_id}/mark-good", response_model=MarkGoodResponse)
def mark_good(
    query_id: UUID,
    db: Session = Depends(get_db),
    user: IdentityUser = Depends(current_user),
) -> MarkGoodResponse:
    """User marked the answer as good — auto-promote to authoritative library.

    Idempotent: if the query already has an authoritative answer attached,
    just re-confirms feedback and returns that id.
    """
    query = db.get(Query, query_id)
    if query is None or query.tenant_id != user.tenant_id:
        raise HTTPException(404, "Query not found")

    query.feedback = "positive"

    # Already promoted (either by prior click or by the reviewer queue) —
    # nothing more to do.
    if query.authoritative_answer_id:
        db.commit()
        return MarkGoodResponse(
            status="ok",
            authoritative_answer_id=query.authoritative_answer_id,
        )

    final_answer = (query.answer or "").strip()
    if not final_answer or query.confidence == "refused":
        # Nothing to promote — still record the positive signal.
        db.commit()
        return MarkGoodResponse(status="ok", authoritative_answer_id=None)

    auth = AuthoritativeAnswer(
        tenant_id=query.tenant_id,
        canonical_question=query.question,
        canonical_question_embedding=query.question_embedding,
        answer=final_answer,
        source_chunk_ids=query.source_chunk_ids,
        status="active",
    )
    db.add(auth)
    db.flush()
    query.authoritative_answer_id = auth.id
    query.reviewer_action = "approved"
    db.commit()

    log.info(
        "search.mark_good",
        query_id=str(query_id),
        auth_id=str(auth.id),
        tenant_id=str(query.tenant_id),
    )
    return MarkGoodResponse(status="ok", authoritative_answer_id=auth.id)


@router.post("/{query_id}/mark-broken")
def mark_broken(
    query_id: UUID,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user: IdentityUser = Depends(current_user),
) -> dict:
    """User marked the answer as wrong ("the corpus knows the right answer,
    the system just didn't find it") — surfaces in the super-admin debug queue.

    If the query is currently attached to a cached authoritative answer,
    retire that cache entry so future asks fall through to fresh retrieval.
    """
    query = db.get(Query, query_id)
    if query is None or query.tenant_id != user.tenant_id:
        raise HTTPException(404, "Query not found")

    query.feedback = "negative"
    query.failure_mode = "retrieval_miss"

    cached_answer_retired = False
    if query.authoritative_answer_id:
        cached = db.get(AuthoritativeAnswer, query.authoritative_answer_id)
        if cached is not None and cached.status == "active":
            cached.status = "retired"
            cached_answer_retired = True

    db.commit()
    log.info(
        "search.mark_broken",
        query_id=str(query_id),
        tenant_id=str(query.tenant_id),
        retired_cache=cached_answer_retired,
    )

    # Notify every super-admin. Users + tenants live in identity now;
    # pull both there. If identity is unreachable we log and skip the
    # notification — the mark-broken flag itself is already saved.
    try:
        super_admin_emails = [
            u["email"]
            for u in identity_service.list_users()
            if u.get("is_super_admin")
        ]
    except Exception as e:  # noqa: BLE001
        log.warning("search.mark_broken_list_super_admins_failed", error=str(e))
        super_admin_emails = []

    tenant = get_tenant_cached(query.tenant_id)
    tenant_name = (tenant or {}).get("name") or str(query.tenant_id)

    if super_admin_emails:
        background_tasks.add_task(
            send_broken_answer_alert,
            to_emails=super_admin_emails,
            tenant_name=tenant_name,
            question=query.question,
            answer=query.answer,
            query_id=str(query.id),
            marked_by_email=user.email,
        )

    return {"status": "ok", "cached_answer_retired": cached_answer_retired}
