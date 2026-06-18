"""Retrieval service — hybrid (vector + BM25) lookup over chunks + Cohere rerank.

Pipeline:
  1. Pull top ~4*K candidates by vector cosine similarity
  2. Pull top ~4*K candidates by Postgres FTS (BM25-ish)
  3. Reciprocal-rank fusion to get a unified ranking
  4. Cohere Rerank to tighten the final top_k

Returns (final_chunks, debug_payload). Debug captures per-stage scores so the
UI can show "what was retrieved and why" for failure triage.
"""
from dataclasses import dataclass, field
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session, joinedload

from app.models import Chunk
from app.services.reranker import rerank


@dataclass
class RetrievalDebug:
    vector: list[dict] = field(default_factory=list)
    bm25: list[dict] = field(default_factory=list)
    fused: list[dict] = field(default_factory=list)
    reranked: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "vector": self.vector,
            "bm25": self.bm25,
            "fused": self.fused,
            "reranked": self.reranked,
        }


def hybrid_retrieve(
    db: Session,
    *,
    tenant_id: UUID,
    query: str,
    query_embedding: list[float],
    top_k: int = 5,
) -> tuple[list[Chunk], RetrievalDebug]:
    """Return (top-k chunks, per-stage debug payload)."""
    debug = RetrievalDebug()

    # Pull a much larger raw pool, then apply per-document diversity *before*
    # any downstream stage. Without this, an oversized document (e.g.
    # תקנון בנים נסמכים at 83 chunks) saturates the candidate set and
    # starves smaller-but-equally-relevant bylaws from ever being considered.
    VECTOR_RAW = top_k * 8
    VECTOR_PER_DOC_CAP = 3

    raw_vector = (
        db.query(Chunk, Chunk.embedding.cosine_distance(query_embedding).label("dist"))
        .filter(Chunk.tenant_id == tenant_id)
        .filter(Chunk.embedding.isnot(None))
        .order_by("dist")
        .limit(VECTOR_RAW)
        .options(joinedload(Chunk.document))
        .all()
    )

    vector_results: list = []
    vector_per_doc: dict[UUID, int] = {}
    for c, dist in raw_vector:
        n = vector_per_doc.get(c.document_id, 0)
        if n >= VECTOR_PER_DOC_CAP:
            continue
        vector_per_doc[c.document_id] = n + 1
        vector_results.append((c, dist))
        if len(vector_results) >= top_k * 4:
            break
    debug.vector = [
        {
            "chunk_id": str(c.id),
            "document_filename": c.document.filename,
            "section_path": c.section_path,
            "cosine_similarity": round(1.0 - float(dist), 4),
        }
        for c, dist in vector_results[:8]
    ]

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

    if bm25_rows:
        bm25_chunk_map = {
            c.id: c
            for c in db.query(Chunk)
            .filter(Chunk.id.in_([r.id for r in bm25_rows]))
            .options(joinedload(Chunk.document))
            .all()
        }
        debug.bm25 = [
            {
                "chunk_id": str(row.id),
                "document_filename": bm25_chunk_map[row.id].document.filename
                if row.id in bm25_chunk_map
                else "?",
                "section_path": bm25_chunk_map[row.id].section_path
                if row.id in bm25_chunk_map
                else None,
                "ts_rank": round(float(row.rank), 4),
            }
            for row in bm25_rows[:8]
        ]

    # Reciprocal-rank-fusion-style combination
    combined: dict[UUID, float] = {}

    for i, (chunk_id, _) in enumerate(sorted(vector_chunks.items(), key=lambda kv: kv[1][1])):
        combined[chunk_id] = combined.get(chunk_id, 0.0) + 1.0 / (i + 60)

    bm25_sorted = sorted(bm25_scores.items(), key=lambda kv: kv[1], reverse=True)
    for i, (chunk_id, _) in enumerate(bm25_sorted):
        combined[chunk_id] = combined.get(chunk_id, 0.0) + 1.0 / (i + 60)

    candidate_n = max(top_k * 4, 12)
    top_ids = [
        cid for cid, _ in sorted(combined.items(), key=lambda kv: kv[1], reverse=True)[:candidate_n]
    ]

    if not top_ids:
        return [], debug

    candidates = (
        db.query(Chunk)
        .filter(Chunk.id.in_(top_ids))
        .options(joinedload(Chunk.document))
        .all()
    )

    order_map = {cid: i for i, cid in enumerate(top_ids)}
    candidates.sort(key=lambda c: order_map.get(c.id, 1_000_000))

    debug.fused = [
        {
            "chunk_id": str(c.id),
            "document_filename": c.document.filename,
            "section_path": c.section_path,
            "fusion_score": round(combined[c.id], 5),
        }
        for c in candidates[:8]
    ]

    # Rerank a larger pool so we have headroom for the diversity filter.
    reranked = rerank(query, candidates, top_n=max(top_k * 3, 12))

    # Per-document diversity: cap each document at MAX_PER_DOC chunks. Prevents
    # a single oversized document (e.g. תקנון בנים נסמכים at 83 chunks) from
    # monopolizing the final top-K and starving other relevant bylaws.
    MAX_PER_DOC = 2
    per_doc: dict[UUID, int] = {}
    final: list[Chunk] = []
    for c in reranked:
        n = per_doc.get(c.document_id, 0)
        if n >= MAX_PER_DOC:
            continue
        per_doc[c.document_id] = n + 1
        final.append(c)
        if len(final) >= top_k:
            break

    # If the diversity filter starved the result (shouldn't happen in practice),
    # fall back to filling with the next reranked items regardless of source.
    if len(final) < top_k:
        seen = {c.id for c in final}
        for c in reranked:
            if c.id in seen:
                continue
            final.append(c)
            if len(final) >= top_k:
                break

    debug.reranked = [
        {
            "chunk_id": str(c.id),
            "document_filename": c.document.filename,
            "section_path": c.section_path,
            "rank": i + 1,
        }
        for i, c in enumerate(final)
    ]
    return final, debug
