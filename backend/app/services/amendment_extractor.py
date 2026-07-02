"""Amendment extractor — turns free-text amendment clauses into structured edits.

Runs once per document, right after ingest+classify, in a background task.
Given the full text of one doc plus the list of prior docs in the tenant,
Claude decides whether this doc amends any of them and emits per-section
edits. Rows land in the ``amendments`` table.

Only edits whose confidence clears ``AUTO_APPLY_CONFIDENCE`` and whose
target chunk can be located unambiguously flip ``chunks.superseded_by_amendment_id``.
Everything else lands with ``needs_review=true`` for the reviewer UI to
approve — we would rather leak a superseded chunk into retrieval than
silently hide the *correct* clause because the extractor guessed wrong.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Amendment, Chunk, Document

log = structlog.get_logger()

# Below this the edit is written but not auto-applied to chunks.
AUTO_APPLY_CONFIDENCE = 0.75

# How many chars of the amending doc to send to the LLM. The extractor works
# on legal-ish text and 20k covers the vast majority of sub-bylaws + resolutions.
# Truncation is logged so a reviewer can bump the limit for an unusually long doc.
MAX_DOC_CHARS = 20_000

# How many prior docs to list in the extractor context. In practice the target
# of an amendment is almost always "the main bylaws" or "a specific sub-bylaw
# in the same folder", so we list every doc — Claude picks by title.
PRIOR_DOC_LIMIT = 40


_ALLOWED_ACTIONS = {"replace", "add_after", "add_before", "delete", "clarify"}

# A well-formed section reference is a number, optionally with dot-separated
# numeric or Hebrew-letter sub-parts: "44", "12.3", "45.ב", "12.3.א".
# The extractor tends to hallucinate free-text section refs like "מבוא.ה",
# "כללי", or the document title itself — these have high stated confidence
# but never match a real chunk. We accept them (so the reviewer can see the
# evidence span) but force ``needs_review=true`` so they never auto-apply.
_SECTION_REF_RE = re.compile(r"^\d+(\.(\d+|[א-ת]))*$")


def looks_like_real_section_ref(s: str) -> bool:
    return bool(_SECTION_REF_RE.match(s.strip()))


@dataclass
class ExtractedEdit:
    target_doc_id: UUID
    target_section: str
    action: str
    old_text: str | None
    new_text: str | None
    effective_date: date | None
    rationale: str | None
    confidence: float
    evidence_span: str | None
    needs_review: bool


@lru_cache(maxsize=1)
def _claude_client():
    from anthropic import Anthropic

    return Anthropic(api_key=settings.anthropic_api_key)


SYSTEM_PROMPT = """אתה מחלץ את מבנה התיקונים ממסמכי ממשל של קיבוץ (תקנון ראשי, תקנוני משנה, תיקונים, החלטות, פרוטוקולים) בעברית.

תקבל:
- טקסט מלא של מסמך אחד
- רשימת מסמכים קודמים בקיבוץ עם id, כותרת, סוג ותאריך תוקף

המשימה: להחליט האם המסמך הזה מתקן מסמך קודם כלשהו, ואם כן — לפלוט רישום מובנה אחד עבור כל שינוי.

כללים:
1. "תיקון" הוא כל שינוי לסעיף ספציפי במסמך קודם: החלפת נוסח, הוספת סעיף חדש, מחיקת סעיף, או הבהרה.
2. תקנוני משנה (תקנון משנה) יכולים לתקן את התקנון הראשי. התייחס אליהם כמסמך תיקון לצורך החילוץ.
3. target_section חייב להיות מספר הסעיף הקנוני **כפי שהוא במסמך היעד** (למשל "44", "12.3", "12.3.א"). אם התיקון מזכיר סעיף רק לפי תיאור מילולי — נסה להסיק את המספר מההקשר, והנמך את confidence בהתאם.
4. effective_date נלקח מהמסמך המתקן. אם כתוב "מיד עם קבלתו" — השתמש בתאריך קבלת המסמך אם הוא ידוע; אחרת null עם needs_review=true.
5. פעולה:
   - replace — כותב מחדש את הסעיף
   - clarify — מוסיף פרשנות בלי לשנות את הנוסח האופרטיבי
   - add_after / add_before — מוסיף סעיף חדש לפני/אחרי סעיף קיים
   - delete — מוחק את הסעיף
