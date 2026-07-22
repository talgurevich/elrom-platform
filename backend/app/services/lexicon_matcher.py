"""LexiconMatcher — word-boundary-aware match over surface_forms.

Used by two consumers with the same matching logic:

1. Retrieval side (`services/lexicon.find_relevant_terms`): scans a user
   question for known terms, injects expansions into the answerer prompt.
2. Highlighter (`services/answer_annotations._find_known_spans`): renders
   hover chips over an answer.

Word-boundary handling: Hebrew has no capitalization and re.escape+\b works
because Hebrew letters are word characters in the Unicode default. We
compile one regex per entry with all its surface_forms alternated, longest
first so "בית ילדים" wins over "בית". Compiled regexes are cached per
Python process — cheap given tens of lexicon entries per tenant.

Match events are recorded via `record_match_events` so the reviewer stats
panel can show 30-day hit counts per entry. Recording is best-effort — a DB
failure here must not break retrieval or rendering.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from uuid import UUID

import structlog
from sqlalchemy.orm import Session

from app.models import Lexicon, LexiconMatchEvent

log = structlog.get_logger()


@dataclass(frozen=True)
class Match:
    lexicon_id: UUID
    canonical_term: str
    surface_form: str
    start: int
    end: int


@lru_cache(maxsize=1024)
def _compile_pattern(forms_tuple: tuple[str, ...]) -> re.Pattern[str]:
    """One regex per entry, alternating all forms longest-first with word
    boundaries. Cached across calls — surface_forms per entry rarely change."""
    ordered = sorted({f for f in forms_tuple if f}, key=len, reverse=True)
    if not ordered:
        # Match-nothing sentinel so callers don't need to guard.
        return re.compile(r"(?!x)x")
    alt = "|".join(re.escape(f) for f in ordered)
    return re.compile(rf"(?<!\w)(?:{alt})(?!\w)")


def _forms_of(entry: Lexicon) -> tuple[str, ...]:
    forms = tuple(entry.surface_forms or ())
    if not forms and entry.term:
        # Legacy safety: pre-backfill rows only have `term`.
        forms = (entry.term,)
    return forms


def match_in_text(entries: list[Lexicon], text: str) -> list[Match]:
    """Return every non-overlapping match of any entry's surface_forms in
    `text`. Longer terms across entries win over shorter ones (a "בית
    ילדים" entry beats a "בית" entry on overlap)."""
    if not text or not entries:
        return []
    raw: list[Match] = []
    for e in entries:
        pat = _compile_pattern(_forms_of(e))
        for m in pat.finditer(text):
            raw.append(
                Match(
                    lexicon_id=e.id,
                    canonical_term=e.term,
                    surface_form=m.group(0),
                    start=m.start(),
                    end=m.end(),
                )
            )
    # Cross-entry overlap resolution: longer span wins, then earliest start.
    raw.sort(key=lambda m: (-(m.end - m.start), m.start))
    chosen: list[Match] = []
    for m in raw:
        if any(not (m.end <= c.start or m.start >= c.end) for c in chosen):
            continue
        chosen.append(m)
    chosen.sort(key=lambda m: m.start)
    return chosen


def load_active_entries(db: Session, *, tenant_id: UUID) -> list[Lexicon]:
    return (
        db.query(Lexicon)
        .filter(Lexicon.tenant_id == tenant_id)
        .filter(Lexicon.status == "active")
        .all()
    )


def record_match_events(
    db: Session,
    *,
    tenant_id: UUID,
    matches: list[Match],
    context: str,
    query_id: UUID | None = None,
) -> None:
    """Best-effort event recording. Never raises — a stats-table failure
    must not break retrieval or rendering."""
    if not matches:
        return
    try:
        # Dedupe: one event per (lexicon_id, surface_form) per call. Multiple
        # matches of the same surface form in one answer/query = one usage
        # signal, not many.
        seen: set[tuple[UUID, str]] = set()
        for m in matches:
            key = (m.lexicon_id, m.surface_form)
            if key in seen:
                continue
            seen.add(key)
            db.add(
                LexiconMatchEvent(
                    tenant_id=tenant_id,
                    lexicon_id=m.lexicon_id,
                    surface_form=m.surface_form,
                    context=context,
                    query_id=query_id,
                )
            )
        db.flush()
    except Exception as e:  # noqa: BLE001
        log.warning("lexicon_matcher.record_events_failed", err=str(e))
