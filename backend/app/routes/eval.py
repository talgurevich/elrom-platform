"""Golden Q&A regression eval.

A golden question pins down what a *correct* answer looks like:
- expected_doc_filenames: which documents must appear in the retrieved sources
- expected_keywords: substrings that must appear in the answer text

Running the eval re-issues every golden through the live search pipeline and
scores it. This is what turns "I think it got worse" into measurable signal
after a prompt / embedding / chunking change.
"""
from datetime import datetime, timezone
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from sqlalchemy import func

from app.db import get_db
from app.models import GoldenQuestion, Query
from app.services.identity import IdentityUser, current_user
from app.services.embedding import embed_texts
from app.services.lexicon import find_relevant_terms, format_lexicon_block
from app.services.llm import answer_with_citations
from app.services.retrieval import hybrid_retrieve

log = structlog.get_logger()
router = APIRouter()


# ─── Schemas ───────────────────────────────────────────────────────────


class GoldenIn(BaseModel):
    question: str
    expected_doc_filenames: list[str] | None = None
    expected_keywords: list[str] | None = None
    expected_answer: str | None = None
    notes: str | None = None


class PromoteGoldenIn(BaseModel):
    """Body for /goldens/from-query — all fields optional because the source
    query supplies sensible defaults (question, answer, cited filenames)."""

    question: str | None = None
    expected_doc_filenames: list[str] | None = None
    expected_keywords: list[str] | None = None
    expected_answer: str | None = None
    notes: str | None = None


class GoldenOut(BaseModel):
    id: UUID
    question: str
    expected_doc_filenames: list[str] | None
    expected_keywords: list[str] | None
    expected_answer: str | None
    notes: str | None
    source_query_id: UUID | None
    created_at: datetime
    last_run_at: datetime | None
    last_score: float | None
    last_retrieval_score: float | None
    last_keyword_score: float | None
    last_confidence: str | None


class EvalRunResult(BaseModel):
    golden_id: UUID
    question: str
    score: float
    retrieval_score: float | None
    keyword_score: float | None
    confidence: str
    retrieved_filenames: list[str]
    missing_filenames: list[str]
    missing_keywords: list[str]


class EvalRunSummary(BaseModel):
    total: int
    avg_score: float
    avg_retrieval: float | None
    avg_keyword: float | None
    confidence_counts: dict[str, int]
    results: list[EvalRunResult]


# ─── Helpers ───────────────────────────────────────────────────────────


def _to_out(g: GoldenQuestion) -> GoldenOut:
    return GoldenOut(
        id=g.id,
        question=g.question,
        expected_doc_filenames=g.expected_doc_filenames,
        expected_keywords=g.expected_keywords,
        expected_answer=g.expected_answer,
        notes=g.notes,
        source_query_id=g.source_query_id,
        created_at=g.created_at,
        last_run_at=g.last_run_at,
        last_score=g.last_score,
        last_retrieval_score=g.last_retrieval_score,
        last_keyword_score=g.last_keyword_score,
        last_confidence=g.last_confidence,
    )


