"""Shared dedup + idempotency helpers for the two upload paths.

Failure modes this defends against:
- User double-clicks Upload because the button doesn't show progress.
- Network hiccup causes the browser to auto-retry a fetch.
- Two tabs / two devices submit the same file within the extraction
  window (30-60s for a scanned PDF).

Three layers, checked in order:

1. **Idempotency-Key** (X-Idempotency-Key header): "same *attempt*
   replayed". Client generates one UUID per submission, retries reuse
   it. Fast: single lookup, returns the previously-stored response.

2. **Client-computed content_sha256** (X-Content-SHA256 header):
   "same *bytes*, different attempt". Lets us reject before reading
   the multipart body from the network. Saves bandwidth on retries
   of large PDFs.

3. **Server-computed content_sha256** at write time, plus a caught
   IntegrityError from the DB. Necessary because the pre-check in (2)
   has a TOCTOU race with concurrent uploads — two attempts can both
   pass the SELECT before either INSERT lands. The DB is the source
   of truth. (Requires the UNIQUE constraint on
   documents(tenant_id, content_sha256) — see migration 0018, held
   until existing duplicates are cleaned up.)
"""
from __future__ import annotations

from uuid import UUID

import structlog
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Document, UploadIdempotency

log = structlog.get_logger()

# X-Idempotency-Key values longer than this are truncated — protects the
# 128-char column and stops abusive callers from wasting index space.
MAX_IDEMPOTENCY_KEY_LEN = 128


def find_by_sha256(db: Session, *, tenant_id: UUID, content_sha256: str) -> Document | None:
    """Return the existing Document for this content, if any."""
    if not content_sha256:
        return None
    return (
        db.query(Document)
        .filter(Document.tenant_id == tenant_id)
        .filter(Document.content_sha256 == content_sha256)
        .first()
    )


def find_by_idempotency_key(
    db: Session, *, tenant_id: UUID, key: str
) -> UploadIdempotency | None:
    if not key:
        return None
    key = key.strip()[:MAX_IDEMPOTENCY_KEY_LEN]
    if not key:
        return None
    return (
        db.query(UploadIdempotency)
        .filter(UploadIdempotency.tenant_id == tenant_id)
        .filter(UploadIdempotency.key == key)
        .first()
    )


def record_idempotency(
    db: Session,
    *,
    tenant_id: UUID,
    key: str | None,
    document_id: UUID | None,
    response_json: dict,
) -> None:
    """Best-effort record. Called after a successful upload so a retry
    with the same key returns the stored response instead of re-
    processing. Silently no-ops if key is missing or duplicate insert
    races with a peer (whichever peer wrote first wins)."""
    if not key:
        return
    key = key.strip()[:MAX_IDEMPOTENCY_KEY_LEN]
    if not key:
        return
    row = UploadIdempotency(
        tenant_id=tenant_id,
        key=key,
        document_id=document_id,
        response_json=response_json,
    )
    db.add(row)
    try:
        db.flush()
    except IntegrityError:
        # Concurrent insert with same key — the peer's response is fine
        # to keep. Just roll back this attempt.
        db.rollback()
        log.info(
            "upload_dedup.idempotency_race",
            tenant_id=str(tenant_id),
            key=key[:16] + "…",
        )


def handle_sha256_race(
    db: Session, *, tenant_id: UUID, content_sha256: str
) -> Document | None:
    """Called from the IntegrityError catch on Document insert. Re-reads
    the row that won the race — that's the response we return to the
    losing caller."""
    db.rollback()
    return find_by_sha256(db, tenant_id=tenant_id, content_sha256=content_sha256)
