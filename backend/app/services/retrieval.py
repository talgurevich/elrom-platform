"""Retrieval service — hybrid (vector + BM25) lookup over chunks + Cohere rerank.

Pipeline:
  1. Pull top ~4*K candidates by vector cosine similarity
  2. Pull top ~4*K candidates by Postgres FTS (BM25-ish)
  3. Reciprocal-rank fusion to get a unified ranking
  4. Cohere Rerank to tighten the final top_k

Returns (final_chunks, debug_payload). Debug captures per-stage scores so the
UI can show "what was retrieved and why" for failure triage.
"""
import re
from dataclasses import dataclass, field
from datetime import date
from uuid import UUID

from sqlalchemy import func as sa_func
from sqlalchemy import text
from sqlalchemy.orm import Session, joinedload

from app.models import Amendment, Chunk, Document
from app.services.hebrew_text import normalize_hebrew, normalize_hebrew_to_tsquery
from app.services.reranker import rerank


# ─── Per-doc-type retrieval knobs ──────────────────────────────────────
#
# Bylaws are dense and self-contained — 2 chunks is usually enough context.
# Protocols (minutes) and decisions unfold across many consecutive chunks
# (agenda → discussion → decision → dissent → vote) and were being starved
# by the old flat cap. Caps below are per doc_type, with a `_default` for
# doc_type=None / unknown.
#
# See the "protocols / decisions retrieval" discussion for rationale.

_VECTOR_CAP = {
    "bylaw": 3,
    "sub_bylaw": 3,
    "decision": 6,
    "minutes": 6,
    "other": 3,
    "_default": 3,
}

_FINAL_CAP = {
    "bylaw": 2,
    "sub_bylaw": 2,
    "decision": 5,
    "minutes": 5,
    "other": 2,
    "_default": 2,
}


def _cap_for(doc_type: str | None, table: dict[str, int]) -> int:
    return table.get(doc_type or "", table["_default"])


# Recency boost — decisions and protocols age. A 2018 decision usually
# yields to a 2024 one on the same topic. Bylaws don't decay this way
# (amendments handle their versioning), so they're excluded.
#
# Boost is added to the RRF fusion score. RRF scores are roughly in the
# 0.01–0.03 range for reasonable ranks, so a 0.005 boost per decade of
# recency is enough to break lightweight ties without overriding a
# strongly-relevant older doc.

_RECENCY_BOOSTED_TYPES = frozenset(["decision", "minutes"])
_RECENCY_WEIGHT_PER_YEAR = 0.0005  # ~0.005 for a decade newer


def _recency_boost(doc: Document, today: date) -> float:
    """Returns a small positive number for recent decisions/protocols and
    zero for everything else. Linear ramp: today = full weight, 20+
    years old = zero. Bylaws never get a boost — see comment above."""
    if not doc or doc.doc_type not in _RECENCY_BOOSTED_TYPES:
        return 0.0
    ed = doc.effective_date
    if ed is None:
        return 0.0
    years_old = max(0, today.year - ed.year)
    if years_old >= 20:
        return 0.0
    # Fresher → bigger boost.
    return (20 - years_old) * _RECENCY_WEIGHT_PER_YEAR


# ─── Year-anchored retrieval ────────────────────────────────────────
#
# Queries that name a year ("מי התקבל לחברות ב2014", "בין 2010 ל-2015")
# don't get date-filtered — semantic search treats the year as just
# another token, and BM25 misses it when the doc renders the date as
# "15.08.14" instead of "2014". Result: docs from the requested year
# often never make retrieval, even when their content is a perfect match.
#
# Fix: extract year(s) from the query, pull chunks from docs whose
# effective_date falls in that range, and inject them into the fusion
# combined score with a boost strong enough to guarantee they enter
# the rerank pool. Reranker then decides which are actually relevant.

# Year regex — can't use \b because Hebrew prefix letters (ב2014, ל2014)
# don't create a word boundary before the digit. Use digit-lookarounds
# instead: no digit before, no digit after.
_YEAR_RANGE_RE = re.compile(
    r"(?:בין\s+)?(?P<from>(?<!\d)(?:19|20)\d{2}(?!\d))\s*"
    r"(?:[-–]|עד|ל[-\s]?)\s*"
    r"(?P<to>(?<!\d)(?:19|20)\d{2}(?!\d))"
)
_SINGLE_YEAR_RE = re.compile(r"(?<!\d)(?:19|20)\d{2}(?!\d)")

