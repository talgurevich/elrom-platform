"""Per-tenant lexicon — domain terms that a generic AI doesn't know about.

Example: "השינוי" means "the transition from kibbutz shitufi to mitchadesh, see
the 2008 שינוי agreement and the related bylaws." NotebookLM doesn't know that.
We tell Claude explicitly when those terms appear in a query.

Used at query time: scan question for known terms, collect their expansions,
prepend them to the LLM context as a "domain note" block.

Matching moved to `lexicon_matcher.py` (word-boundary regex over
surface_forms). This module now stays thin: query the DB, delegate the
match, format the block, record the events.
"""
from uuid import UUID

import structlog
from sqlalchemy.orm import Session

from app.models import Lexicon
from app.services import lexicon_matcher

log = structlog.get_logger()


def find_relevant_terms(
    db: Session,
    *,
    tenant_id: UUID,
    question: str,
    query_id: UUID | None = None,
    record_events: bool = True,
) -> list[Lexicon]:
    """Return active lexicon entries whose surface_forms appear in `question`.

    Delegates matching to `lexicon_matcher.match_in_text` so retrieval and
    highlighting share one implementation. When `record_events=True`, logs
    a match event per hit so the reviewer stats panel can show usage.
    """
    entries = lexicon_matcher.load_active_entries(db, tenant_id=tenant_id)
    matches = lexicon_matcher.match_in_text(entries, question)
    if not matches:
        return []
    matched_ids = {m.lexicon_id for m in matches}
    hits = [e for e in entries if e.id in matched_ids]
    if record_events:
        lexicon_matcher.record_match_events(
            db,
            tenant_id=tenant_id,
            matches=matches,
            context="query",
            query_id=query_id,
        )
    log.info(
        "lexicon.hit",
        count=len(hits),
        terms=[e.term for e in hits],
    )
    return hits


def format_lexicon_block(entries: list[Lexicon]) -> str:
    """Format lexicon entries for inclusion in the LLM prompt context.

    Prefers `answerer_expansion` (the split, LLM-facing field). Falls back
    to the legacy `expansion` for entries not yet migrated by the reviewer.
    """
    if not entries:
        return ""
    lines: list[str] = []
    for e in entries:
        body = (e.answerer_expansion or "").strip() or (e.expansion or "").strip()
        if not body:
            continue
        lines.append(f'- "{e.term}": {body}')
    return "\n".join(lines)


def suggest_lexicon_entries_from_failures(
    db: Session, *, tenant_id: UUID, limit: int = 10
) -> list[dict]:
    """Look at recent failed queries and propose lexicon entries.

    A "failed query" = feedback=negative OR failure_mode=retrieval_miss. Each
    one is sent to Claude Haiku with: is there a kibbutz-specific term here
    that a generic search engine wouldn't know? If yes, propose
    {term, expansion}. Results are deduped against the existing lexicon.
    """
    import json

    from anthropic import Anthropic

    from app.config import settings
    from app.models import Query

    failed = (
        db.query(Query)
        .filter(Query.tenant_id == tenant_id)
        .filter(
            (Query.feedback == "negative") | (Query.failure_mode == "retrieval_miss")
        )
        .order_by(Query.created_at.desc())
        .limit(limit)
        .all()
    )
    if not failed:
        return []

    existing_terms = {
        (l.term or "").strip().lower()
        for l in db.query(Lexicon).filter(Lexicon.tenant_id == tenant_id).all()
    }

    client = Anthropic(api_key=settings.anthropic_api_key)
    suggestions: dict[str, dict] = {}

    system_prompt = (
        "אתה עוזר לבנות מילון מונחים פנים-קיבוציים. לכל שאלה — בדוק אם יש מונח שייחודי לקיבוץ "
        "(ראשי תיבות, כינוי פנימי, החלטה ידועה, אירוע היסטורי) שמנוע חיפוש כללי לא יזהה. "
        'אם כן — החזר JSON: {"term": "...", "expansion": "...", "why": "..."}. '
        'אם לא — החזר {"term": null}.'
    )

    for q in failed:
        try:
            resp = client.messages.create(
                model=settings.claude_extract_model,
                max_tokens=300,
                system=system_prompt,
                messages=[{"role": "user", "content": f"שאלה: {q.question}\n\nהחזר JSON בלבד."}],
            )
            raw = resp.content[0].text.strip()
            if raw.startswith("```"):
                raw = raw.strip("`").lstrip("json").strip()
            data = json.loads(raw)
            term = (data.get("term") or "").strip()
            if not term:
                continue
            if term.lower() in existing_terms:
                continue
            if term in suggestions:
                continue
            suggestions[term] = {
                "term": term,
                "expansion": data.get("expansion", ""),
                "why": data.get("why", ""),
                "source_question": q.question,
                "source_query_id": str(q.id),
            }
        except Exception as e:
            log.warning("lexicon.suggest_failed", question=q.question, err=str(e))
            continue

    return list(suggestions.values())