def _score_golden(db: Session, tenant_id: UUID, g: GoldenQuestion) -> EvalRunResult:
    """Re-run a single golden through the live pipeline and score."""
    q_emb = embed_texts([g.question], input_type="search_query")[0]
    retrieved, _debug, amendment_context = hybrid_retrieve(
        db, tenant_id=tenant_id, query=g.question, query_embedding=q_emb, top_k=5
    )
    retrieved_filenames = [c.document.filename for c in retrieved]

    if retrieved:
        lex = find_relevant_terms(db, tenant_id=tenant_id, question=g.question)
        llm = answer_with_citations(
            question=g.question,
            chunks=retrieved,
            lexicon_block=format_lexicon_block(lex),
            amendment_notes=[ac.format_for_prompt() for ac in amendment_context] or None,
        )
        answer_text = llm.answer
        confidence = llm.confidence
    else:
        answer_text = ""
        confidence = "refused"

    retrieval_score: float | None = None
    missing_filenames: list[str] = []
    if g.expected_doc_filenames:
        hit = [f for f in g.expected_doc_filenames if f in retrieved_filenames]
        missing_filenames = [f for f in g.expected_doc_filenames if f not in retrieved_filenames]
        retrieval_score = len(hit) / len(g.expected_doc_filenames)

    keyword_score: float | None = None
    missing_keywords: list[str] = []
    if g.expected_keywords:
        hit_kw = [kw for kw in g.expected_keywords if kw in answer_text]
        missing_keywords = [kw for kw in g.expected_keywords if kw not in answer_text]
        keyword_score = len(hit_kw) / len(g.expected_keywords)

    parts = [s for s in (retrieval_score, keyword_score) if s is not None]
    composite = sum(parts) / len(parts) if parts else (1.0 if confidence == "confident" else 0.0)

    g.last_run_at = datetime.now(timezone.utc)
    g.last_score = composite
    g.last_retrieval_score = retrieval_score
    g.last_keyword_score = keyword_score
    g.last_confidence = confidence

    return EvalRunResult(
        golden_id=g.id,
        question=g.question,
        score=composite,
        retrieval_score=retrieval_score,
        keyword_score=keyword_score,
        confidence=confidence,
        retrieved_filenames=retrieved_filenames,
        missing_filenames=missing_filenames,
        missing_keywords=missing_keywords,
    )


# ─── Routes ────────────────────────────────────────────────────────────


@router.get("/goldens", response_model=list[GoldenOut])
def list_goldens(
    db: Session = Depends(get_db),
    user: IdentityUser = Depends(current_user),
) -> list[GoldenOut]:
    goldens = (
        db.query(GoldenQuestion)
        .filter(GoldenQuestion.tenant_id == user.tenant_id)
        .order_by(GoldenQuestion.created_at.desc())
        .all()
    )
    return [_to_out(g) for g in goldens]


@router.post("/goldens", response_model=GoldenOut)
def create_golden(
    body: GoldenIn,
    db: Session = Depends(get_db),
    user: IdentityUser = Depends(current_user),
) -> GoldenOut:
    g = GoldenQuestion(
        tenant_id=user.tenant_id,
        question=body.question.strip(),
        expected_doc_filenames=body.expected_doc_filenames or None,
        expected_keywords=body.expected_keywords or None,
        expected_answer=body.expected_answer,
        notes=body.notes,
    )
    db.add(g)
    db.commit()
    db.refresh(g)
    return _to_out(g)


@router.post("/goldens/from-query/{query_id}", response_model=GoldenOut)
def promote_query_to_golden(
    query_id: UUID,
    body: PromoteGoldenIn | None = None,
    db: Session = Depends(get_db),
    user: IdentityUser = Depends(current_user),
) -> GoldenOut:
    """Promote an existing answered query into a golden. Defaults pull from the
    query (the cited sources become expected_doc_filenames) but the caller can
    override every field."""
    query = db.get(Query, query_id)
    if query is None or query.tenant_id != user.tenant_id:
        raise HTTPException(404, "Query not found")

    expected_filenames: list[str] | None = None
    if query.source_chunk_ids:
        from app.models import Chunk

        chunks = (
            db.query(Chunk)
            .filter(Chunk.id.in_(query.source_chunk_ids))
            .all()
        )
        expected_filenames = sorted({c.document.filename for c in chunks})

    g = GoldenQuestion(
        tenant_id=user.tenant_id,
        question=(body.question if body and body.question else query.question).strip(),
        expected_doc_filenames=(body.expected_doc_filenames if body and body.expected_doc_filenames else expected_filenames),
        expected_keywords=(body.expected_keywords if body else None),
        expected_answer=(body.expected_answer if body and body.expected_answer else query.answer),
        notes=(body.notes if body else None),
        source_query_id=query.id,
    )
    db.add(g)
    db.commit()
    db.refresh(g)
    return _to_out(g)


