"""Corpus stats — inject a short "your library at a glance" block into every
answerer prompt.

Motivation: user asks "כמה פרוטוקולים יש לך" / "מה המסמך העדכני" — corpus
meta-questions. Vector retrieval returns chunks *of* protocols but none
contain the sentence "there are N protocols total", so the answerer
correctly refuses. This block makes those answers available from context
without a structured query path.

Also useful for regular answers: when the answerer knows the tenant has
zero decisions on a topic, it can refuse honestly instead of scraping
around for anything that lexically matches.

Format is short and Hebrew, structured so the LLM can extract counts,
newest-of-type, and doc_type distribution at a glance.
"""
from __future__ import annotations

from datetime import date
from uuid import UUID

import structlog
from sqlalchemy import func as sa_func
from sqlalchemy.orm import Session

from app.models import Document

log = structlog.get_logger()


# Human-readable Hebrew labels for doc_type. Order matters — this is
# also the order they appear in the "by type" line, most-important first.
_DOC_TYPE_LABEL = [
    ("bylaw", "תקנון ראשי"),
    ("sub_bylaw", "תקנון משנה"),
    ("decision", "החלטה"),
    ("minutes", "פרוטוקול"),
    ("other", "אחר"),
]
_DOC_TYPE_PLURAL = {
    "bylaw": "תקנונים ראשיים",
    "sub_bylaw": "תקנוני משנה",
    "decision": "החלטות",
    "minutes": "פרוטוקולים",
    "other": "אחרים",
}

# Doc types where "the newest one" is a meaningful, useful signal.
# Bylaws don't decay — the newest bylaw isn't more binding than an
# older one, so newest-of-type there is noise.
_NEWEST_OF_TYPE_TYPES = ("decision", "minutes")


def _pick_date(doc: Document) -> date | None:
    """Prefer effective_date (real recency signal). Fall back to
    ingested_at.date() so uncategorized docs still get ordered."""
    if doc.effective_date:
        return doc.effective_date
    if doc.ingested_at:
        return doc.ingested_at.date()
    return None


def format_corpus_stats(db: Session, *, tenant_id: UUID) -> str:
    """Return a short Hebrew block summarizing the tenant's corpus, or
    empty string if the corpus is empty. Injected into the answerer
    prompt above the retrieved sources."""
    # Counts by doc_type (NULL doc_type is counted separately as "ללא סיווג").
    rows = (
        db.query(Document.doc_type, sa_func.count(Document.id))
        .filter(Document.tenant_id == tenant_id)
        .group_by(Document.doc_type)
        .all()
    )
    if not rows:
        return ""
    counts: dict[str | None, int] = {r[0]: r[1] for r in rows}
    total = sum(counts.values())

    lines: list[str] = [f"מאגר הארגון: {total} מסמכים סה\"כ."]

    # By-type breakdown in the canonical order.
    parts: list[str] = []
    for key, _label in _DOC_TYPE_LABEL:
        n = counts.get(key, 0)
        if n:
            parts.append(f"{n} {_DOC_TYPE_PLURAL[key]}")
    if counts.get(None, 0):
        parts.append(f"{counts[None]} ללא סיווג")
    if parts:
        lines.append("לפי סוג: " + ", ".join(parts) + ".")

    # Newest overall (by effective_date, fallback ingested_at). Only include
    # if we can point to a real doc — no useful "newest" on an empty corpus.
    newest_overall = _newest_doc(db, tenant_id=tenant_id, doc_type=None)
    if newest_overall is not None:
        d = _pick_date(newest_overall)
        lines.append(
            f"המסמך העדכני ביותר: {newest_overall.filename!r}"
            + (f" ({d.isoformat()})" if d else "")
            + "."
        )

    # Newest per time-sensitive type — the two the user most often asks
    # meta-questions about.
    for t in _NEWEST_OF_TYPE_TYPES:
        if not counts.get(t):
            continue
        newest = _newest_doc(db, tenant_id=tenant_id, doc_type=t)
        if newest is None:
            continue
        d = _pick_date(newest)
        lines.append(
            f"{_DOC_TYPE_LABEL_DICT[t]} אחרון: {newest.filename!r}"
            + (f" ({d.isoformat()})" if d else "")
            + "."
        )

    return "\n".join(lines)


_DOC_TYPE_LABEL_DICT = dict(_DOC_TYPE_LABEL)


def _newest_doc(
    db: Session, *, tenant_id: UUID, doc_type: str | None
) -> Document | None:
    """Return the newest doc in the tenant, optionally filtered by doc_type.
    "Newest" = max(effective_date), NULLs sort last; ties broken by
    ingested_at desc."""
    q = db.query(Document).filter(Document.tenant_id == tenant_id)
    if doc_type is not None:
        q = q.filter(Document.doc_type == doc_type)
    return (
        q.order_by(
            Document.effective_date.desc().nulls_last(),
            Document.ingested_at.desc(),
        )
        .first()
    )
