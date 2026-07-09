"""Weekly digest cron — one email per super-admin, per week.

Scope for v1: **lexicon activity only** — the additions/approvals/rejections
that happened in the past 7 days per tenant. Skips tenants with zero activity
so quiet weeks produce zero emails.

Wired via render.yaml as a cron service running at 04:00 UTC every Sunday
(= 07:00 Israel, before the work week starts). Safe to run manually:

    cd backend
    .venv/bin/python -m scripts.send_weekly_digests
"""
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from uuid import UUID

import structlog
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import Lexicon, Tenant, User
from app.services.mail import LexiconEntrySnapshot, send_lexicon_digest

log = structlog.get_logger()


def _snapshot(row: Lexicon) -> LexiconEntrySnapshot:
    return LexiconEntrySnapshot(
        term=row.term,
        expansion=row.expansion,
        confidence=row.confidence,
        status=row.status,
        source=row.source,
        updated_at_iso=row.updated_at.isoformat() if row.updated_at else "",
    )


def _collect_activity(db: Session, cutoff: datetime) -> dict[UUID, dict]:
    """Return {tenant_id: {"pending": [...], "active": [...], "rejected": [...]}}
    for every tenant with lexicon activity since ``cutoff``. Empty dict if the
    week was quiet across the board."""
    rows = (
        db.query(Lexicon)
        .filter(Lexicon.updated_at >= cutoff)
        .order_by(Lexicon.updated_at.desc())
        .all()
    )
    if not rows:
        return {}

    activity: dict[UUID, dict[str, list[LexiconEntrySnapshot]]] = defaultdict(
        lambda: {"pending": [], "active": [], "rejected": []}
    )
    for r in rows:
        snap = _snapshot(r)
        bucket = (
            "pending"
            if r.status == "pending"
            else "active"
            if r.status == "active"
            else "rejected"
        )
        activity[r.tenant_id][bucket].append(snap)
    return activity


def main(days: int = 7) -> None:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    db: Session = SessionLocal()
    try:
        super_admins = (
            db.query(User).filter(User.is_super_admin.is_(True)).all()
        )
        if not super_admins:
            log.info("digest.no_super_admins")
            return

        activity = _collect_activity(db, cutoff)
        if not activity:
            log.info("digest.no_activity", days=days)
            return

        tenant_names = {
            t.id: t.name for t in db.query(Tenant).all() if t.id in activity
        }
        # Build the sections list once — same content goes to every super-admin.
        sections = []
        for tid, buckets in activity.items():
            name = tenant_names.get(tid, str(tid))
            sections.append(
                (name, buckets["pending"], buckets["active"], buckets["rejected"])
            )
        # Deterministic order: most items first, alphabetical tie-break.
        sections.sort(
            key=lambda s: (-sum(len(x) for x in s[1:]), s[0])
        )

        sent = 0
        for admin in super_admins:
            log.info(
                "digest.send",
                to=admin.email,
                tenants=len(sections),
                total=sum(sum(len(x) for x in s[1:]) for s in sections),
            )
            send_lexicon_digest(
                to_email=admin.email,
                admin_display_name=admin.display_name,
                tenant_sections=sections,
            )
            sent += 1
        log.info("digest.done", sent=sent)
    finally:
        db.close()


if __name__ == "__main__":
    main()
