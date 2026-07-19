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


# Hebrew quote flavors we treat as "notable phrase":
#   "…"   straight double quotes
#   ״…״   Hebrew gershayim (U+05F4)
#   «…»   guillemets (rare, but cheap to include)
# Group 1 captures the inner text.
_QUOTED_RE = re.compile(r'"([^"\n]{2,40})"|״([^״\n]{2,40})״|«([^»\n]{2,40})»')

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
    spans: list[AnnotationSpan] = []
    # Longer terms first so "בית ילדים" wins over "בית".
    for e in sorted(entries, key=lambda x: -len(x.term or "")):
        term = (e.term or "").strip()
        if not term or len(term) < 2:
            continue
        start = 0
        while True:
            idx = answer.find(term, start)
            if idx < 0:
                break
            end = idx + len(term)
            spans.append(
                AnnotationSpan(
                    start=idx,
                    end=end,
                    text=term,
                    kind="known",
                    lexicon_id=e.id,
                    expansion=e.expansion,
                )
            )
            start = end
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
    db: Session, *, tenant_id: UUID, answer: str
) -> list[AnnotationSpan]:
    if not answer or not answer.strip():
        return []
    entries = (
        db.query(Lexicon)
        .filter(Lexicon.tenant_id == tenant_id)
        .filter(Lexicon.status == "active")
        .all()
    )
    existing_terms_lower = {
        (e.term or "").strip().lower() for e in entries if e.term
    }
    known = _find_known_spans(answer, entries)
    candidates = _find_candidate_spans(answer, existing_terms_lower)
    return _resolve_overlaps(known + candidates)
