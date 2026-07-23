"""Highlight spans over an answer string.

Two flavors:
- known: substring matches active lexicon entries → hover shows the expansion.
- candidate: Hebrew-quoted phrases and Hebrew acronyms that are NOT already in
  the lexicon → offered to the user as "add to lexicon".

Kept intentionally simple — regex + substring. If precision becomes an issue we
can move to a proper tokenizer / NER pass.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.orm import Session

from app.models import Lexicon
from app.services import lexicon_matcher


# Hebrew quote flavors we treat as "notable phrase":
#   "…"   straight double quotes
#   ״…״   Hebrew gershayim (U+05F4) — but ONLY when free-standing.
#         Inside a word (יו״ר, מנכ״ל) it's an acronym marker, not a quote.
#         Lookarounds guard: opening ״ must not be preceded by a Hebrew
#         letter; closing ״ must not be followed by one. Otherwise
#         "יו״ר ועד ההנהלה ויו״ר" gets matched as one giant "quote"
#         spanning the two acronyms.
#   «…»   guillemets (rare, but cheap to include)
# Group 1 captures the inner text (first non-empty group across the alternation).
_QUOTED_RE = re.compile(
    r'"([^"\n]{2,40})"'
    r'|(?<![֐-׿])״([^״\n]{2,40})״(?![֐-׿])'
    r'|«([^»\n]{2,40})»'
)

# Hebrew acronym: letters with a gershayim before the last letter, e.g. מנכ״ל.
_ACRONYM_RE = re.compile(r'[֐-׿]{1,6}״[֐-׿]')


@dataclass
class AnnotationSpan:
    start: int
    end: int
    text: str
    kind: str  # "known" | "candidate"
    lexicon_id: UUID | None = None
    expansion: str | None = None


def _find_known_spans(answer: str, entries: list[Lexicon]) -> list[AnnotationSpan]:
    """Delegate to the shared matcher so hover-highlights and retrieval
    agree on what counts as a match. Hover tooltip prefers `short_gloss`;
    falls back to the legacy `expansion`."""
    matches = lexicon_matcher.match_in_text(entries, answer)
    if not matches:
        return []
    by_id = {e.id: e for e in entries}
    spans: list[AnnotationSpan] = []
    for m in matches:
        e = by_id.get(m.lexicon_id)
        if e is None:
            continue
        tooltip = (e.short_gloss or "").strip() or (e.expansion or "").strip()
        spans.append(
            AnnotationSpan(
                start=m.start,
                end=m.end,
                text=m.surface_form,
                kind="known",
                lexicon_id=e.id,
                expansion=tooltip,
            )
        )
    return spans


def _find_candidate_spans(
    answer: str, existing_terms_lower: set[str]
) -> list[AnnotationSpan]:
    spans: list[AnnotationSpan] = []

    for m in _QUOTED_RE.finditer(answer):
        inner = m.group(1) or m.group(2) or m.group(3) or ""
        inner_stripped = inner.strip()
        if not inner_stripped or inner_stripped.lower() in existing_terms_lower:
            continue
        inner_start = m.start() + (m.group(0).find(inner))
        spans.append(
            AnnotationSpan(
                start=inner_start,
                end=inner_start + len(inner),
                text=inner_stripped,
                kind="candidate",
            )
        )

    for m in _ACRONYM_RE.finditer(answer):
        text = m.group(0)
        if text.lower() in existing_terms_lower:
            continue
        spans.append(
            AnnotationSpan(
                start=m.start(),
                end=m.end(),
                text=text,
                kind="candidate",
            )
        )

    return spans


def _resolve_overlaps(spans: list[AnnotationSpan]) -> list[AnnotationSpan]:
    """Non-overlapping spans. Known beats candidate; longer beats shorter; then
    earliest start wins. Also dedupe exact duplicates."""
    if not spans:
        return []
    ranked = sorted(
        spans,
        key=lambda s: (
            0 if s.kind == "known" else 1,
            -(s.end - s.start),
            s.start,
        ),
    )
    chosen: list[AnnotationSpan] = []
    for s in ranked:
        if any(not (s.end <= c.start or s.start >= c.end) for c in chosen):
            continue
        chosen.append(s)
    chosen.sort(key=lambda s: s.start)
    return chosen


def annotate_answer(
    db: Session,
    *,
    tenant_id: UUID,
    answer: str,
    query_id: UUID | None = None,
) -> list[AnnotationSpan]:
    if not answer or not answer.strip():
        return []
    entries = lexicon_matcher.load_active_entries(db, tenant_id=tenant_id)
    # Existing surface_forms (not just canonical term) — a candidate span
    # that already matches an entry variant shouldn't be re-proposed.
    existing_terms_lower: set[str] = set()
    for e in entries:
        for f in (e.surface_forms or []):
            if f:
                existing_terms_lower.add(f.strip().lower())
        if e.term:
            existing_terms_lower.add(e.term.strip().lower())
    known = _find_known_spans(answer, entries)
    candidates = _find_candidate_spans(answer, existing_terms_lower)
    # Record answer_render events for the known matches. We reconstruct
    # Match objects from the resolved spans so overlap-resolved-out
    # duplicates don't inflate stats.
    if known:
        rendered_matches = [
            lexicon_matcher.Match(
                lexicon_id=s.lexicon_id,  # type: ignore[arg-type]
                canonical_term="",  # not used by record_match_events
                surface_form=s.text,
                start=s.start,
                end=s.end,
            )
            for s in known
            if s.lexicon_id is not None
        ]
        lexicon_matcher.record_match_events(
            db,
            tenant_id=tenant_id,
            matches=rendered_matches,
            context="answer_render",
            query_id=query_id,
        )
    return _resolve_overlaps(known + candidates)
