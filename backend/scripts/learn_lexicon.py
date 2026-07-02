"""Nightly lexicon learner — turn chat refinement pairs into proposed lexicon
entries.

Hypothesis: when a user reformulates an earlier turn (clarification +
follow-up, OR thumbs-down → re-asked with new vocabulary), the *new
vocabulary* the user added is, on average, the bylaw-side translation of
their original lay phrasing. Capturing those translations is the same task
as building a domain lexicon — except the user labels it for us by simply
having a conversation.

What this script does
=====================

1. Find "refinement pairs" — for each conversation, look at consecutive
   user turns (turn_index N and N+1) where N didn't go well and N+1 did:
     - turn N: confidence='clarifying' (assistant asked back), OR
               feedback='negative', OR retrieval returned 'refused'.
     - turn N+1: confidence='confident', AND feedback != 'negative'.
2. Diff the pair to extract the *signal*:
     - new terms in turn N+1 not present in turn N (lay → bylaw translation).
     - new doc filenames retrieved on turn N+1 not on turn N (target docs).
3. Ask Claude Haiku what lexicon mapping would have closed the gap.
4. Insert candidates as ``Lexicon`` rows with source='learned',
   status='pending'. They stay out of retrieval until a reviewer approves.
   A reviewer page in the existing /api/reviewer/lexicon endpoint surfaces
   them with their evidence so the call is one-click.

This is the v0.3 flywheel: the chat UX both serves users and trains itself.

Usage:
    python -m scripts.learn_lexicon
    python -m scripts.learn_lexicon --tenant "אל-רום"
    python -m scripts.learn_lexicon --since 2026-06-01 --max-pairs 50
"""
import argparse
import json
from collections.abc import Iterable
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from uuid import UUID

import structlog
from sqlalchemy.orm import Session, joinedload

from app.config import settings
from app.db import SessionLocal
from app.models import Chunk, Conversation, Document, Lexicon, Query, Tenant

log = structlog.get_logger()


# ─── Pair detection ────────────────────────────────────────────────────


def _is_failed(q: Query) -> bool:
    """A 'failed' turn is one the user wouldn't accept as the final answer."""
    if q.confidence == "clarifying":
        return True
    if q.confidence == "refused":
        return True
    if q.feedback == "negative":
        return True
    return False


def _is_succeeded(q: Query) -> bool:
    """A 'succeeded' turn is one the user accepted (or didn't reject)."""
    if q.feedback == "negative":
        return False
    if q.confidence == "confident":
        return True
    # Tolerate 'uncertain' if the user didn't 👎 — usually the answer is
    # acceptable enough that the conversation didn't continue.
    return q.confidence in {"confident", "uncertain"}


def find_refinement_pairs(
    db: Session, *, tenant_id: UUID, since: datetime, max_pairs: int
) -> list[tuple[Query, Query]]:
    convs = (
        db.query(Conversation)
        .filter(Conversation.tenant_id == tenant_id)
        .filter(Conversation.updated_at >= since)
        .all()
    )
    pairs: list[tuple[Query, Query]] = []
    for c in convs:
        turns = (
            db.query(Query)
            .filter(Query.conversation_id == c.id)
            .order_by(Query.turn_index.asc().nulls_last(), Query.created_at.asc())
            .all()
        )
        # Walk consecutive (N, N+1) pairs.
        for a, b in zip(turns, turns[1:]):
            if _is_failed(a) and _is_succeeded(b):
                pairs.append((a, b))
                if len(pairs) >= max_pairs:
                    return pairs
    return pairs


# ─── Evidence assembly ─────────────────────────────────────────────────


def _retrieved_filenames(db: Session, q: Query) -> list[str]:
    ids = q.source_chunk_ids or []
    if not ids:
        return []
    rows = (
        db.query(Document.filename)
        .join(Chunk, Chunk.document_id == Document.id)
        .filter(Chunk.id.in_(ids))
        .distinct()
        .all()
    )
    return sorted({r[0] for r in rows if r[0]})


# ─── Claude call ───────────────────────────────────────────────────────


@lru_cache(maxsize=1)
def _claude_client():
    from anthropic import Anthropic

    return Anthropic(api_key=settings.anthropic_api_key)


