"""Corpus reconciliation — flag contradictions when a new doc is ingested.

For each operative chunk of a just-ingested document (terminal decision
items, bylaw sections), pull its nearest neighbors from the *rest* of the
corpus by vector similarity, and ask Claude to classify every pair:

  * ``contradicts`` — the two texts reach incompatible outcomes on the
    same subject and neither formally amends the other.
  * ``supersedes``  — the newer text de-facto replaces the older rule on
    the same subject without formal amendment language (formal amendments
    are handled by the amendment extractor; this catches the informal
    ones, including a decision that contradicts a bylaw section).
  * ``duplicates``  — same content re-ingested under another guise.

Findings land as ``CorpusFlag(status="pending")`` rows for the reviewer
queue. Deliberately nothing else: a flag never changes retrieval, doc
metadata, or supersession state — those moves stay human-approved.
Covers both decision-vs-decision and decision-vs-bylaw, in both time
directions (the "new" doc may be an old archive uploaded late).
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from uuid import UUID

import structlog
from sqlalchemy.orm import Session, joinedload

from app.config import settings
from app.models import Chunk, CorpusFlag, Document

log = structlog.get_logger()

# Doc types that carry operative rules worth reconciling. Reports,
# notices, contracts etc. produce noise, not policy conflicts.
RECONCILED_DOC_TYPES = {"bylaw", "sub_bylaw", "decision", "minutes"}

# How many of the new doc's chunks to check, and how many corpus
# neighbors to pull per chunk. Pairs are the unit of LLM work, so the
# product (bounded further by MAX_PAIRS) is what controls cost.
MAX_NEW_CHUNKS = 12
NEIGHBORS_PER_CHUNK = 3
MAX_PAIRS = 15
# Neighbors farther than this cosine distance are not plausible
# same-subject material; skip them before they reach the LLM.
MAX_NEIGHBOR_DISTANCE = 0.45

SNIPPET_CHARS = 700

_ALLOWED_KINDS = {"contradicts", "supersedes", "duplicates"}
# Below this the pair is treated as "consistent" and no flag is written.
MIN_FLAG_CONFIDENCE = 0.5


@dataclass
class _Pair:
    new_chunk: Chunk
    existing_chunk: Chunk
    existing_doc: Document


@lru_cache(maxsize=1)
def _claude_client():
    from anthropic import Anthropic

    return Anthropic(api_key=settings.anthropic_api_key)


SYSTEM_PROMPT = """אתה בודק עקביות של מאגר מסמכי ממשל של קיבוץ (תקנונים, תקנוני משנה, החלטות, פרוטוקולים).

תקבל זוגות של קטעים: קטע ממסמך שנקלט עכשיו מול קטע קיים במאגר, כולל מטא-נתונים (מסמך, סוג, פורום, תאריך). לכל זוג, סווג את היחס:

- consistent — עוסקים בנושאים שונים, או באותו נושא בלי סתירה. זה המצב הרגיל.
- duplicates — אותו תוכן מהותי (אותו מסמך בגרסה/סריקה אחרת, אותה החלטה שנקלטה פעמיים).
- supersedes — שני הקטעים קובעים כלל באותו נושא בדיוק, המאוחר מחליף בפועל את המוקדם (גם החלטה שמשנה בפועל סעיף תקנון בלי לשון "תיקון" פורמלית). ציין supersedes רק כשהמאוחר באמת בא במקום המוקדם.
- contradicts — שני הקטעים קובעים תוצאות שאינן מתיישבות זו עם זו באותו נושא, ולא ברור שאחד מחליף את השני (למשל שתי החלטות טרמינליות סותרות, או החלטה שסותרת תקנון בלי הסדרה).

