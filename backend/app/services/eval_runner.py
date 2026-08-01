"""Golden-set eval runner — shared scoring + post-deploy regression watch.

Two consumers:
  * routes/eval.py — the manual per-golden and batch endpoints.
  * the post-deploy task launched from app startup (main.py) — waits for
    the service to settle, claims a deploy-run row per tenant (partial
    unique index on tenant_id+git_sha keeps WEB_CONCURRENCY workers from
    double-running), scores every golden, records an EvalRun, and emails
    the super-admins when the average score regressed beyond
    settings.eval_regression_threshold.

This is the regression gate the user chose ("post-deploy on Render"):
not a pre-push check, but every deploy gets scored automatically and a
drop is loud instead of silent.
"""
import asyncio
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from uuid import UUID

import structlog
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.db import SessionLocal
from app.models import EvalRun, GoldenQuestion
from app.services.embedding import embed_texts
from app.services.lexicon import find_relevant_terms, format_lexicon_block
from app.services.llm import answer_with_citations
from app.services.retrieval import hybrid_retrieve

log = structlog.get_logger()


@dataclass
class GoldenScore:
    golden_id: UUID
    question: str
    score: float
    retrieval_score: float | None
    keyword_score: float | None
    confidence: str
    retrieved_filenames: list[str]
    missing_filenames: list[str]
    missing_keywords: list[str]