_LEARN_TOOL = {
    "name": "propose_mappings",
    "description": (
        "Given a chat refinement pair, propose lexicon entries that would "
        "have closed the gap between the user's original phrasing and the "
        "refined phrasing — so the next user asking similarly gets the right "
        "docs without needing to know the formal terminology."
    ),
    "input_schema": {
        "type": "object",
        "required": ["mappings"],
        "properties": {
            "mappings": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["term", "expansion", "confidence", "why"],
                    "properties": {
                        "term": {
                            "type": "string",
                            "description": (
                                "The lay-phrasing word/phrase from the "
                                "ORIGINAL turn that should trigger expansion."
                            ),
                        },
                        "expansion": {
                            "type": "string",
                            "description": (
                                "The bylaw-side vocabulary (one or several "
                                "comma-separated terms) that should be added "
                                "to the embedding query when `term` appears."
                            ),
                        },
                        "confidence": {
                            "type": "number",
                            "description": (
                                "0.0 to 1.0. >=0.85 means auto-activatable "
                                "(but we still default to pending). <0.5 is "
                                "weak evidence — caller will likely drop it."
                            ),
                        },
                        "why": {
                            "type": "string",
                            "description": "One short Hebrew sentence explaining the mapping.",
                        },
                    },
                },
            }
        },
    },
}


_LEARN_SYSTEM = """אתה חוקר טרמינולוגיה של תקנוני קיבוצים. תקבל זוג תורים מתוך שיחה: התור הראשון לא הוביל לתשובה מספקת, השני כן. תפקידך לזהות אילו מונחים בתור השני שלא היו בתור הראשון הם תרגום של "ניסוח עממי" ל"ניסוח תקנוני" — כלומר, מילון ערכים שכאשר משתמש אחר ישאל בניסוח של תור 1 בעתיד, הרחבת ההטמעה לפי המילון תאחזר את המסמכים הנכונים.

כללים:
- אל תציע מונחים שמופיעים זהים בשני התורים — אלה לא תרגום.
- אל תציע מונחים גנריים (פעלים יומיומיים, מילות שאלה). רק טרמינולוגיה מקצועית או נושאית.
- "term" צריך להיות הניסוח שכנראה יופיע אצל המשתמש העתידי (תור 1), ו-"expansion" הניסוח המקצועי (תור 2 / מסמכים).
- אם אין מיפוי טוב — החזר מערך ריק. עדיף ערך 0 על פני רעש."""


def _ask_claude(*, failed: Query, succeeded: Query, new_docs: list[str]) -> list[dict]:
    client = _claude_client()
    user_message = (
        f"תור 1 (שאלה ראשונה — לא הספיקה):\n{failed.question}\n\n"
        f"תור 2 (שאלה שעבדה):\n{succeeded.question}\n\n"
        f"מסמכים שעלו לראשונה בתור 2 (היעדים שצריך לאחזר):\n"
        + ("\n".join(f"- {d}" for d in new_docs) if new_docs else "(אין)")
        + "\n\n"
        "הצע מיפויים. מותר להחזיר רשימה ריקה."
    )
    resp = client.messages.create(
        model=settings.claude_extract_model,
        max_tokens=800,
        system=_LEARN_SYSTEM,
        tools=[_LEARN_TOOL],
        tool_choice={"type": "tool", "name": "propose_mappings"},
        messages=[{"role": "user", "content": user_message}],
    )
    for block in resp.content:
        if getattr(block, "type", None) == "tool_use" and getattr(block, "name", "") == "propose_mappings":
            inp = block.input  # type: ignore[attr-defined]
            if isinstance(inp, dict):
                m = inp.get("mappings") or []
                if isinstance(m, list):
                    return [x for x in m if isinstance(x, dict)]
    return []


# ─── Insert ─────────────────────────────────────────────────────────────


def _existing_terms(db: Session, tenant_id: UUID) -> set[str]:
    return {
        (l.term or "").strip().lower()
        for l in db.query(Lexicon).filter(Lexicon.tenant_id == tenant_id).all()
    }