כללים:
1. סווג לפי מהות אופרטיבית: כללים, זכאויות, סכומים, מועדים, סמכויות. דיון כללי או אזכור אגבי של אותו נושא איננו סתירה.
2. אל תסמן supersedes/contradicts כשקטע אחד הוא escalation (החלטה להעביר לפורום אחר) והשני הוא ההכרעה — זו שרשרת תקינה, סווג consistent.
2ב. שים לב ל-מעמד= במטא-נתונים: הצעה (proposal) או טיוטה (draft) שסותרת מסמך מאושר (adopted) איננה סתירה — זה מהלך תקין של הצעת שינוי. סווג consistent. חריג: שתי גרסאות של אותו מסמך שבהן שתיהן adopted — שם supersedes/duplicates רלוונטי.
3. topic — משפט קצר בעברית על הנושא המשותף. explanation — משפט או שניים שמסבירים את הקביעה, כולל מה גובר לדעתך ולמה.
4. evidence_new / evidence_existing — ציטוט קצר מכל צד שמראה את אי-ההתאמה.
5. confidence: 1.0 = ודאי. מתחת ל-0.5 — סווג consistent.
6. עדיף להחמיץ מאשר להציף: סמן רק ממצאים שמזכיר קיבוץ היה רוצה לבדוק.