# How many year-matched chunks to seed *per year in the range*. Small
# enough to not swamp fusion, big enough that a multi-year range gets
# even coverage. For a 9-year range this yields ~45 chunks total.
YEAR_SEED_PER_YEAR = 5
# Hard cap on total year-seed chunks to protect fusion latency on very
# wide ranges ("החלטות 1990-2026").
YEAR_SEED_MAX_TOTAL = 80
# Boost added to fusion combined score for year-matched chunks. RRF
# scores sit around 0.01–0.03, so 0.03 makes a year-match roughly
# equivalent to a top-3 vector hit — guarantees it enters candidates
# without silencing genuinely-better semantic matches.
YEAR_MATCH_BOOST = 0.03


def _extract_year_range(query: str) -> tuple[int, int] | None:
    """Return (from_year, to_year) if the query names a year or range,
    else None. Range wins over single year — 'בין 2010 ל-2015' returns
    (2010, 2015). A lone year returns (year, year); multiple lone years
    span the min→max."""
    if not query:
        return None
    m = _YEAR_RANGE_RE.search(query)
    if m:
        f, t = int(m.group("from")), int(m.group("to"))
        return (min(f, t), max(f, t))
    years = [int(mm.group(0)) for mm in _SINGLE_YEAR_RE.finditer(query)]
    if years:
        return (min(years), max(years))
    return None


