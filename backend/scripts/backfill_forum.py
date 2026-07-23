"""Backfill Document.forum for historical docs.

The classifier learned to emit forum after 0018 shipped. Docs uploaded
before that have forum=NULL. This script fires a tiny Haiku call per
missing-forum doc, seeded with:
  - filename (has strong hints: "פרוטוקול אסיפה", "ועד הנהלה", "קלפי")
  - existing doc_type + first ~800 chars of extracted text
  - AI title/summary if present in doc_metadata

Idempotent: marker in doc_metadata skips already-processed docs. Safe
to leave in start.sh on every deploy; after the first pass it's a no-op.

    .venv/bin/python -m scripts.backfill_forum
    .venv/bin/python -m scripts.backfill_forum --tenant "אל-רום"
    .venv/bin/python -m scripts.backfill_forum --dry-run
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from functools import lru_cache

import structlog
from sqlalchemy.orm import Session

from app.config import settings
from app.db import SessionLocal
from app.models import Chunk, Document
from app.services.identity import get_tenant_row_by_name, list_tenants_as_rows

log = structlog.get_logger()

_FORUM_ENUM = [
    "assembly", "committee", "ballot", "sub_committee",
    "external_law", "external_ruling", "contract", "legal_opinion",
    "report", "notice", "procedure", "budget", "agreement_internal", "other",
]

_MARKER = "forum_backfilled_v1"


_SYSTEM = f"""אתה מסווג מסמכים של קיבוץ. תפקידך יחיד: לזהות את ה-forum של המסמך — הגוף שבו הופק.

ערכים תקינים (חובה להחזיר אחד מהם בדיוק):
- assembly: תקנונים, תקנוני משנה, פרוטוקולי אסיפה כללית
- committee: פרוטוקולי ועד הנהלה
- ballot: החלטות קלפי, תוצאות הצבעה בקלפי
- sub_committee: ועדות משנה (ועדת ביקורת/שיוך/חינוך וכו')
- external_law: חוקים, פקודת האגודות, תקנות רשם
- external_ruling: פסיקות בית משפט, החלטות רשם
- contract: הסכמים עם צדדים שלישיים
- legal_opinion: חוות דעת משפטית
- report: דוחות מבקר/כספיים/סקירות
- notice: חוזרים והודעות פנימיות
- procedure: נהלים פנימיים
- budget: תקציב
- agreement_internal: הסכם בין הקיבוץ לחבר (שנת חופש, קליטה, פרישה) או בין חברים
- other: אין התאמה טובה

החזר JSON תקין בפורמט: {{"forum": "<value>"}}. ללא הסברים, ללא markdown."""


@lru_cache(maxsize=1)
def _client():
    from anthropic import Anthropic

    return Anthropic(api_key=settings.anthropic_api_key)


def _sample_text(db: Session, doc: Document, max_chars: int = 800) -> str:
    """First N characters of the doc, joined from earliest chunks."""
    rows = (
        db.query(Chunk.text)
        .filter(Chunk.document_id == doc.id)
        .order_by(Chunk.position)
        .limit(4)
        .all()
    )
    text = "\n\n".join(r[0] for r in rows if r[0])
    return text[:max_chars]


def _classify_forum(db: Session, doc: Document) -> str | None:
    meta = doc.doc_metadata or {}
    hint_parts = [f"filename: {doc.filename}"]
    if doc.doc_type:
        hint_parts.append(f"doc_type: {doc.doc_type}")
    if meta.get("ai_title"):
        hint_parts.append(f"title: {meta['ai_title']}")
    if meta.get("summary"):
        hint_parts.append(f"summary: {meta['summary']}")
    sample = _sample_text(db, doc)
    if sample:
        hint_parts.append(f"\n---\n{sample}")
    user_message = "\n".join(hint_parts) + "\n\nהחזר JSON."

    try:
        resp = _client().messages.create(
            model=settings.claude_extract_model,
            max_tokens=100,
            system=_SYSTEM,
            messages=[{"role": "user", "content": user_message}],
        )
        raw = resp.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.strip("`").lstrip("json").strip()
        data = json.loads(raw)
        forum = str(data.get("forum") or "").strip()
        if forum not in _FORUM_ENUM:
            log.warning("backfill_forum.invalid_value", forum=forum, doc=doc.filename)
            return None
        return forum
    except Exception as e:  # noqa: BLE001
        log.warning("backfill_forum.claude_failed", err=str(e), doc=doc.filename)
        return None


def run_for_tenant(db: Session, tenant_id, *, dry_run: bool) -> dict:
    all_docs = (
        db.query(Document)
        .filter(Document.tenant_id == tenant_id)
        .filter(Document.forum.is_(None))
        .all()
    )
    todo = [d for d in all_docs if not (d.doc_metadata or {}).get(_MARKER)]
    if not todo:
        return {"scanned": 0, "already_marked": len(all_docs) - len(todo)}

    counter: Counter = Counter()
    for d in todo:
        forum = _classify_forum(db, d)
        if forum:
            if not dry_run:
                d.forum = forum
                d.doc_metadata = {**(d.doc_metadata or {}), _MARKER: True}
            counter[forum] += 1
        else:
            counter["_failed"] += 1
    if not dry_run:
        db.commit()
    return {
        "scanned": len(todo),
        "assigned": dict(counter),
        "dry_run": dry_run,
    }


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--tenant")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    db = SessionLocal()
    try:
        if args.tenant:
            t = get_tenant_row_by_name(args.tenant)
            tenants = [t] if t else []
        else:
            tenants = list_tenants_as_rows()
        for t in tenants:
            res = run_for_tenant(db, t.id, dry_run=args.dry_run)
            print(f"{t.name}: {res}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
