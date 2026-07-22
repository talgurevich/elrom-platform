"""Signal collectors that feed the lexicon proposer.

Signals implemented here:
- reviewer_edit: reviewer approved an answer with edits. Diff and enqueue
  any noun-phrase-shaped candidate that appears in the edit but not in the
  original — those are terms the reviewer thought worth adding/changing.
- auto_quoted_acronym: quoted phrases + Hebrew acronyms in recent answers
  that appear across ≥ THRESHOLD distinct queries. Runs in the nightly
  batch, not in the request path.

Insertion side-effect: rows land as `status="pending"` with
`source="learned"` — same shape as the existing refinement-pair learner
uses, so the reviewer queue and weekly digest work unchanged.
"""
from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable
from datetime import datetime, timedelta, timezone
from uuid import UUID

import structlog
from sqlalchemy.orm import Session

from app.models import Lexicon, Query
from app.services.lexicon_proposer import propose_entry

log = structlog.get_logger()

# Shared regexes (mirror answer_annotations._QUOTED_RE / _ACRONYM_RE).
_QUOTED_RE = re.compile(r'"([^"\n]{2,40})"|״([^״\n]{2,40})״|«([^»\n]{2,40})»')
_ACRONYM_RE = re.compile(r'[֐-׿]{1,6}״[֐-׿]')

# A candidate must appear in this many distinct answers within the harvest
# window before we spend a Haiku call on it. Prevents one-off quoted noise.
AUTO_QUOTED_MIN_DISTINCT = 3


def _existing_surface_forms(db: Session, *, tenant_id: UUID) -> set[str]:
    """All surface_forms + canonical terms in this tenant, lowercased.
    Used to dedupe candidates against everything already curated —
    including rejected ones (we don't re-propose things a reviewer killed)."""
    entries = db.query(Lexicon).filter(Lexicon.tenant_id == tenant_id).all()
    known: set[str] = set()
    for e in entries:
        if e.term:
            known.add(e.term.strip().lower())
        for f in (e.surface_forms or []):
            if f:
                known.add(f.strip().lower())
    return known


def _extract_candidates(text: str) -> list[str]:
    """Extract quoted-phrase inner text + acronyms from a body of text."""
    if not text:
        return []
    out: list[str] = []
    for m in _QUOTED_RE.finditer(text):
        inner = (m.group(1) or m.group(2) or m.group(3) or "").strip()
        if inner:
            out.append(inner)
    for m in _ACRONYM_RE.finditer(text):
        out.append(m.group(0))
    return out


def _insert_pending(
    db: Session,
    *,
    tenant_id: UUID,
    proposal: dict,
    signal_type: str,
    evidence: dict,
    source_query_id: UUID | None = None,
) -> Lexicon | None:
    """Insert as pending. Returns the row on success; None if the proposer
    returned nothing or the term ended up duplicate."""
    term = (proposal.get("term") or "").strip()
    if not term:
        return None
    known = _existing_surface_forms(db, tenant_id=tenant_id)
    if term.lower() in known:
        return None
    row = Lexicon(
        tenant_id=tenant_id,
        term=term,
        surface_forms=proposal.get("surface_forms") or [term],
        short_gloss=proposal.get("short_gloss") or "",
        answerer_expansion=proposal.get("answerer_expansion") or "",
        # Legacy `expansion` NOT NULL — mirror the new field so old readers
        # (and the eval/summary code) keep working.
        expansion=proposal.get("answerer_expansion") or proposal.get("short_gloss") or term,
        entry_type=proposal.get("entry_type") or "definition",
        notes=f"harvested via {signal_type}",
        source="learned",
        status="pending",
        confidence=proposal.get("confidence"),
        evidence={**evidence, "signal_type": signal_type},
        learned_from_query_id=source_query_id,
    )
    db.add(row)
    return row


# ─── Signal 3: reviewer edits ─────────────────────────────────────────


def _diff_new_candidates(original: str, edited: str) -> list[str]:
    """Candidates that appear in `edited` but not in `original`, extracted
    with the same regex the highlighter uses."""
    orig_candidates = set(_extract_candidates(original))
    edited_candidates = _extract_candidates(edited)
    return [c for c in edited_candidates if c not in orig_candidates]


def harvest_from_reviewer_edit(
    db: Session,
    *,
    tenant_id: UUID,
    original_answer: str,
    edited_answer: str,
    source_query_id: UUID | None = None,
) -> int:
    """Called synchronously from the reviewer approve endpoint when
    edited_answer is provided. Returns number of pending rows inserted."""
    if not edited_answer or edited_answer == original_answer:
        return 0
    new_candidates = _diff_new_candidates(original_answer or "", edited_answer)
    if not new_candidates:
        return 0
    known = _existing_surface_forms(db, tenant_id=tenant_id)
    inserted = 0
    for candidate in new_candidates:
        if candidate.strip().lower() in known:
            continue
        proposal = propose_entry(
            candidate_term=candidate,
            context_snippet=edited_answer,
            signal_type="reviewer_edit",
        )
        if not proposal:
            continue
        row = _insert_pending(
            db,
            tenant_id=tenant_id,
            proposal=proposal,
            signal_type="reviewer_edit",
            evidence={
                "candidate_term": candidate,
                "edited_answer_snippet": edited_answer[:400],
            },
            source_query_id=source_query_id,
        )
        if row is not None:
            inserted += 1
            known.add(row.term.strip().lower())
    if inserted:
        log.info("lexicon_harvest.reviewer_edit", tenant_id=str(tenant_id), inserted=inserted)
    return inserted


# ─── Signal 6: auto quoted/acronym (nightly) ──────────────────────────


def harvest_auto_quoted_acronym(
    db: Session, *, tenant_id: UUID, since: datetime
) -> int:
    """Batch harvester: scans all Query.answer within window, aggregates
    quoted phrases + acronyms, proposes anything hit in ≥ THRESHOLD
    distinct queries and not already in the lexicon."""
    queries = (
        db.query(Query)
        .filter(Query.tenant_id == tenant_id)
        .filter(Query.created_at >= since)
        .filter(Query.answer.isnot(None))
        .all()
    )
    if not queries:
        return 0

    # candidate → set of query IDs where it appeared
    hits: dict[str, set[UUID]] = defaultdict(set)
    # candidate → representative answer text (first one we saw)
    context_for: dict[str, str] = {}
    for q in queries:
        answer = q.answer or ""
        for c in _extract_candidates(answer):
            hits[c].add(q.id)
            context_for.setdefault(c, answer)

    known = _existing_surface_forms(db, tenant_id=tenant_id)
    inserted = 0
    for candidate, query_ids in hits.items():
        if len(query_ids) < AUTO_QUOTED_MIN_DISTINCT:
            continue
        if candidate.strip().lower() in known:
            continue
        proposal = propose_entry(
            candidate_term=candidate,
            context_snippet=context_for[candidate],
            signal_type="auto_quoted_acronym",
        )
        if not proposal:
            continue
        row = _insert_pending(
            db,
            tenant_id=tenant_id,
            proposal=proposal,
            signal_type="auto_quoted_acronym",
            evidence={
                "candidate_term": candidate,
                "distinct_query_count": len(query_ids),
                "sample_query_ids": [str(q) for q in list(query_ids)[:5]],
            },
        )
        if row is not None:
            inserted += 1
            known.add(row.term.strip().lower())
    if inserted:
        log.info(
            "lexicon_harvest.auto_quoted",
            tenant_id=str(tenant_id),
            inserted=inserted,
            candidates_seen=len(hits),
        )
    return inserted
