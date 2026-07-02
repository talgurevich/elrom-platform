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

from app.models import Amendment, Chunk, Document
from app.services.hebrew_text import normalize_hebrew
from app.services.reranker import rerank


@dataclass
class RetrievalDebug:
    vector: list[dict] = field(default_factory=list)
    bm25: list[dict] = field(default_factory=list)
    fused: list[dict] = field(default_factory=list)
    reranked: list[dict] = field(default_factory=list)
    amendments: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "vector": self.vector,
            "bm25": self.bm25,
            "fused": self.fused,
            "reranked": self.reranked,
            "amendments": self.amendments,
        }


@dataclass
class AmendmentContext:
    """An amendment that touches one of the retrieved chunks.

    Handed to the answerer so it sees the chain — a later `add_after` clause
    or `clarify` gloss that the vanilla top-k missed. ``superseded_chunk_id``
    is set when this amendment replaces one of the retrieved chunks (in
    practice this shouldn't happen because we filter superseded chunks out,
    but we keep the field so the LLM can be told explicitly).
    """

    target_doc_filename: str
    target_section: str
    action: str
    new_text: str | None
    effective_date: str | None
    rationale: str | None
    amendment_doc_filename: str
    superseded_chunk_id: UUID | None = None

    def format_for_prompt(self) -> str:
        header = (
            f"[תיקון פעיל • תוקף {self.effective_date or 'לא מפורש'} • "
            f"פעולה: {self.action}] סעיף {self.target_section} של "
            f"{self.target_doc_filename} תוקן ב-{self.amendment_doc_filename}."
        )
        body_parts = []
        if self.new_text:
            body_parts.append(f"נוסח מעודכן: {self.new_text}")
        if self.rationale:
            body_parts.append(f"סיבה: {self.rationale}")
        return header + ("\n" + "\n".join(body_parts) if body_parts else "")


def hybrid_retrieve(
    db: Session,
    *,
    tenant_id: UUID,
    query: str,
    query_embedding: list[float],
    top_k: int = 5,
    include_superseded: bool = False,
) -> tuple[list[Chunk], RetrievalDebug, list[AmendmentContext]]:
    """Return (top-k chunks, per-stage debug payload, active amendments touching those chunks).

    ``include_superseded`` — when the query is historical ("מה היה כתוב לפני
    התיקון?"), the caller can set this to True and get the raw pre-amendment
    text. Default False: only currently-in-force material reaches the
    answerer, which is the answer the user almost always wants.
    """
    debug = RetrievalDebug()

    # Pull a much larger raw pool, then apply per-document diversity *before*
    # any downstream stage. Without this, an oversized document (e.g.
    # תקנון בנים נסמכים at 83 chunks) saturates the candidate set and
    # starves smaller-but-equally-relevant bylaws from ever being considered.
    VECTOR_RAW = top_k * 8
    VECTOR_PER_DOC_CAP = 3

    vector_q = (
        db.query(Chunk, Chunk.embedding.cosine_distance(query_embedding).label("dist"))
        .filter(Chunk.tenant_id == tenant_id)
        .filter(Chunk.embedding.isnot(None))
    )
    if not include_superseded:
        vector_q = vector_q.filter(Chunk.superseded_by_amendment_id.is_(None))
    raw_vector = (
        vector_q.order_by("dist")
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

    # Normalize the query identically to the way text_search was built at
    # ingest, so prefix/suffix-attached Hebrew tokens actually match. Without
    # this, ``הירושה`` in the query and ``ירושה`` in the corpus never collide.
    bm25_query = normalize_hebrew(query)
    superseded_clause = "" if include_superseded else " AND superseded_by_amendment_id IS NULL"
    bm25_sql = text(
        f"""
        SELECT id, ts_rank(text_search, plainto_tsquery('simple', :q)) AS rank
        FROM chunks
        WHERE tenant_id = :tenant_id
          AND text_search @@ plainto_tsquery('simple', :q)
          {superseded_clause}
        ORDER BY rank DESC
        LIMIT :limit
        """
    )
    bm25_rows = db.execute(
        bm25_sql, {"q": bm25_query, "tenant_id": tenant_id, "limit": top_k * 4}
    ).fetchall() if bm25_query else []
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

    amendment_context = _amendment_chain_for_chunks(db, tenant_id=tenant_id, chunks=final)
    debug.amendments = [
        {
            "target_doc": ac.target_doc_filename,
            "section": ac.target_section,
            "action": ac.action,
            "effective_date": ac.effective_date,
            "amendment_doc": ac.amendment_doc_filename,
        }
        for ac in amendment_context
    ]
    return final, debug, amendment_context


def _amendment_chain_for_chunks(
    db: Session, *, tenant_id: UUID, chunks: list[Chunk]
) -> list[AmendmentContext]:
    """For each retrieved chunk with a section_ref, fetch all active
    amendments that touch (chunk.document_id, chunk.section_ref) and turn
    them into ``AmendmentContext`` rows for the answerer.

    ``needs_review=True`` amendments are excluded — they haven't been
    approved yet and would be a hallucination risk if surfaced to the LLM.
    """
    keys = {(c.document_id, c.section_ref) for c in chunks if c.section_ref}
    if not keys:
        return []

    doc_ids = {d for d, _ in keys}
    sections = {s for _, s in keys}
    rows = (
        db.query(Amendment)
        .filter(
            Amendment.tenant_id == tenant_id,
            Amendment.needs_review.is_(False),
            Amendment.target_doc_id.in_(doc_ids),
            Amendment.target_section.in_(sections),
        )
        .all()
    )
    # Filter to exact (doc, section) pairs — the SQL IN clauses are a
    # superset because target_doc and target_section are indexed separately.
    rows = [a for a in rows if (a.target_doc_id, a.target_section) in keys]
    if not rows:
        return []

    doc_ids_needed = {a.target_doc_id for a in rows} | {a.amendment_doc_id for a in rows}
    docs = {
        d.id: d
        for d in db.query(Document).filter(Document.id.in_(doc_ids_needed)).all()
    }
    chunk_by_key = {(c.document_id, c.section_ref): c for c in chunks if c.section_ref}

    contexts: list[AmendmentContext] = []
    for a in sorted(rows, key=lambda r: (r.effective_date or r.created_at.date())):
        target_doc = docs.get(a.target_doc_id)
        amend_doc = docs.get(a.amendment_doc_id)
        if target_doc is None or amend_doc is None:
            continue
        matched = chunk_by_key.get((a.target_doc_id, a.target_section))
        contexts.append(
            AmendmentContext(
                target_doc_filename=target_doc.filename,
                target_section=a.target_section,
                action=a.action,
                new_text=a.new_text,
                effective_date=a.effective_date.isoformat() if a.effective_date else None,
                rationale=a.rationale,
                amendment_doc_filename=amend_doc.filename,
                superseded_chunk_id=matched.id if matched else None,
            )
        )
    return contexts
