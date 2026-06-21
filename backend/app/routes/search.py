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
from fastapi import APIRouter, Depends, HTTPException, Query as QParam
from fastapi.responses import StreamingResponse
from sqlalchemy import func
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import SessionLocal, get_db
from app.models import AuthoritativeAnswer, Chunk, Query, Tenant, User
from app.routes.auth import current_user
from app.services.embedding import embed_texts
from app.services.hitl import find_cached_answer, find_near_misses
from app.services.lexicon import find_relevant_terms, format_lexicon_block
from app.services.llm import answer_with_citations
from app.services.retrieval import hybrid_retrieve

log = structlog.get_logger()
router = APIRouter()


class SearchRequest(BaseModel):
    question: str
    top_k: int = 5


class SourceCitation(BaseModel):
    chunk_id: UUID
    document_filename: str
    section_path: str | None
    text: str


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
    question: str
    answer: str
    confidence: str  # confident | uncertain | refused
    sources: list[SourceCitation]
    references: list[StructuredReference] = []
    llm_used: bool
    served_from: str  # "hitl_cache" | "llm" | "no_documents"
    retrieval_debug: dict | None = None
    near_misses: list[NearMiss] = []


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
            document_filename=c.document.filename,
            section_path=c.section_path,
            text=c.text,
        )
        for cid in chunk_ids
        if (c := by_id.get(cid)) is not None
    ]


async def search_pipeline(
    db: Session, *, tenant_id: UUID, question: str, top_k: int
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
        question_embedding = await asyncio.to_thread(
            lambda: embed_texts([question], input_type="search_query")[0]
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
                question=question,
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
            response = SearchResponse(
                query_id=query_log.id,
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
        retrieved, debug = await asyncio.to_thread(
            hybrid_retrieve,
            db,
            tenant_id=tenant_id,
            query=question,
            query_embedding=question_embedding,
            top_k=top_k,
        )
        debug_dict = debug.to_dict()

        if not retrieved:
            query_log = Query(
                tenant_id=tenant_id,
                question=question,
                question_embedding=question_embedding,
                answer="לא נמצאו מסמכים רלוונטיים במאגר.",
                confidence="refused",
                llm_used=False,
                retrieval_debug=debug_dict,
            )
            db.add(query_log)
            db.commit()
            db.refresh(query_log)
            response = SearchResponse(
                query_id=query_log.id,
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
        lexicon_entries = await asyncio.to_thread(
            find_relevant_terms, db, tenant_id=tenant_id, question=question
        )
        lexicon_block = format_lexicon_block(lexicon_entries)
        llm_result = await asyncio.to_thread(
            answer_with_citations,
            question=question,
            chunks=retrieved,
            lexicon_block=lexicon_block,
        )

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
                document_filename=c.document.filename,
                section_path=c.section_path,
                text=c.text,
            )
            for c in retrieved
        ]

        query_log = Query(
            tenant_id=tenant_id,
            question=question,
            question_embedding=question_embedding,
            answer=llm_result.answer,
            source_chunk_ids=[c.id for c in retrieved],
            confidence=llm_result.confidence,
            llm_used=True,
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
    user: User = Depends(current_user),
) -> SearchResponse:
    """JSON endpoint — runs the pipeline to completion and returns the final
    SearchResponse. Identical behavior to /search/stream, just without the
    intermediate progress events."""
    last_event: dict[str, Any] | None = None
    async for ev in search_pipeline(
        db, tenant_id=user.tenant_id, question=req.question, top_k=req.top_k
    ):
        if ev["type"] in ("done", "error"):
            last_event = ev
    if last_event is None or last_event["type"] == "error":
        raise HTTPException(500, last_event["detail"] if last_event else "Pipeline produced no result")
    return SearchResponse(**last_event["response"])


@router.post("/stream")
async def search_stream(
    req: SearchRequest,
    user: User = Depends(current_user),
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
                db, tenant_id=user.tenant_id, question=req.question, top_k=req.top_k
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
    user: User = Depends(current_user),
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
    user: User = Depends(current_user),
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
    user: User = Depends(current_user),
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