הפעל את הכלי classify_pairs עם קביעה אחת לכל זוג, לפי pair_index."""


_CLASSIFY_TOOL = {
    "name": "classify_pairs",
    "description": "Classify each (new chunk, existing chunk) pair.",
    "input_schema": {
        "type": "object",
        "properties": {
            "verdicts": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "pair_index": {"type": "integer"},
                        "kind": {
                            "type": "string",
                            "enum": ["consistent", "duplicates", "supersedes", "contradicts"],
                        },
                        "topic": {"type": ["string", "null"]},
                        "explanation": {"type": ["string", "null"]},
                        "evidence_new": {"type": ["string", "null"]},
                        "evidence_existing": {"type": ["string", "null"]},
                        "confidence": {"type": "number"},
                    },
                    "required": ["pair_index", "kind", "confidence"],
                },
            }
        },
        "required": ["verdicts"],
    },
}


def _snippet(text: str | None) -> str:
    return (text or "").strip()[:SNIPPET_CHARS]


def _operative_chunks(db: Session, doc: Document) -> list[Chunk]:
    """The chunks of `doc` worth reconciling, best-first, capped.

    Decisions/minutes: terminal decision chunks first (escalations are
    chain material, not rules). Bylaws: section chunks. Falls back to the
    doc's leading chunks so a doc with no markers still gets checked.
    """
    chunks = (
        db.query(Chunk)
        .filter(Chunk.document_id == doc.id)
        .order_by(Chunk.position)
        .all()
    )
    if not chunks:
        return []
    terminal = [
        c for c in chunks if (c.chunk_metadata or {}).get("decision_type") == "terminal"
    ]
    sectioned = [c for c in chunks if c.section_path]
    picked = terminal or sectioned or chunks
    return picked[:MAX_NEW_CHUNKS]


def _neighbor_pairs(db: Session, doc: Document, new_chunks: list[Chunk]) -> list[_Pair]:
    pairs: list[_Pair] = []
    seen: set[tuple[UUID, UUID]] = set()
    for nc in new_chunks:
        if nc.embedding is None:
            continue
        emb = [float(x) for x in nc.embedding]
        rows = (
            db.query(Chunk, Chunk.embedding.cosine_distance(emb).label("dist"))
            .join(Document, Chunk.document_id == Document.id)
            .filter(
                Chunk.tenant_id == doc.tenant_id,
                Chunk.document_id != doc.id,
                Chunk.embedding.isnot(None),
                Chunk.superseded_by_amendment_id.is_(None),
                Document.superseded_by_id.is_(None),
                Document.doc_type.in_(RECONCILED_DOC_TYPES),
            )
            .order_by("dist")
            .options(joinedload(Chunk.document))
            .limit(NEIGHBORS_PER_CHUNK)
            .all()
        )
        for ec, dist in rows:
            if float(dist) > MAX_NEIGHBOR_DISTANCE:
                continue
            key = (nc.id, ec.id)
            if key in seen:
                continue
            seen.add(key)
            pairs.append(_Pair(new_chunk=nc, existing_chunk=ec, existing_doc=ec.document))
            if len(pairs) >= MAX_PAIRS:
                return pairs
    return pairs


def _doc_line(doc: Document) -> str:
    eff = doc.effective_date.isoformat() if doc.effective_date else "unknown"
    line = f"{doc.filename} | סוג={doc.doc_type or 'unknown'} | פורום={doc.forum or 'unknown'} | תאריך={eff}"
    if doc.doc_status:
        line += f" | מעמד={doc.doc_status}"
    return line


def _pairs_block(doc: Document, pairs: list[_Pair]) -> str:
    blocks = []
    for i, p in enumerate(pairs):
        blocks.append(
            f"### זוג {i}\n"
            f"קטע חדש (מתוך: {_doc_line(doc)}"
            + (f" | סעיף {p.new_chunk.section_path}" if p.new_chunk.section_path else "")
            + f"):\n{_snippet(p.new_chunk.text)}\n\n"
            f"קטע קיים (מתוך: {_doc_line(p.existing_doc)}"
            + (
                f" | סעיף {p.existing_chunk.section_path}"
                if p.existing_chunk.section_path
                else ""
            )
            + f"):\n{_snippet(p.existing_chunk.text)}"
        )
    return "\n\n".join(blocks)


def reconcile_document(db: Session, doc: Document) -> dict:
    """Run the reconciliation pass for one just-ingested document.

    Idempotent: skips if flags already exist with this doc on the new side.
    Returns {status, pairs_checked, flags_written}.
    """
    if (doc.doc_type or "") not in RECONCILED_DOC_TYPES:
        return {"status": "skipped", "reason": f"doc_type_not_reconciled:{doc.doc_type}"}

    existing = (
        db.query(CorpusFlag.id).filter(CorpusFlag.new_doc_id == doc.id).first()
    )
    if existing:
        return {"status": "skipped", "reason": "already_reconciled"}

    new_chunks = _operative_chunks(db, doc)
    if not new_chunks:
        return {"status": "skipped", "reason": "no_chunks"}

    pairs = _neighbor_pairs(db, doc, new_chunks)
    if not pairs:
        return {"status": "ok", "pairs_checked": 0, "flags_written": 0}

    user_message = (
        f"{_pairs_block(doc, pairs)}\n\nהפעל את הכלי classify_pairs."
    )
    try:
        client = _claude_client()
        # Bounded timeout — see decision_chain._call_matcher rationale.
        resp = client.messages.create(
            model=settings.claude_extract_model,
            max_tokens=4096,
            temperature=0,
            timeout=120.0,
            system=SYSTEM_PROMPT,
            tools=[_CLASSIFY_TOOL],
            tool_choice={"type": "tool", "name": "classify_pairs"},
            messages=[{"role": "user", "content": user_message}],
        )
    except Exception as e:
        log.error("reconciliation.llm_failed", doc_id=str(doc.id), err=str(e)[:300])
        return {"status": "error", "error": str(e)[:200]}

    verdicts: list[dict] = []
    for block in resp.content:
        if getattr(block, "type", None) == "tool_use" and getattr(block, "name", "") == "classify_pairs":
            raw = block.input  # type: ignore[attr-defined]
            if isinstance(raw, dict) and isinstance(raw.get("verdicts"), list):
                verdicts = [v for v in raw["verdicts"] if isinstance(v, dict)]
            break

    flags_written = 0
    for v in verdicts:
        kind = str(v.get("kind") or "").strip()
        if kind not in _ALLOWED_KINDS:
            continue
        confidence = float(v.get("confidence") or 0.0)
        if confidence < MIN_FLAG_CONFIDENCE:
            continue
        try:
            pair = pairs[int(v["pair_index"])]
        except (KeyError, ValueError, TypeError, IndexError):
            continue
        db.add(
            CorpusFlag(
                tenant_id=doc.tenant_id,
                new_doc_id=doc.id,
                existing_doc_id=pair.existing_doc.id,
                new_chunk_id=pair.new_chunk.id,
                existing_chunk_id=pair.existing_chunk.id,
                kind=kind,
                topic=(str(v.get("topic") or "").strip() or None),
                explanation=(str(v.get("explanation") or "").strip() or None),
                evidence_new=(str(v.get("evidence_new") or "").strip() or None),
                evidence_existing=(str(v.get("evidence_existing") or "").strip() or None),
                confidence=confidence,
                status="pending",
                extractor_model=settings.claude_extract_model,
            )
        )
        flags_written += 1

    db.commit()
    return {"status": "ok", "pairs_checked": len(pairs), "flags_written": flags_written}