def _rerank_hint(chunk: Chunk) -> str:
    """Prefix a doc-type-aware hint to the chunk text passed to the
    reranker. Cohere doesn't see doc_type as metadata, so a bracketed
    prefix in the text is the cheapest way to give it that signal.

    Examples:
      [החלטה 47/22 · 2024-03-14] …chunk text…
      [פרוטוקול אסיפה · 2024-03-14] …chunk text…
      [תקנון שיוך דירות · סעיף 3.2] …chunk text…
    """
    doc = chunk.document
    if doc is None:
        return chunk.text
    tag_parts: list[str] = []
    meta = doc.doc_metadata or {}
    if doc.doc_type == "decision":
        num = str(meta.get("decision_number") or "").strip()
        tag_parts.append(f"החלטה {num}" if num else "החלטה")
    elif doc.doc_type == "minutes":
        num = str(meta.get("meeting_number") or "").strip()
        tag_parts.append(f"פרוטוקול {num}" if num else "פרוטוקול")
    elif doc.doc_type in ("bylaw", "sub_bylaw"):
        # For bylaws the section is more useful than the doc name.
        title = (doc.filename or "").rsplit(".", 1)[0]
        if title:
            tag_parts.append(title[:40])
    else:
        title = (doc.filename or "").rsplit(".", 1)[0]
        if title:
            tag_parts.append(title[:40])
    if doc.effective_date:
        tag_parts.append(doc.effective_date.isoformat())
    if chunk.section_path:
        tag_parts.append(f"סעיף {chunk.section_path}")
    if not tag_parts:
        return chunk.text
    return f"[{' · '.join(tag_parts)}] {chunk.text}"


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

    # For multi-year range queries, expand top_k so the answerer sees
    # chunks from more distinct years. 5 chunks can't enumerate 9 years.
    _range = _extract_year_range(query)
    if _range and (_range[1] - _range[0]) >= 2:
        span = _range[1] - _range[0] + 1
        top_k = min(max(top_k, span + 2), 15)

    # Pull a much larger raw pool, then apply per-document diversity *before*
    # any downstream stage. Without this, an oversized document (e.g.
    # תקנון בנים נסמכים at 83 chunks) saturates the candidate set and
    # starves smaller-but-equally-relevant bylaws from ever being considered.
    # Cap is per doc_type: bylaws stay tight (3), protocols/decisions get
    # more headroom (6) because their relevant context spans more chunks.
    VECTOR_RAW = top_k * 8

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
        cap = _cap_for(c.document.doc_type if c.document else None, _VECTOR_CAP)
        n = vector_per_doc.get(c.document_id, 0)
        if n >= cap:
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

    # Build a per-source-word OR / cross-source-word AND tsquery so the
    # BM25 lane actually retrieves. The old code passed the normalized flat
    # string to plainto_tsquery, which ANDs everything — including every
    # alternative normalized form of the same source word. Recall collapsed
    # to zero on real Hebrew queries (see project_bm25_hebrew_gap memo).
    bm25_query = normalize_hebrew_to_tsquery(query)
    superseded_clause = "" if include_superseded else " AND superseded_by_amendment_id IS NULL"
    bm25_sql = text(
        f"""
        SELECT id, ts_rank(text_search, to_tsquery('simple', :q)) AS rank
        FROM chunks
        WHERE tenant_id = :tenant_id
          AND text_search @@ to_tsquery('simple', :q)
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

    # Year-anchored seeding — when the query names a year or range,
    # pull chunks from docs whose effective_date falls in range and
    # inject them with a strong fusion boost. Fixes the "מה קרה ב2014"
    # class of query where BM25 misses the year token and vector
    # loses short chunks to longer generic ones.
    #
    # Doc-first, then chunks-per-doc: previously we ORDER BY date DESC
    # LIMIT N at chunk level, so a doc-rich year (2020 with 100+ chunks)
    # ate the whole budget before older years were reached. Now we
    # enumerate distinct docs by year, guaranteeing per-year coverage.
    year_range = _extract_year_range(query)
    if year_range:
        y_from, y_to = year_range
        # Get all docs whose effective_date falls in range, newest first.
        # This is a small result set (docs, not chunks).
        docs_in_range = (
            db.query(Document)
            .filter(Document.tenant_id == tenant_id)
            .filter(Document.effective_date.isnot(None))
            .filter(sa_func.extract("year", Document.effective_date) >= y_from)
            .filter(sa_func.extract("year", Document.effective_date) <= y_to)
            .order_by(Document.effective_date.desc())
            .all()
        )
        # Round-robin: for each doc, pull its first N chunks; cap chunks
        # per year across all its docs so one doc-heavy year doesn't
        # crowd out sparse years.
        per_year: dict[int, int] = {}
        year_seed: list[Chunk] = []
        for d in docs_in_range:
            if d.effective_date is None:
                continue
            yr = d.effective_date.year
            if per_year.get(yr, 0) >= YEAR_SEED_PER_YEAR:
                continue
            remaining_for_year = YEAR_SEED_PER_YEAR - per_year.get(yr, 0)
            chunks_q = (
                db.query(Chunk)
                .filter(Chunk.document_id == d.id)
                .order_by(Chunk.position)
                .options(joinedload(Chunk.document))
            )
            if not include_superseded:
                chunks_q = chunks_q.filter(
                    Chunk.superseded_by_amendment_id.is_(None)
                )
            for c in chunks_q.limit(remaining_for_year).all():
                year_seed.append(c)
                per_year[yr] = per_year.get(yr, 0) + 1
                if len(year_seed) >= YEAR_SEED_MAX_TOTAL:
                    break
            if len(year_seed) >= YEAR_SEED_MAX_TOTAL:
                break
        for c in year_seed:
            combined[c.id] = combined.get(c.id, 0.0) + YEAR_MATCH_BOOST
            vector_chunks.setdefault(c.id, (c, 1.0))

    # Recency boost — small linear bump for decisions/protocols by
    # effective_date. Zero for bylaws (amendments handle their versioning).
    # See _recency_boost + _RECENCY_WEIGHT_PER_YEAR for rationale.
    today = date.today()
    # Merge chunk→document lookups from both lanes so BM25-only chunks
    # can also be boosted.
    all_chunk_docs: dict[UUID, Chunk] = {cid: c for cid, (c, _) in vector_chunks.items()}
    if bm25_rows:
        for cid, c in bm25_chunk_map.items():
            all_chunk_docs.setdefault(cid, c)
    for chunk_id, chunk_obj in all_chunk_docs.items():
        boost = _recency_boost(chunk_obj.document, today)
        if boost:
            combined[chunk_id] = combined.get(chunk_id, 0.0) + boost

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

    # Recency-aware ordering: when two chunks have near-identical fusion scores,
    # prefer the one with the more recent effective_date. This is a tiebreaker,
    # not a re-rank — a strong semantic hit still beats a weak recent one. The
    # epsilon is small (1e-6) so it only affects genuine ties.
    order_map = {cid: i for i, cid in enumerate(top_ids)}
    def _sort_key(c: Chunk) -> tuple[float, float]:
        rrf_rank = order_map.get(c.id, 1_000_000)
        # Newer effective_date → smaller tiebreaker. No date → treated as oldest.
        ed_ts = -c.effective_date.toordinal() if c.effective_date else 0
        return (rrf_rank, ed_ts * 1e-6)
    candidates.sort(key=_sort_key)

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
    # Pass doc-type-hinted text to Cohere so it can see the source type
    # (bracketed prefix — see _rerank_hint).
    rerank_texts = [_rerank_hint(c) for c in candidates]
    reranked = rerank(query, candidates, top_n=max(top_k * 3, 12), texts=rerank_texts)

    # Per-document diversity: cap each document at _FINAL_CAP[doc_type] chunks.
    # Bylaws at 2 (self-contained sections), protocols/decisions at 5
    # (context spans multiple consecutive chunks).
    per_doc: dict[UUID, int] = {}
    final: list[Chunk] = []
    for c in reranked:
        cap = _cap_for(c.document.doc_type if c.document else None, _FINAL_CAP)
        n = per_doc.get(c.document_id, 0)
        if n >= cap:
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