def _insert_mappings(
    db: Session,
    *,
    tenant_id: UUID,
    failed: Query,
    succeeded: Query,
    mappings: list[dict],
    min_confidence: float,
) -> int:
    existing = _existing_terms(db, tenant_id)
    inserted = 0
    for m in mappings:
        term = (m.get("term") or "").strip()
        expansion = (m.get("expansion") or "").strip()
        conf = float(m.get("confidence") or 0.0)
        why = (m.get("why") or "").strip()
        if not term or not expansion:
            continue
        if conf < min_confidence:
            continue
        if term.lower() in existing:
            # Don't overwrite a human-curated or already-accepted entry.
            continue
        evidence = {
            "from_query_id": str(failed.id),
            "to_query_id": str(succeeded.id),
            "from_question": failed.question,
            "to_question": succeeded.question,
            "why": why,
        }
        entry = Lexicon(
            tenant_id=tenant_id,
            term=term,
            expansion=expansion,
            notes=f"learned: {why}" if why else None,
            source="learned",
            status="pending",
            confidence=conf,
            evidence=evidence,
            learned_from_query_id=succeeded.id,
        )
        db.add(entry)
        existing.add(term.lower())  # prevent duplicates within this batch
        inserted += 1
    return inserted


# ─── Driver ─────────────────────────────────────────────────────────────


def run_for_tenant(
    db: Session, tenant: Tenant, *, since: datetime, max_pairs: int, min_confidence: float
) -> dict:
    pairs = find_refinement_pairs(
        db, tenant_id=tenant.id, since=since, max_pairs=max_pairs
    )
    log.info("learn_lexicon.pairs", tenant=tenant.name, count=len(pairs))
    inserted_total = 0
    for failed, succeeded in pairs:
        failed_docs = set(_retrieved_filenames(db, failed))
        succ_docs = _retrieved_filenames(db, succeeded)
        new_docs = [d for d in succ_docs if d not in failed_docs]
        try:
            mappings = _ask_claude(failed=failed, succeeded=succeeded, new_docs=new_docs)
        except Exception as e:
            log.warning("learn_lexicon.claude_failed", err=str(e))
            continue
        if not mappings:
            continue
        n = _insert_mappings(
            db,
            tenant_id=tenant.id,
            failed=failed,
            succeeded=succeeded,
            mappings=mappings,
            min_confidence=min_confidence,
        )
        if n:
            db.commit()
            inserted_total += n
            log.info(
                "learn_lexicon.inserted",
                tenant=tenant.name,
                pair=(str(failed.id), str(succeeded.id)),
                inserted=n,
            )
    return {"pairs": len(pairs), "inserted": inserted_total}


_RELATIVE_RE = __import__("re").compile(r"^\s*(\d+)\s*([dhm])\s*$")


def _parse_since(raw: str | None) -> datetime:
    """Accept ISO date, relative duration (``7d``/``24h``/``90m``), or None
    (defaults to 7 days back). Returns a tz-aware UTC datetime."""
    if not raw:
        return datetime.now(timezone.utc) - timedelta(days=7)
    m = _RELATIVE_RE.match(raw)
    if m:
        n = int(m.group(1))
        unit = m.group(2)
        delta = {"d": timedelta(days=n), "h": timedelta(hours=n), "m": timedelta(minutes=n)}[unit]
        return datetime.now(timezone.utc) - delta
    # Fall back to ISO. Treat naive dates as UTC midnight.
    parsed = datetime.fromisoformat(raw)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--tenant", help="Limit to a single tenant by name.")
    p.add_argument(
        "--since",
        help=(
            "Lower bound for conversations.updated_at. Accepts either an ISO "
            "date (YYYY-MM-DD) or a relative duration like '7d' / '24h' / "
            "'90m'. Defaults to 7d. The relative form is what the nightly cron "
            "uses so the job is self-contained."
        ),
    )
    p.add_argument("--max-pairs", type=int, default=200)
    p.add_argument(
        "--min-confidence",
        type=float,
        default=0.5,
        help="Drop proposed mappings with confidence < this value.",
    )
    args = p.parse_args()

    since = _parse_since(args.since)

    db = SessionLocal()
    try:
        q = db.query(Tenant)
        if args.tenant:
            q = q.filter(Tenant.name == args.tenant)
        tenants = q.all()
        if not tenants:
            print("No tenants matched.")
            return
        summary: dict[str, dict] = {}
        for t in tenants:
            res = run_for_tenant(
                db,
                t,
                since=since,
                max_pairs=args.max_pairs,
                min_confidence=args.min_confidence,
            )
            summary[t.name] = res
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    finally:
        db.close()


if __name__ == "__main__":
    main()