def score_golden(db: Session, tenant_id: UUID, g: GoldenQuestion) -> GoldenScore:
    """Re-run a single golden through the live pipeline and score it.

    Also updates the golden's last_* columns (caller commits).
    """
    q_emb = embed_texts([g.question], input_type="search_query")[0]
    retrieved, _debug, amendment_context, resolution_context = hybrid_retrieve(
        db, tenant_id=tenant_id, query=g.question, query_embedding=q_emb, top_k=5
    )
    retrieved_filenames = [c.document.filename for c in retrieved]

    if retrieved:
        lex = find_relevant_terms(
            db, tenant_id=tenant_id, question=g.question, record_events=False
        )
        # Same tenant identity/context injection as the live search path —
        # goldens must be scored against the prompt users actually get.
        from app.services.identity import get_tenant_cached

        tenant = get_tenant_cached(tenant_id)
        llm = answer_with_citations(
            question=g.question,
            chunks=retrieved,
            tenant_name=(tenant or {}).get("name") or "הארגון",
            tenant_context=(tenant or {}).get("system_context"),
            lexicon_block=format_lexicon_block(lex),
            amendment_notes=[ac.format_for_prompt() for ac in amendment_context] or None,
            resolution_notes=[rc.format_for_prompt() for rc in resolution_context] or None,
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

    return GoldenScore(
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


def run_and_record(
    db: Session, *, tenant_id: UUID, trigger: str, git_sha: str | None
) -> EvalRun | None:
    """Score every golden for the tenant, persist an EvalRun row.

    For trigger='deploy', the row is inserted FIRST as a claim (partial
    unique index on tenant_id+git_sha) — an IntegrityError means another
    worker owns this deploy's run, and we return None.
    """
    goldens = (
        db.query(GoldenQuestion).filter(GoldenQuestion.tenant_id == tenant_id).all()
    )
    if not goldens:
        return None

    run = EvalRun(tenant_id=tenant_id, trigger=trigger, git_sha=git_sha or None)
    db.add(run)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        log.info(
            "eval_runner.deploy_run_already_claimed",
            tenant_id=str(tenant_id),
            git_sha=git_sha,
        )
        return None

    scores = [score_golden(db, tenant_id, g) for g in goldens]

    avg_score = sum(s.score for s in scores) / len(scores)
    ret = [s.retrieval_score for s in scores if s.retrieval_score is not None]
    kw = [s.keyword_score for s in scores if s.keyword_score is not None]
    confidence_counts: dict[str, int] = {}
    for s in scores:
        confidence_counts[s.confidence] = confidence_counts.get(s.confidence, 0) + 1

    run.finished_at = datetime.now(timezone.utc)
    run.total = len(scores)
    run.avg_score = avg_score
    run.avg_retrieval = sum(ret) / len(ret) if ret else None
    run.avg_keyword = sum(kw) / len(kw) if kw else None
    run.confidence_counts = confidence_counts
    # Compact per-golden results — enough to see WHICH golden regressed
    # without re-running. UUIDs stringified for JSON.
    run.results = [
        {**asdict(s), "golden_id": str(s.golden_id)} for s in scores
    ]
    db.commit()
    log.info(
        "eval_runner.run_recorded",
        tenant_id=str(tenant_id),
        trigger=trigger,
        total=run.total,
        avg_score=round(avg_score, 3),
    )
    return run


def previous_finished_run(db: Session, *, tenant_id: UUID, before: EvalRun) -> EvalRun | None:
    return (
        db.query(EvalRun)
        .filter(
            EvalRun.tenant_id == tenant_id,
            EvalRun.finished_at.isnot(None),
            EvalRun.id != before.id,
            EvalRun.started_at < before.started_at,
        )
        .order_by(EvalRun.started_at.desc())
        .first()
    )


def _regressed_goldens(prev: EvalRun, cur: EvalRun) -> list[dict]:
    """Per-golden diff: goldens whose score dropped between runs."""
    prev_by_id = {r["golden_id"]: r for r in (prev.results or [])}
    out = []
    for r in cur.results or []:
        p = prev_by_id.get(r["golden_id"])
        if p is not None and r["score"] < p["score"]:
            out.append(
                {
                    "question": r["question"],
                    "prev_score": p["score"],
                    "new_score": r["score"],
                    "missing_filenames": r.get("missing_filenames") or [],
                    "missing_keywords": r.get("missing_keywords") or [],
                }
            )
    return out


def run_post_deploy_eval() -> None:
    """Entry point for the startup background task (sync — call via
    asyncio.to_thread). Runs the eval per tenant-with-goldens for the
    current deploy SHA and alerts super-admins on regression."""
    git_sha = (settings.render_git_commit or "").strip()
    if not git_sha:
        log.info("eval_runner.skip_no_git_sha")
        return

    from app.services.identity import list_super_admin_emails, list_tenants_as_rows
    from app.services.mail import send_eval_regression_alert

    try:
        tenants = list_tenants_as_rows()
    except Exception as e:  # noqa: BLE001 — identity outage must not crash startup
        log.warning("eval_runner.list_tenants_failed", error=str(e)[:200])
        return

    for t in tenants:
        db = SessionLocal()
        try:
            run = run_and_record(db, tenant_id=t.id, trigger="deploy", git_sha=git_sha)
            if run is None:
                continue
            prev = previous_finished_run(db, tenant_id=t.id, before=run)
            if prev is None or prev.avg_score is None or run.avg_score is None:
                continue
            delta = run.avg_score - prev.avg_score
            if delta < -settings.eval_regression_threshold:
                log.warning(
                    "eval_runner.regression",
                    tenant=t.name,
                    prev=round(prev.avg_score, 3),
                    new=round(run.avg_score, 3),
                    delta=round(delta, 3),
                    git_sha=git_sha[:12],
                )
                try:
                    emails = list_super_admin_emails()
                except Exception:  # noqa: BLE001
                    emails = []
                if emails:
                    send_eval_regression_alert(
                        to_emails=emails,
                        tenant_name=t.name,
                        prev_score=prev.avg_score,
                        new_score=run.avg_score,
                        git_sha=git_sha,
                        regressed=_regressed_goldens(prev, run),
                    )
        except Exception as e:  # noqa: BLE001 — one tenant failing must not stop the rest
            log.warning(
                "eval_runner.tenant_failed", tenant=t.name, error=str(e)[:300]
            )
        finally:
            db.close()


async def post_deploy_eval_task() -> None:
    """Startup wrapper: wait for the service to settle (health checks,
    migrations, first requests), then run the eval off the event loop."""
    try:
        await asyncio.sleep(settings.eval_on_deploy_delay_seconds)
        await asyncio.to_thread(run_post_deploy_eval)
    except Exception as e:  # noqa: BLE001 — background task must never crash the app
        log.warning("eval_runner.post_deploy_task_failed", error=str(e)[:300])
