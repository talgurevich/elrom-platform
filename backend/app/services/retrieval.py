"""Retrieval service — hybrid (vector + BM25) lookup over chunks.

MVP scope: combine vector similarity and Postgres full-text search results.
A reranker layer (Cohere Rerank) is added in Week 2.
"""
from uuid import UUID

from sqlalchemy import func, text
from sqlalchemy.orm import Session, joinedload

from app.models import Chunk


def hybrid_retrieve(
    db: Session,
    *,
    tenant_id: UUID,
    query: str,
    query_embedding: list[float],
    top_k: int = 5,
) -> list[Chunk]:
    """Return top-k chunks by hybrid score (vector + keyword)."""
    vector_results = (
        db.query(Chunk, Chunk.embedding.cosine_distance(query_embedding).label("dist"))
        .filter(Chunk.tenant_id == tenant_id)
        .filter(Chunk.embedding.isnot(None))
        .order_by("dist")
        .limit(top_k * 4)
        .options(joinedload(Chunk.document))
        .all()
    )

    vector_chunks = {c.id: (c, dist) for c, dist in vector_results}

    bm25_sql = text(
        """
        SELECT id, ts_rank(text_search, plainto_tsquery('simple', :q)) AS rank
        FROM chunks
        WHERE tenant_id = :tenant_id
          AND text_search @@ plainto_tsquery('simple', :q)
        ORDER BY rank DESC
        LIMIT :limit
        """
    )
    bm25_rows = db.execute(
        bm25_sql, {"q": query, "tenant_id": tenant_id, "limit": top_k * 4}
    ).fetchall()

    bm25_scores = {row.id: row.rank for row in bm25_rows}

    # Reciprocal-rank-fusion-style combination: normalize each list's contribution.
    combined: dict[UUID, float] = {}

    for i, (chunk_id, _) in enumerate(sorted(vector_chunks.items(), key=lambda kv: kv[1][1])):
        combined[chunk_id] = combined.get(chunk_id, 0.0) + 1.0 / (i + 60)

    bm25_sorted = sorted(bm25_scores.items(), key=lambda kv: kv[1], reverse=True)
    for i, (chunk_id, _) in enumerate(bm25_sorted):
        combined[chunk_id] = combined.get(chunk_id, 0.0) + 1.0 / (i + 60)

    top_ids = [cid for cid, _ in sorted(combined.items(), key=lambda kv: kv[1], reverse=True)[:top_k]]

    if not top_ids:
        return []

    # Re-fetch with relationship loaded so the route can read filename without N+1
    return (
        db.query(Chunk)
        .filter(Chunk.id.in_(top_ids))
        .options(joinedload(Chunk.document))
        .all()
    )