@router.delete("/goldens/{golden_id}")
def delete_golden(
    golden_id: UUID,
    db: Session = Depends(get_db),
    user: IdentityUser = Depends(current_user),
) -> dict:
    g = db.get(GoldenQuestion, golden_id)
    if g is None or g.tenant_id != user.tenant_id:
        raise HTTPException(404, "Golden not found")
    db.delete(g)
    db.commit()
    return {"status": "ok"}


# ─── Manual pass-rate report ──────────────────────────────────────────
#
# Distinct from POST /run (the automated regression scorer). This endpoint
# aggregates the human 👍/👎 signals on Query rows that were dispatched with
# a golden_id — i.e. when a user runs a golden through the live chat and
# marks the answer good/bad, that judgement flows into per-golden counts
# and an overall pass rate.


class GoldenReportRow(BaseModel):
    golden_id: UUID
    question: str
    total_runs: int
    positive: int
    negative: int
    unmarked: int
    pass_rate: float | None  # positive / (positive + negative); None if never marked
    last_run_at: datetime | None
    last_feedback: str | None  # positive | negative | None
    # Latest run's full details, so the eval UI can render inline 👍/👎 on
    # goldens that were already run in chat but never marked.
    latest_query_id: UUID | None = None
    latest_answer: str | None = None
    latest_confidence: str | None = None


class GoldenReport(BaseModel):
    total_goldens: int
    goldens_with_runs: int
    goldens_with_feedback: int
    total_runs: int
    total_positive: int
    total_negative: int
    overall_pass_rate: float | None  # across all marked runs
    rows: list[GoldenReportRow]


@router.get("/report", response_model=GoldenReport)
def golden_report(
    db: Session = Depends(get_db),
    user: IdentityUser = Depends(current_user),
) -> GoldenReport:
    """Per-golden pass-rate from human 👍/👎 marks on live-chat runs.

    A run counts only if the Query was issued with a golden_id (i.e. via
    the "run golden" flow). Unmarked runs are shown but excluded from
    pass_rate — no signal means no verdict, not a failure.
    """
    tenant_id = user.tenant_id

    goldens = (
        db.query(GoldenQuestion)
        .filter(GoldenQuestion.tenant_id == tenant_id)
        .order_by(GoldenQuestion.created_at.desc())
        .all()
    )

    # One grouped query — (golden_id, feedback) → count + latest run.
    agg_rows = (
        db.query(
            Query.golden_id,
            Query.feedback,
            func.count(Query.id).label("cnt"),
            func.max(Query.created_at).label("last_at"),
        )
        .filter(Query.tenant_id == tenant_id, Query.golden_id.isnot(None))
        .group_by(Query.golden_id, Query.feedback)
        .all()
    )

    # Fetch the latest Query row per golden (full row, not just aggregate) so
    # the UI can render inline 👍/👎 grading for runs that were done in chat
    # but not marked at the time. Uses DISTINCT ON — Postgres-specific but
    # this file already assumes Postgres via pgvector etc.
    from sqlalchemy import desc
    latest_query_rows = (
        db.query(Query.id, Query.golden_id, Query.answer, Query.confidence, Query.created_at)
        .filter(Query.tenant_id == tenant_id, Query.golden_id.isnot(None))
        .order_by(Query.golden_id, desc(Query.created_at))
        .distinct(Query.golden_id)
        .all()
    )
    latest_by_golden = {
        r.golden_id: {"id": r.id, "answer": r.answer, "confidence": r.confidence}
        for r in latest_query_rows
    }

    # golden_id → {"positive": n, "negative": n, "unmarked": n, "last_at": ts, "last_feedback": str|None}
    per_golden: dict[UUID, dict] = {}
    for r in agg_rows:
        entry = per_golden.setdefault(
            r.golden_id,
            {"positive": 0, "negative": 0, "unmarked": 0, "last_at": None, "last_feedback": None},
        )
        bucket = r.feedback if r.feedback in ("positive", "negative") else "unmarked"
        entry[bucket] += r.cnt
        if entry["last_at"] is None or r.last_at > entry["last_at"]:
            entry["last_at"] = r.last_at
            entry["last_feedback"] = r.feedback  # may be None for the newest run

    rows: list[GoldenReportRow] = []
    total_positive = 0
    total_negative = 0
    total_runs = 0
    goldens_with_runs = 0
    goldens_with_feedback = 0
    for g in goldens:
        e = per_golden.get(g.id)
        if e is None:
            rows.append(
                GoldenReportRow(
                    golden_id=g.id,
                    question=g.question,
                    total_runs=0,
                    positive=0,
                    negative=0,
                    unmarked=0,
                    pass_rate=None,
                    last_run_at=None,
                    last_feedback=None,
                )
            )
            continue
        pos, neg, unm = e["positive"], e["negative"], e["unmarked"]
        marked = pos + neg
        total = pos + neg + unm
        goldens_with_runs += 1
        if marked:
            goldens_with_feedback += 1
        total_positive += pos
        total_negative += neg
        total_runs += total
        latest = latest_by_golden.get(g.id)
        rows.append(
            GoldenReportRow(
                golden_id=g.id,
                question=g.question,
                total_runs=total,
                positive=pos,
                negative=neg,
                unmarked=unm,
                pass_rate=(pos / marked) if marked else None,
                last_run_at=e["last_at"],
                last_feedback=e["last_feedback"],
                latest_query_id=latest["id"] if latest else None,
                latest_answer=latest["answer"] if latest else None,
                latest_confidence=latest["confidence"] if latest else None,
            )
        )

    overall_marked = total_positive + total_negative
    overall_pass_rate = (total_positive / overall_marked) if overall_marked else None

    return GoldenReport(
        total_goldens=len(goldens),
        goldens_with_runs=goldens_with_runs,
        goldens_with_feedback=goldens_with_feedback,
        total_runs=total_runs,
        total_positive=total_positive,
        total_negative=total_negative,
        overall_pass_rate=overall_pass_rate,
        rows=rows,
    )


