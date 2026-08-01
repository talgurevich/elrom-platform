"""In-process ingestion worker — processes queued IngestJob rows.

Design (user-selected: in-process, no new infra):
  * Each uvicorn worker runs one loop task, started at app startup.
  * Claiming uses FOR UPDATE SKIP LOCKED, so multiple workers never
    double-process a job — and two workers simply double the throughput.
  * The actual pipeline (extraction/OCR/chunk/embed) is synchronous and
    runs via asyncio.to_thread, keeping /api/health responsive during a
    multi-minute OCR job — the exact failure Render restarts used to
    cause when this ran inside the request.
  * On startup each loop first requeues stale 'processing' rows (a worker
    died mid-job). attempts caps runaway retries at MAX_ATTEMPTS.
"""
import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

import structlog
from sqlalchemy import text as sa_text

from app.db import SessionLocal
from app.models import IngestJob
from app.routes.documents import classify_document_by_id_bg
from app.services.ingest_pipeline import IngestRejection, run_upload_pipeline

log = structlog.get_logger()

POLL_SECONDS = 3.0
STALE_PROCESSING_MINUTES = 30
MAX_ATTEMPTS = 2


def _requeue_stale_jobs() -> int:
    """Jobs stuck in 'processing' past the stale window (worker died) go
    back to 'queued' — unless they're out of attempts, then 'failed'."""
    db = SessionLocal()
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=STALE_PROCESSING_MINUTES)
        requeued = db.execute(
            sa_text(
                """
                UPDATE ingest_jobs
                SET status = CASE WHEN attempts >= :max_attempts THEN 'failed' ELSE 'queued' END,
                    error = CASE WHEN attempts >= :max_attempts
                                 THEN 'העיבוד נקטע יותר מדי פעמים — פנה לתמיכה.'
                                 ELSE error END,
                    stage = NULL
                WHERE status = 'processing' AND started_at < :cutoff
                """
            ),
            {"cutoff": cutoff, "max_attempts": MAX_ATTEMPTS},
        ).rowcount
        db.commit()
        return requeued or 0
    finally:
        db.close()


def _claim_next_job() -> UUID | None:
    """Atomically claim the oldest queued job. SKIP LOCKED makes this safe
    under WEB_CONCURRENCY > 1."""
    db = SessionLocal()
    try:
        row = db.execute(
            sa_text(
                """
                UPDATE ingest_jobs
                SET status = 'processing',
                    started_at = now(),
                    attempts = attempts + 1
                WHERE id = (
                    SELECT id FROM ingest_jobs
                    WHERE status = 'queued'
                    ORDER BY created_at
                    LIMIT 1
                    FOR UPDATE SKIP LOCKED
                )
                RETURNING id
                """
            )
        ).fetchone()
        db.commit()
        return row.id if row else None
    finally:
        db.close()


def _process_job(job_id: UUID) -> None:
    """Run the shared pipeline for one claimed job. Synchronous — called
    via asyncio.to_thread from the loop."""
    db = SessionLocal()
    try:
        job = db.get(IngestJob, job_id)
        if job is None:
            return

        def _set_stage(stage: str) -> None:
            # Separate short-lived session so stage updates are visible to
            # pollers immediately, not at the end of the pipeline txn.
            s = SessionLocal()
            try:
                s.execute(
                    sa_text("UPDATE ingest_jobs SET stage = :st WHERE id = :jid"),
                    {"st": stage, "jid": job_id},
                )
                s.commit()
            finally:
                s.close()

        stored = Path(job.stored_path)
        if not stored.exists():
            job.status = "failed"
            job.error = "הקובץ שהועלה לא נמצא באחסון — העלה מחדש."
            job.finished_at = datetime.now(timezone.utc)
            db.commit()
            return

        contents = stored.read_bytes()
        try:
            outcome = run_upload_pipeline(
                db,
                tenant_id=job.tenant_id,
                filename=job.filename,
                suffix=job.suffix,
                contents=contents,
                prefer_ocr=job.prefer_ocr,
                doc_type=job.doc_type,
                stage_cb=_set_stage,
            )
        except IngestRejection as e:
            db.rollback()
            job = db.get(IngestJob, job_id)
            job.status = "failed"
            job.error = e.detail
            job.stage = None
            job.finished_at = datetime.now(timezone.utc)
            db.commit()
            _cleanup_stored(stored)
            log.info("ingest_worker.job_rejected", job_id=str(job_id), detail=e.detail[:200])
            return
        except Exception as e:  # noqa: BLE001 — infra failure: keep queued state visible
            db.rollback()
            job = db.get(IngestJob, job_id)
            if job.attempts >= MAX_ATTEMPTS:
                job.status = "failed"
                job.error = f"שגיאת עיבוד: {str(e)[:300]}"
                job.finished_at = datetime.now(timezone.utc)
                _cleanup_stored(stored)
            else:
                # Back to the queue for another attempt (attempts already
                # incremented at claim time).
                job.status = "queued"
                job.stage = None
            db.commit()
            log.warning("ingest_worker.job_failed", job_id=str(job_id), error=str(e)[:300])
            return

        job = db.get(IngestJob, job_id)
        job.status = "done"
        job.stage = None
        job.document_id = outcome.document_id
        job.finished_at = datetime.now(timezone.utc)
        db.commit()
        _cleanup_stored(stored)

        if job.auto_classify:
            try:
                classify_document_by_id_bg(outcome.document_id)
            except Exception as e:  # noqa: BLE001 — classification is enrichment, not core
                log.warning(
                    "ingest_worker.classify_failed",
                    document_id=str(outcome.document_id),
                    error=str(e)[:200],
                )
        log.info(
            "ingest_worker.job_done",
            job_id=str(job_id),
            document_id=str(outcome.document_id),
            chunks=outcome.chunks_created,
        )
    finally:
        db.close()


def _cleanup_stored(path: Path) -> None:
    try:
        path.unlink()
    except OSError:
        pass


async def ingest_worker_loop() -> None:
    """Started once per uvicorn worker at app startup."""
    try:
        requeued = await asyncio.to_thread(_requeue_stale_jobs)
        if requeued:
            log.info("ingest_worker.requeued_stale", count=requeued)
    except Exception as e:  # noqa: BLE001
        log.warning("ingest_worker.stale_sweep_failed", error=str(e)[:200])

    log.info("ingest_worker.loop_started")
    while True:
        try:
            job_id = await asyncio.to_thread(_claim_next_job)
            if job_id is None:
                await asyncio.sleep(POLL_SECONDS)
                continue
            log.info("ingest_worker.job_claimed", job_id=str(job_id))
            await asyncio.to_thread(_process_job, job_id)
        except asyncio.CancelledError:
            log.info("ingest_worker.loop_cancelled")
            raise
        except Exception as e:  # noqa: BLE001 — the loop must survive anything
            log.warning("ingest_worker.loop_error", error=str(e)[:300])
            await asyncio.sleep(POLL_SECONDS)
