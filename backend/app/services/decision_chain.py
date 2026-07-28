"""Decision-chain extractor — links escalation chunks to terminal decisions.

The forum chain: ועד הנהלה (committee) decides to pass a topic to the
אסיפה (assembly); the assembly may pass it to the קלפי (ballot); the
highest forum that ruled holds the binding decision. The chunker already
marks protocol items that *escalate* (``decision_type == "escalation"``);
this service finds, for each such chunk, the terminal decision in a
higher-forum document and writes a ``DecisionResolution`` row.

Runs once per document right after classify + amendment extraction, in
the same background task, and works in both directions — ingestion order
is not chronological (archives get uploaded late):

  * The new doc is a higher-forum doc (assembly / ballot): it may resolve
    escalation chunks already sitting in lower-forum protocols.
  * The new doc is a protocol containing escalation chunks: they may
    already be resolved by higher-forum docs in the corpus.

Candidate pairs are pre-selected by vector similarity, then confirmed by
Claude. Links below ``AUTO_APPLY_CONFIDENCE``, with inconsistent dates,
or with an inconsistent forum direction land with ``needs_review=True``
and stay inert until a reviewer approves them — same philosophy as the
amendment extractor: better to miss a chain expansion than to inject a
wrong "binding decision" into answers.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.config import settings
from app.models import Chunk, DecisionResolution, Document

log = structlog.get_logger()

# At or below this the link is written but needs_review=True — it will
# not affect retrieval until approved. Strictly-greater on purpose: the
# matcher hedges with exactly 0.75 on plausible-but-wrong links (first
# production run auto-applied several admission escalations "resolved"
# by an unrelated org-structure doc, all at exactly 0.75).
AUTO_APPLY_CONFIDENCE = 0.75

# Forums that participate in the escalation chain, in rank order.
# A terminal decision must come from a strictly higher-ranked forum.
FORUM_RANK = {"sub_committee": 0, "committee": 1, "assembly": 2, "ballot": 3}

# Bounds on what we show the LLM. The corpus is kibbutz-scale, so these
# mostly guard against pathological docs, not normal load.
MAX_OPEN_ESCALATIONS = 30      # direction A: unresolved escalations offered
MAX_DOC_ESCALATIONS = 12       # direction B: escalations taken from the new doc
MAX_DOC_TERMINALS = 20         # direction A: candidate chunks from the new doc
TERMINAL_CANDIDATES_PER_ESC = 4
SNIPPET_CHARS = 700


@dataclass
class _EscalationItem:
    chunk: Chunk
    doc: Document


@dataclass
class _TerminalCandidate:
    chunk: Chunk
    doc: Document


@lru_cache(maxsize=1)
def _claude_client():
    from anthropic import Anthropic

    return Anthropic(api_key=settings.anthropic_api_key)


SYSTEM_PROMPT = """אתה מזהה שרשראות קבלת החלטות במסמכי ממשל של קיבוץ.

רקע: ועד ההנהלה יכול להחליט להעביר נושא לאסיפה; האסיפה יכולה להעביר לקלפי. פריט "escalation" הוא החלטה להעביר נושא לפורום גבוה יותר — לא החלטה על המהות. "החלטה טרמינלית" היא ההכרעה המהותית באותו נושא בפורום הגבוה.

תקבל:
- רשימת פריטי escalation (מזהה, מסמך, פורום, תאריך, טקסט).
- רשימת מועמדים להחלטה טרמינלית (מזהה קטע, מזהה מסמך, כותרת, פורום, תאריך, טקסט).

המשימה: לכל פריט escalation, לקבוע האם אחד המועמדים הוא ההחלטה הטרמינלית **על אותו נושא בדיוק**. פלוט התאמה רק כשהנושא זהה — לא כשהנושאים רק דומים.

