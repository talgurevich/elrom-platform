"""Human-in-the-loop authoritative answer cache.

When a reviewer marks an answer as authoritative, future questions with
similar semantic embedding return the marked answer directly, bypassing
the LLM entirely. This is the moat vs. generic AI tools.
"""
from uuid import UUID

import structlog
from sqlalchemy.orm import Session

from app.models import AuthoritativeAnswer

log = structlog.get_logger()


def find_cached_answer(
    db: Session,
    *,
    tenant_id: UUID,
    question_embedding: list[float],
) -> AuthoritativeAnswer | None:
    """Find the closest active authoritative answer that meets its similarity threshold.

    Cosine distance: 0 = identical, 2 = opposite. similarity = 1 - distance.
    Each authoritative answer has its own per-row threshold; we filter on it.
    """
    distance = AuthoritativeAnswer.canonical_question_embedding.cosine_distance(question_embedding)

    row = (
        db.query(AuthoritativeAnswer, distance.label("dist"))
        .filter(AuthoritativeAnswer.tenant_id == tenant_id)
        .filter(AuthoritativeAnswer.status == "active")
        .filter(AuthoritativeAnswer.canonical_question_embedding.isnot(None))
        .order_by(distance)
        .limit(1)
        .first()
    )

    if row is None:
        return None

    answer, dist = row
    similarity = 1.0 - float(dist)

    if similarity >= answer.similarity_threshold:
        log.info(
            "hitl.cache_hit",
            answer_id=str(answer.id),
            similarity=similarity,
            threshold=answer.similarity_threshold,
        )
        return answer

    log.info("hitl.cache_miss", best_similarity=similarity, threshold=answer.similarity_threshold)
    return None


def find_near_misses(
    db: Session,
    *,
    tenant_id: UUID,
    question_embedding: list[float],
    min_similarity: float = 0.82,
    max_similarity: float = 0.92,
    limit: int = 3,
) -> list[tuple[AuthoritativeAnswer, float]]:
    """Return authoritative answers that are *close* but didn't trigger the cache.

    Surfaced as "you might already have an approved answer for this" hints —
    so reviewers don't approve near-duplicates and so end-users can see an
    existing authoritative answer alongside a fresh LLM one.
    """
    distance = AuthoritativeAnswer.canonical_question_embedding.cosine_distance(question_embedding)
    rows = (
        db.query(AuthoritativeAnswer, distance.label("dist"))
        .filter(AuthoritativeAnswer.tenant_id == tenant_id)
        .filter(AuthoritativeAnswer.status == "active")
        .filter(AuthoritativeAnswer.canonical_question_embedding.isnot(None))
        .order_by(distance)
        .limit(limit * 4)
        .all()
    )
    out: list[tuple[AuthoritativeAnswer, float]] = []
    for answer, dist in rows:
        sim = 1.0 - float(dist)
        if min_similarity <= sim < max_similarity:
            out.append((answer, sim))
        if len(out) >= limit:
            break
    return out
