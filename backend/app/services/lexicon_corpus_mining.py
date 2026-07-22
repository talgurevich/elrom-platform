"""Corpus mining — signals 4 (doc-frequent, query-rare) and 5 (query-
frequent, doc-miss).

Tokenization is deliberately naive: whitespace + punctuation split, strip
Hebrew prefix letters (ה/ל/ב/מ/ש/ו/כ) from the front of each token,
lowercase Latin, drop tokens shorter than 3 chars. No morphology.

Rationale for staying naive: real Hebrew tokenization (Yap, HebPipe)
adds runtime deps and a heavy model. For a nightly proposer whose output
is human-reviewed, false candidates cost a click; false negatives cost
missing terms. Cheap-and-noisy over expensive-and-precise.

Both signals share the same tokenizer + counter pass to keep DB
pressure low: one scan over recent chunks, one scan over recent queries.
"""
from __future__ import annotations

import re
from collections import Counter
from datetime import datetime
from uuid import UUID

import structlog
from sqlalchemy.orm import Session

from app.models import Chunk, Lexicon, Query
from app.services.lexicon_harvest import _existing_surface_forms, _insert_pending
from app.services.lexicon_proposer import propose_entry

log = structlog.get_logger()

# Hebrew letter class (u0590-u05FF covers Hebrew block). Latin letters
# tolerated for tokens like "COVID" or "OCR" that show up in docs.
_TOKEN_RE = re.compile(r"[֐-׿\w]{2,40}")
_PREFIX_STRIP_RE = re.compile(r"^[הלבמשוכ]+")

# Ignore very common Hebrew function words. Not exhaustive — the proposer
# LLM will also reject noise, this is just a cheap first pass.
_STOP_WORDS = frozenset(
    [
        "את", "של", "על", "לא", "כן", "אבל", "אם", "או", "גם", "רק",
        "יש", "אין", "היה", "היו", "יהיה", "כדי", "לפי", "לאחר", "לפני",
        "בין", "מול", "כמו", "בגלל", "אצל", "שלה", "שלו", "שלנו", "שלכם",
        "אנחנו", "אתם", "אתה", "אני", "הוא", "היא", "הם", "הן", "זה", "זאת",
        "שם", "פה", "כאן", "מה", "מי", "איך", "למה", "מתי", "איפה",
        "אחר", "אחת", "אחד", "כל", "לכל", "כמה", "יותר", "פחות", "מאוד",
    ]
)

# Signal thresholds — tuned for order-of-magnitude sensible defaults on a
# typical kibbutz corpus (~20 docs, ~500 queries/month). Real tuning is a
# future concern; today the goal is "does anything sensible come out."
DOC_FREQ_MIN = 8       # signal 4: term appears in >= 8 doc chunks
QUERY_FREQ_MAX = 2     # signal 4: but in < 3 queries
QUERY_FREQ_MIN = 5     # signal 5: term appears in >= 5 queries
DOC_FREQ_MAX = 0       # signal 5: but no doc mentions


def _tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    for m in _TOKEN_RE.finditer(text or ""):
        raw = m.group(0)
        stripped = _PREFIX_STRIP_RE.sub("", raw)
        if len(stripped) < 3:
            continue
        low = stripped.lower()
        if low in _STOP_WORDS:
            continue
        tokens.append(stripped)
    return tokens


def _count_terms(texts: list[str]) -> Counter:
    """Doc-set / query-set frequency (how many *texts* each token appears
    in, not raw occurrences — one term mentioned 20 times in one doc counts
    once)."""
    counter: Counter = Counter()
    for text in texts:
        seen = set(_tokenize(text))
        for t in seen:
            counter[t] += 1
    return counter


def harvest_corpus_mining(
    db: Session, *, tenant_id: UUID, since: datetime, max_proposals: int = 15
) -> dict:
    """Run signals 4 and 5. Returns counts by signal.

    `since` bounds the query scan (recent user vocabulary). Docs aren't
    time-bounded — the whole active corpus counts as "ambient vocabulary."
    """
    doc_texts = [
        c.text for c in db.query(Chunk.text).filter(Chunk.tenant_id == tenant_id).all()
    ]
    query_texts = [
        q.question or ""
        for q in db.query(Query.question)
        .filter(Query.tenant_id == tenant_id)
        .filter(Query.created_at >= since)
        .all()
    ]
    if not doc_texts and not query_texts:
        return {"doc_frequent": 0, "query_frequent": 0}

    doc_freq = _count_terms(doc_texts)
    query_freq = _count_terms(query_texts)
    known = _existing_surface_forms(db, tenant_id=tenant_id)

    # Signal 4 — terms your corpus uses that users never say.
    signal4 = sorted(
        (
            t
            for t, c in doc_freq.items()
            if c >= DOC_FREQ_MIN and query_freq.get(t, 0) <= QUERY_FREQ_MAX
        ),
        key=lambda t: -doc_freq[t],
    )
    # Signal 5 — terms users say that never appear in your docs. These are
    # often the exact vocabulary-gap signal that hurts retrieval.
    signal5 = sorted(
        (
            t
            for t, c in query_freq.items()
            if c >= QUERY_FREQ_MIN and doc_freq.get(t, 0) <= DOC_FREQ_MAX
        ),
        key=lambda t: -query_freq[t],
    )

    inserted_by_signal = {"doc_frequent": 0, "query_frequent": 0}
    proposals_left = max_proposals

    def _propose(term: str, signal_type: str, context: str, extra_evidence: dict) -> None:
        nonlocal proposals_left
        if proposals_left <= 0:
            return
        if term.strip().lower() in known:
            return
        proposal = propose_entry(
            candidate_term=term,
            context_snippet=context,
            signal_type=signal_type,
        )
        if not proposal:
            return
        row = _insert_pending(
            db,
            tenant_id=tenant_id,
            proposal=proposal,
            signal_type=signal_type,
            evidence={"candidate_term": term, **extra_evidence},
        )
        if row is not None:
            inserted_by_signal[
                "doc_frequent" if signal_type == "doc_frequent" else "query_frequent"
            ] += 1
            known.add(row.term.strip().lower())
            proposals_left -= 1

    # Interleave the two signals so a term-dense corpus doesn't starve the
    # query-frequent list of its Haiku budget.
    for term in signal4[:max_proposals]:
        # Grab a representative doc chunk mentioning the term for context.
        ctx = next((t for t in doc_texts if term in t), "")
        _propose(
            term,
            "doc_frequent",
            ctx,
            {"doc_freq": doc_freq[term], "query_freq": query_freq.get(term, 0)},
        )
    for term in signal5[:max_proposals]:
        ctx = next((t for t in query_texts if term in t), "")
        _propose(
            term,
            "query_frequent",
            ctx,
            {"doc_freq": doc_freq.get(term, 0), "query_freq": query_freq[term]},
        )

    return inserted_by_signal