@router.post("/run/{golden_id}", response_model=EvalRunResult)
def run_single_golden(
    golden_id: UUID,
    db: Session = Depends(get_db),
    user: IdentityUser = Depends(current_user),
) -> EvalRunResult:
    """Score one golden. The frontend loops through the set calling this
    once per golden, which keeps each request short enough to survive
    Render's proxy timeout (the batch /run endpoint below dies on ~10+
    goldens once each LLM call is added up)."""
    g = db.get(GoldenQuestion, golden_id)
    if g is None or g.tenant_id != user.tenant_id:
        raise HTTPException(404, "Golden not found")
    result = _score_golden(db, user.tenant_id, g)
    db.commit()
    return result


@router.post("/run", response_model=EvalRunSummary)
def run_eval(
    db: Session = Depends(get_db),
    user: IdentityUser = Depends(current_user),
) -> EvalRunSummary:
    """Batch runner. Kept for CLI/scripts, but the UI now uses /run/{id}
    per-golden to avoid the proxy timeout on large golden sets."""
    tenant_id = user.tenant_id
    goldens = (
        db.query(GoldenQuestion)
        .filter(GoldenQuestion.tenant_id == tenant_id)
        .all()
    )
    if not goldens:
        raise HTTPException(400, "No golden questions defined yet")

    results = [_score_golden(db, tenant_id, g) for g in goldens]
    db.commit()

    avg_score = sum(r.score for r in results) / len(results)
    ret_scores = [r.retrieval_score for r in results if r.retrieval_score is not None]
    kw_scores = [r.keyword_score for r in results if r.keyword_score is not None]
    avg_retrieval = sum(ret_scores) / len(ret_scores) if ret_scores else None
    avg_keyword = sum(kw_scores) / len(kw_scores) if kw_scores else None

    confidence_counts: dict[str, int] = {}
    for r in results:
        confidence_counts[r.confidence] = confidence_counts.get(r.confidence, 0) + 1

    return EvalRunSummary(
        total=len(results),
        avg_score=avg_score,
        avg_retrieval=avg_retrieval,
        avg_keyword=avg_keyword,
        confidence_counts=confidence_counts,
        results=results,
    )