כללים:
1. ההחלטה הטרמינלית חייבת להיות בפורום גבוה יותר מפורום ה-escalation (ועד < אסיפה < קלפי) ובתאריך מאוחר או שווה.
2. אם האסיפה עצמה העבירה את הנושא לקלפי — פרוטוקול האסיפה הוא escalation נוסף, לא ההחלטה הטרמינלית. התאם רק את ההכרעה עצמה (למשל תוצאת הקלפי).
3. topic — סכם את הנושא במשפט קצר בעברית (למשל "שיוך דירות לחברים חדשים").
4. evidence_span — ציטוט קצר מתוך המועמד הטרמינלי שמראה את ההכרעה.
5. confidence: 1.0 = אותו נושא במפורש, אותם מונחים/מספרי החלטה. 0.7 = אותו נושא בסבירות גבוהה. מתחת ל-0.5 — אל תפלוט את ההתאמה בכלל.
6. אל תמציא התאמות. escalation ללא הכרעה תואמת פשוט לא מופיע בפלט — זה ממצא חשוב בפני עצמו (נושא שממתין להכרעה).

הפעל את הכלי match_resolutions. אם אין אף התאמה — resolutions=[]."""


_MATCH_TOOL = {
    "name": "match_resolutions",
    "description": "Emit escalation→terminal decision matches.",
    "input_schema": {
        "type": "object",
        "properties": {
            "resolutions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "escalation_chunk_id": {"type": "string"},
                        "terminal_chunk_id": {"type": "string"},
                        "topic": {"type": "string"},
                        "evidence_span": {"type": ["string", "null"]},
                        "confidence": {"type": "number"},
                    },
                    "required": [
                        "escalation_chunk_id",
                        "terminal_chunk_id",
                        "confidence",
                    ],
                },
            }
        },
        "required": ["resolutions"],
    },
}


def _snippet(text: str | None) -> str:
    return (text or "").strip()[:SNIPPET_CHARS]


def _mean_embedding(chunks: list[Chunk]) -> list[float] | None:
    vecs = [c.embedding for c in chunks if c.embedding is not None]
    if not vecs:
        return None
    dim = len(vecs[0])
    acc = [0.0] * dim
    for v in vecs:
        for i, x in enumerate(v):
            acc[i] += float(x)
    return [x / len(vecs) for x in acc]


def _resolved_chunk_ids(db: Session, chunk_ids: list[UUID]) -> set[UUID]:
    if not chunk_ids:
        return set()
    rows = db.execute(
        select(DecisionResolution.escalation_chunk_id).where(
            DecisionResolution.escalation_chunk_id.in_(chunk_ids)
        )
    ).fetchall()
    return {r[0] for r in rows}


def _open_escalations_below(
    db: Session, *, tenant_id: UUID, max_rank: int, exclude_doc_id: UUID
) -> list[_EscalationItem]:
    """Unresolved escalation chunks in docs whose forum ranks below max_rank."""
    forums = [f for f, r in FORUM_RANK.items() if r < max_rank]
    if not forums:
        return []
    chunks = (
        db.query(Chunk)
        .join(Document, Chunk.document_id == Document.id)
        .filter(
            Chunk.tenant_id == tenant_id,
            Document.forum.in_(forums),
            Document.id != exclude_doc_id,
            Chunk.chunk_metadata["decision_type"].as_string() == "escalation",
        )
        .options(joinedload(Chunk.document))
        .all()
    )
    resolved = _resolved_chunk_ids(db, [c.id for c in chunks])
    return [
        _EscalationItem(chunk=c, doc=c.document) for c in chunks if c.id not in resolved
    ]


def _terminal_candidates_for(
    db: Session, *, tenant_id: UUID, escalation: Chunk, min_rank: int
) -> list[_TerminalCandidate]:
    """Nearest chunks (by cosine) in higher-forum docs for one escalation."""
    if escalation.embedding is None:
        return []
    forums = [f for f, r in FORUM_RANK.items() if r > min_rank]
    if not forums:
        return []
    emb = [float(x) for x in escalation.embedding]
    rows = (
        db.query(Chunk)
        .join(Document, Chunk.document_id == Document.id)
        .filter(
            Chunk.tenant_id == tenant_id,
            Document.forum.in_(forums),
            Chunk.embedding.isnot(None),
            Chunk.document_id != escalation.document_id,
        )
        .order_by(Chunk.embedding.cosine_distance(emb))
        .options(joinedload(Chunk.document))
        .limit(TERMINAL_CANDIDATES_PER_ESC)
        .all()
    )
    return [_TerminalCandidate(chunk=c, doc=c.document) for c in rows]


def _escalations_block(items: list[_EscalationItem]) -> str:
    lines = []
    for it in items:
        eff = it.doc.effective_date.isoformat() if it.doc.effective_date else "unknown"
        lines.append(
            f"- escalation_chunk_id={it.chunk.id} | מסמך={it.doc.filename} | "
            f"פורום={it.doc.forum} | תאריך={eff}\n  טקסט: {_snippet(it.chunk.text)}"
        )
    return "\n".join(lines)


def _terminals_block(cands: list[_TerminalCandidate]) -> str:
    lines = []
    seen: set[UUID] = set()
    for tc in cands:
        if tc.chunk.id in seen:
            continue
        seen.add(tc.chunk.id)
        eff = tc.doc.effective_date.isoformat() if tc.doc.effective_date else "unknown"
        lines.append(
            f"- terminal_chunk_id={tc.chunk.id} | מסמך={tc.doc.filename} | "
            f"פורום={tc.doc.forum} | תאריך={eff}\n  טקסט: {_snippet(tc.chunk.text)}"
        )
    return "\n".join(lines)


def _call_matcher(
    escalations: list[_EscalationItem], terminals: list[_TerminalCandidate]
) -> list[dict]:
    user_message = (
        f"פריטי escalation (החלטות להעביר נושא לפורום גבוה יותר):\n"
        f"{_escalations_block(escalations)}\n\n"
        f"מועמדים להחלטה הטרמינלית:\n{_terminals_block(terminals)}\n\n"
        f"הפעל את הכלי match_resolutions."
    )
    client = _claude_client()
    # Bounded timeout — the default (10min × retries) once held a DB
    # session open long enough for the server to drop the connection.
    resp = client.messages.create(
        model=settings.claude_extract_model,
        max_tokens=4096,
        temperature=0,
        timeout=120.0,
        system=SYSTEM_PROMPT,
        tools=[_MATCH_TOOL],
        tool_choice={"type": "tool", "name": "match_resolutions"},
        messages=[{"role": "user", "content": user_message}],
    )
    for block in resp.content:
        if getattr(block, "type", None) == "tool_use" and getattr(block, "name", "") == "match_resolutions":
            raw = block.input  # type: ignore[attr-defined]
            if isinstance(raw, dict) and isinstance(raw.get("resolutions"), list):
                return [r for r in raw["resolutions"] if isinstance(r, dict)]
    return []


def _write_resolutions(
    db: Session,
    *,
    tenant_id: UUID,
    matches: list[dict],
    escalations_by_id: dict[UUID, _EscalationItem],
    terminals_by_id: dict[UUID, _TerminalCandidate],
) -> tuple[int, int]:
    """Validate matches and persist. Returns (written, needs_review)."""
    written = review = 0
    already = _resolved_chunk_ids(db, list(escalations_by_id.keys()))
    for m in matches:
        try:
            esc_id = UUID(str(m["escalation_chunk_id"]))
            term_id = UUID(str(m["terminal_chunk_id"]))
        except (KeyError, ValueError, TypeError):
            continue
        esc = escalations_by_id.get(esc_id)
        term = terminals_by_id.get(term_id)
        if esc is None or term is None or esc_id in already:
            # Hallucinated id, or a chunk that got resolved meanwhile.
            continue
        confidence = float(m.get("confidence") or 0.0)
        if confidence < 0.5:
            continue

        esc_rank = FORUM_RANK.get(esc.doc.forum or "", -1)
        term_rank = FORUM_RANK.get(term.doc.forum or "", -1)
        forum_ok = esc_rank >= 0 and term_rank > esc_rank
        dates_ok = True
        if esc.doc.effective_date and term.doc.effective_date:
            dates_ok = term.doc.effective_date >= esc.doc.effective_date

        needs_review = (
            confidence <= AUTO_APPLY_CONFIDENCE or not forum_ok or not dates_ok
        )
        db.add(
            DecisionResolution(
                tenant_id=tenant_id,
                escalation_chunk_id=esc.chunk.id,
                escalation_doc_id=esc.doc.id,
                terminal_doc_id=term.doc.id,
                terminal_chunk_id=term.chunk.id,
                topic=(str(m.get("topic") or "").strip() or None),
                evidence_span=(str(m.get("evidence_span") or "").strip() or None),
                extractor_confidence=confidence,
                needs_review=needs_review,
                extractor_model=settings.claude_extract_model,
            )
        )
        already.add(esc_id)
        written += 1
        if needs_review:
            review += 1
    return written, review


def resolve_chains_for_document(db: Session, doc: Document) -> dict:
    """Run both chain directions for one just-ingested document.

    Returns a small dict for logging: {status, written, needs_review}.
    """
    rank = FORUM_RANK.get(doc.forum or "", -1)
    if rank < 0:
        return {"status": "skipped", "reason": f"forum_not_chained:{doc.forum}"}

    doc_chunks = (
        db.query(Chunk)
        .filter(Chunk.document_id == doc.id)
        .order_by(Chunk.position)
        .all()
    )
    if not doc_chunks:
        return {"status": "skipped", "reason": "no_chunks"}

    escalations: list[_EscalationItem] = []
    terminals: list[_TerminalCandidate] = []

    # Direction A — this doc may hold terminal decisions for escalations
    # already sitting in lower-forum protocols. Candidate escalations are
    # ranked by similarity to the doc's mean embedding so a huge backlog
    # can't swamp the prompt.
    if rank > 0:
        open_esc = _open_escalations_below(
            db, tenant_id=doc.tenant_id, max_rank=rank, exclude_doc_id=doc.id
        )
        if open_esc:
            mean = _mean_embedding(doc_chunks)
            if mean is not None and len(open_esc) > MAX_OPEN_ESCALATIONS:
                ids = [it.chunk.id for it in open_esc]
                ordered = (
                    db.query(Chunk.id)
                    .filter(Chunk.id.in_(ids), Chunk.embedding.isnot(None))
                    .order_by(Chunk.embedding.cosine_distance(mean))
                    .limit(MAX_OPEN_ESCALATIONS)
                    .all()
                )
                keep = {r[0] for r in ordered}
                open_esc = [it for it in open_esc if it.chunk.id in keep]
            escalations.extend(open_esc[:MAX_OPEN_ESCALATIONS])
            # Terminal candidates from this doc: prefer chunks the chunker
            # marked terminal; ballot results often carry no הוחלט marker,
            # so fall back to every chunk when none are marked.
            marked = [
                c
                for c in doc_chunks
                if (c.chunk_metadata or {}).get("decision_type") == "terminal"
            ]
            for c in (marked or doc_chunks)[:MAX_DOC_TERMINALS]:
                terminals.append(_TerminalCandidate(chunk=c, doc=doc))

    # Direction B — this doc's own escalation chunks may already be
    # resolved by higher-forum docs in the corpus.
    own_esc = [
        c
        for c in doc_chunks
        if (c.chunk_metadata or {}).get("decision_type") == "escalation"
    ]
    own_resolved = _resolved_chunk_ids(db, [c.id for c in own_esc])
    own_esc = [c for c in own_esc if c.id not in own_resolved][:MAX_DOC_ESCALATIONS]
    if own_esc and rank < max(FORUM_RANK.values()):
        for c in own_esc:
            cands = _terminal_candidates_for(
                db, tenant_id=doc.tenant_id, escalation=c, min_rank=rank
            )
            if cands:
                escalations.append(_EscalationItem(chunk=c, doc=doc))
                terminals.extend(cands)

    if not escalations or not terminals:
        return {"status": "ok", "written": 0, "needs_review": 0}

    escalations_by_id = {it.chunk.id: it for it in escalations}
    terminals_by_id = {tc.chunk.id: tc for tc in terminals}

    try:
        matches = _call_matcher(escalations, terminals)
    except Exception as e:
        log.error("decision_chain.llm_failed", doc_id=str(doc.id), err=str(e)[:300])
        return {"status": "error", "error": str(e)[:200]}

    written, review = _write_resolutions(
        db,
        tenant_id=doc.tenant_id,
        matches=matches,
        escalations_by_id=escalations_by_id,
        terminals_by_id=terminals_by_id,
    )
    db.commit()
    return {"status": "ok", "written": written, "needs_review": review}