6. old_text — ציטוט מילולי מהמסמך המתקן כאשר הוא מצטט את הנוסח המקורי, אחרת null.
7. new_text — הנוסח האופרטיבי החדש, ציטוט מילולי מהמסמך המתקן.
8. evidence_span — הציטוט מהמסמך שממנו נחלץ הרישום (משפט אחד או שניים). זה מאפשר לסוקר אנושי לאמת.
9. confidence: 1.0 = מספר הסעיף והפעולה מפורשים במסמך. 0.7 = מספר סעיף הוסק, פעולה מפורשת. 0.4 = שניהם הוסקו.
   כל דבר מתחת ל-0.75 חייב needs_review=true. אם effective_date לא ידוע — needs_review=true.
10. אל תמציא סעיפים. עדיף להוציא פחות עריכות בביטחון גבוה מיותר עריכות בביטחון נמוך.

הפעל את הכלי extract_amendments עם JSON תואם לסכימה. אם המסמך אינו מתקן אף מסמך קודם — is_amendment=false ו-edits=[].
"""


_EXTRACT_TOOL = {
    "name": "extract_amendments",
    "description": "Emit the structured amendment graph for a governance document.",
    "input_schema": {
        "type": "object",
        "properties": {
            "is_amendment": {"type": "boolean"},
            "parent_doc_id": {
                "type": ["string", "null"],
                "description": (
                    "The single doc this document primarily amends — the target of "
                    "most edits. Null if the doc is not an amendment or amends "
                    "several docs equally."
                ),
            },
            "edits": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "target_doc_id": {"type": "string"},
                        "target_section": {"type": "string"},
                        "action": {
                            "type": "string",
                            "enum": sorted(_ALLOWED_ACTIONS),
                        },
                        "old_text": {"type": ["string", "null"]},
                        "new_text": {"type": ["string", "null"]},
                        "effective_date": {
                            "type": ["string", "null"],
                            "description": "YYYY-MM-DD or null",
                        },
                        "rationale": {"type": ["string", "null"]},
                        "confidence": {"type": "number"},
                        "evidence_span": {"type": ["string", "null"]},
                        "needs_review": {"type": "boolean"},
                    },
                    "required": [
                        "target_doc_id",
                        "target_section",
                        "action",
                        "confidence",
                        "needs_review",
                    ],
                },
            },
        },
        "required": ["is_amendment", "edits"],
    },
}


def _prior_docs_block(prior: list[Document]) -> str:
    lines = []
    for d in prior[:PRIOR_DOC_LIMIT]:
        eff = d.effective_date.isoformat() if d.effective_date else "unknown"
        lines.append(f"- id={d.id} | סוג={d.doc_type or 'unknown'} | תוקף={eff} | כותרת={d.filename}")
    return "\n".join(lines) or "(אין מסמכים קודמים במאגר)"


def _doc_full_text(db: Session, doc: Document) -> str:
    chunks = (
        db.query(Chunk)
        .filter(Chunk.document_id == doc.id)
        .order_by(Chunk.position)
        .all()
    )
    joined = "\n\n".join(c.text for c in chunks if c.text)
    if len(joined) > MAX_DOC_CHARS:
        log.info("amendment_extractor.doc_truncated", doc_id=str(doc.id), full=len(joined), kept=MAX_DOC_CHARS)
        return joined[:MAX_DOC_CHARS]
    return joined


def _parse_edit(raw: dict, tenant_doc_ids: set[UUID]) -> ExtractedEdit | None:
    try:
        target_doc_id = UUID(str(raw["target_doc_id"]))
    except (KeyError, ValueError, TypeError):
        return None
    if target_doc_id not in tenant_doc_ids:
        # Hallucinated UUID — Claude invented a target that isn't in the tenant.
        return None
    action = str(raw.get("action") or "").strip()
    if action not in _ALLOWED_ACTIONS:
        return None
    target_section = str(raw.get("target_section") or "").strip()
    if not target_section:
        return None

    confidence = float(raw.get("confidence") or 0.0)
    eff_raw = raw.get("effective_date")
    eff: date | None = None
    if isinstance(eff_raw, str) and eff_raw:
        try:
            eff = date.fromisoformat(eff_raw)
        except ValueError:
            eff = None

    needs_review = (
        bool(raw.get("needs_review"))
        or confidence < AUTO_APPLY_CONFIDENCE
        or eff is None
        or not looks_like_real_section_ref(target_section)
    )

    return ExtractedEdit(
        target_doc_id=target_doc_id,
        target_section=target_section,
        action=action,
        old_text=(raw.get("old_text") or None),
        new_text=(raw.get("new_text") or None),
        effective_date=eff,
        rationale=(raw.get("rationale") or None),
        confidence=confidence,
        evidence_span=(raw.get("evidence_span") or None),
        needs_review=needs_review,
    )


def break_circular_parents(db: Session, tenant_id: UUID) -> int:
    """Repair bidirectional parent_doc_id edges within a tenant.

    Two versions of the same document can look like mutual amendments to the
    extractor. When A.parent=B and B.parent=A, the older doc cannot have been
    amended by the newer — its edge is spurious. We clear it, leaving the
    newer-amends-older direction intact. If effective_dates tie or are both
    null, we break by ingested_at as a fallback so the corpus doesn't stay
    in an inconsistent state.

    Returns the number of edges cleared.
    """
    docs = (
        db.query(Document)
        .filter(Document.tenant_id == tenant_id, Document.parent_doc_id.isnot(None))
        .all()
    )
    by_id = {d.id: d for d in docs}
    cleared = 0
    seen: set[frozenset[UUID]] = set()
    for d in docs:
        p = by_id.get(d.parent_doc_id) if d.parent_doc_id else None
        if p is None:
            continue
        if p.parent_doc_id != d.id:
            continue  # not circular
        pair = frozenset({d.id, p.id})
        if pair in seen:
            continue
        seen.add(pair)

        # Pick which one to clear. Older doc's edge is the wrong one.
        def _key(doc: Document):
            # None sorts last so a doc with no effective_date is treated as
            # "younger" (less likely to be the amender). Falls back to
            # ingested_at when dates are missing on both sides.
            return (doc.effective_date or doc.ingested_at.date(),)

        older, newer = sorted([d, p], key=_key)
        older.parent_doc_id = None
        cleared += 1
        log.info(
            "amendment_extractor.broke_circular_parent",
            older_doc=str(older.id),
            newer_doc=str(newer.id),
        )
    if cleared:
        db.commit()
    return cleared


def _apply_supersession(db: Session, amendment: Amendment) -> int:
    """Flip ``superseded_by_amendment_id`` on chunks whose (doc, section_ref)
    matches this amendment. Only runs for auto-applied edits; needs_review
    edits are inert until a reviewer approves them.

    Returns the number of chunks flipped. We match on exact section_ref for
    now — if the section-parser didn't populate section_ref on the target
    chunks, this quietly no-ops and the amendment still shows in retrieval
    via the chain expansion at query time.
    """
    if amendment.action not in {"replace", "delete"}:
        # add_after / add_before don't invalidate an existing chunk;
        # clarify is interpretive and coexists with the original.
        return 0

    chunks = (
        db.query(Chunk)
        .filter(
            Chunk.document_id == amendment.target_doc_id,
            Chunk.section_ref == amendment.target_section,
            Chunk.superseded_by_amendment_id.is_(None),
        )
        .all()
    )
    for c in chunks:
        c.superseded_by_amendment_id = amendment.id
    return len(chunks)


def extract_amendments(db: Session, doc: Document) -> dict:
    """Run the extractor for one document. Idempotent: skips if amendments
    already exist for this doc.

    Returns a small dict for logging: {status, edits_written, chunks_superseded, needs_review}.
    """
    existing = db.execute(
        select(Amendment.id).where(Amendment.amendment_doc_id == doc.id).limit(1)
    ).first()
    if existing:
        return {"status": "skipped", "reason": "already_extracted"}

    body = _doc_full_text(db, doc)
    if not body.strip():
        return {"status": "skipped", "reason": "no_text"}

    prior = (
        db.query(Document)
        .filter(Document.tenant_id == doc.tenant_id, Document.id != doc.id)
        .order_by(Document.ingested_at)
        .all()
    )
    if not prior:
        return {"status": "skipped", "reason": "no_prior_docs"}

    tenant_doc_ids = {d.id for d in prior}
    prior_block = _prior_docs_block(prior)

    user_message = (
        f"מסמך נוכחי:\nid={doc.id}\nכותרת={doc.filename}\n"
        f"סוג={doc.doc_type or 'unknown'}\n"
        f"תאריך תוקף={doc.effective_date.isoformat() if doc.effective_date else 'unknown'}\n\n"
        f"מסמכים קודמים במאגר (מקורות אפשריים לתיקון):\n{prior_block}\n\n"
        f"טקסט המסמך הנוכחי:\n\n{body}\n\n"
        f"הפעל את הכלי extract_amendments."
    )

    try:
        client = _claude_client()
        resp = client.messages.create(
            model=settings.claude_extract_model,
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            tools=[_EXTRACT_TOOL],
            tool_choice={"type": "tool", "name": "extract_amendments"},
            messages=[{"role": "user", "content": user_message}],
        )
    except Exception as e:
        log.error("amendment_extractor.llm_failed", doc_id=str(doc.id), err=str(e)[:300])
        return {"status": "error", "error": str(e)[:200]}

    tool_input: dict | None = None
    for block in resp.content:
        if getattr(block, "type", None) == "tool_use" and getattr(block, "name", "") == "extract_amendments":
            tool_input = block.input  # type: ignore[attr-defined]
            break
    if not isinstance(tool_input, dict):
        return {"status": "error", "error": "no_tool_use_in_response"}

    if not tool_input.get("is_amendment"):
        return {"status": "ok", "edits_written": 0, "chunks_superseded": 0, "needs_review": 0}

    parent_raw = tool_input.get("parent_doc_id")
    if isinstance(parent_raw, str):
        try:
            parent_id = UUID(parent_raw)
            if parent_id in tenant_doc_ids:
                doc.parent_doc_id = parent_id
        except ValueError:
            pass

    edits_written = 0
    chunks_superseded = 0
    review_count = 0

    for raw in tool_input.get("edits") or []:
        if not isinstance(raw, dict):
            continue
        parsed = _parse_edit(raw, tenant_doc_ids)
        if parsed is None:
            continue
        amendment = Amendment(
            tenant_id=doc.tenant_id,
            amendment_doc_id=doc.id,
            target_doc_id=parsed.target_doc_id,
            target_section=parsed.target_section,
            action=parsed.action,
            old_text=parsed.old_text,
            new_text=parsed.new_text,
            effective_date=parsed.effective_date,
            rationale=parsed.rationale,
            extractor_confidence=parsed.confidence,
            needs_review=parsed.needs_review,
            evidence_span=parsed.evidence_span,
            extractor_model=settings.claude_extract_model,
        )
        db.add(amendment)
        db.flush()
        edits_written += 1
        if parsed.needs_review:
            review_count += 1
        else:
            chunks_superseded += _apply_supersession(db, amendment)

    db.commit()

    # Two versions of the same doc can look like mutual amendments; run the
    # repair after each extraction so the graph never stays circular.
    circular_broken = break_circular_parents(db, doc.tenant_id)

    return {
        "status": "ok",
        "edits_written": edits_written,
        "chunks_superseded": chunks_superseded,
        "needs_review": review_count,
        "circular_broken": circular_broken,
    }


def extract_amendments_by_id_bg(document_id: UUID) -> None:
    """Background-task entrypoint. Opens its own DB session, mirrors the
    shape of ``classify_document_by_id_bg`` in ``routes/documents.py``.
    Errors are swallowed and logged — there is no caller to surface them to.
    """
    from app.db import SessionLocal

    db: Session = SessionLocal()
    try:
        doc = db.get(Document, document_id)
        if doc is None:
            log.warning("amendment_extractor.bg.doc_missing", document_id=str(document_id))
            return
        result = extract_amendments(db, doc)
        log.info("amendment_extractor.bg.done", document_id=str(document_id), **result)
    except Exception as e:
        log.error("amendment_extractor.bg.crashed", document_id=str(document_id), err=str(e))
    finally:
        db.close()
