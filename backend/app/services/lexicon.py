"""Per-tenant lexicon — domain terms that a generic AI doesn't know about.

Example: "השינוי" means "the transition from kibbutz shitufi to mitchadesh, see
the 2008 שינוי agreement and the related bylaws." NotebookLM doesn't know that.
We tell Claude explicitly when those terms appear in a query.

Used at query time: scan question for known terms, collect their expansions,
prepend them to the LLM context as a "domain note" block.
"""
from uuid import UUID

import structlog
from sqlalchemy.orm import Session

from app.models import Lexicon

log = structlog.get_logger()


def find_relevant_terms(db: Session, *, tenant_id: UUID, question: str) -> list[Lexicon]:
    """Return active lexicon entries whose term appears in the question.

    Simple substring match for MVP. Could be improved with lemmatization
    (Hebrew morphology) in a later iteration.
    """
    candidates = (
        db.query(Lexicon)
        .filter(Lexicon.tenant_id == tenant_id)
        .all()
    )
    hits = [c for c in candidates if c.term and c.term in question]
    if hits:
        log.info(
            "lexicon.hit",
            count=len(hits),
            terms=[c.term for c in hits],
        )
    return hits


def format_lexicon_block(entries: list[Lexicon]) -> str:
    """Format lexicon entries for inclusion in the LLM prompt context."""
    if not entries:
        return ""
    lines = [f"- \"{e.term}\": {e.expansion}" for e in entries]
    return "\n".join(lines)
