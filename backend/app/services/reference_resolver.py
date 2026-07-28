"""Bind each LLM-emitted reference to a real Document, or drop it.

Why this exists
---------------

The answerer returns references whose ``title`` is free text the model
wrote. It is *asked* for the filename verbatim (llm.py prompt), but models
reliably normalise what they echo — most commonly collapsing runs of
whitespace. 38% of the Elrom corpus has double-spaced filenames, so a
strict string comparison against ``documents.filename`` failed for roughly
two in five citations, and the UI silently dropped the "open source"
button for documents that were sitting right there on disk.

The frontend used to do that comparison itself with ``===``. It no longer
does anything of the sort: this module resolves every reference against
the documents that actually fed the turn, and the API returns a real
``document_id`` plus the *canonical* filename read from the database.

Two consequences worth stating plainly:

  * The title the user sees is always a filename that exists. The model's
    string is never displayed. Whitespace drift, a spliced extension, or
    an outright invented name cannot reach the browser.
  * A reference that cannot be bound to a retrieved document is dropped,
    and the count is reported to the caller. A citation whose document
    can't be identified is not verifiable by the reader, so presenting it
    as a source would be a claim we can't stand behind. Dropping is
    logged at WARNING with the candidate list so a matcher that is too
    strict shows up in the logs rather than as a silently thinner answer.

Candidates are scoped to the documents that contributed chunks to *this*
turn — never the whole corpus. That scoping is what makes fabrication
detectable at all: a title matching nothing in the retrieved set is, by
construction, not something the model was shown.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from uuid import UUID

import structlog

log = structlog.get_logger()

# Score below which a candidate is not considered a match at all. Tiers
# below are spaced so that "one name contains the other" clears it and a
# weak token overlap does not.
ACCEPT_SCORE = 70.0

# Extensions we strip before comparing stems. The model frequently swaps
# one for another when two near-duplicate uploads differ only by format.
_EXTENSIONS = (".pdf", ".docx", ".doc", ".txt", ".rtf", ".odt")

# The one legitimate reference with no document behind it: the answerer
# emits this when replying to a corpus-meta question ("how many documents
# do you have?") from the injected stats block. There is no chunk to cite.
META_TITLE = "מאגר הארגון"


def _normalise(s: str) -> str:
    """Fold the differences a model introduces when echoing a filename."""
    s = unicodedata.normalize("NFKC", s)
    # Hebrew maqaf and the various dashes all read as "-" to a model.
    s = s.replace("־", "-").replace("–", "-").replace("—", "-")
    # Any run of whitespace (incl. NBSP) becomes one space. This single
    # line is what fixes the 38%.
    s = re.sub(r"[\s ]+", " ", s)
    return s.strip().casefold()


def _stem(s: str) -> str:
    """Normalised name with a trailing known extension removed."""
    n = _normalise(s)
    for ext in _EXTENSIONS:
        if n.endswith(ext):
            return n[: -len(ext)].strip()
    return n


def _tokens(s: str) -> set[str]:
    return {t for t in re.split(r"[^\w֐-׿]+", _stem(s)) if t}


def _score(title: str, filename: str) -> float:
    """How strongly `title` designates `filename`. 0 means no match."""
    if title == filename:
        return 100.0
    if _normalise(title) == _normalise(filename):
        return 95.0  # whitespace / dash drift only — the common case
    t_stem, f_stem = _stem(title), _stem(filename)
    if t_stem == f_stem:
        return 90.0  # same name, extension swapped or dropped
    if t_stem and f_stem and (t_stem in f_stem or f_stem in t_stem):
        return 75.0  # model shortened the name, or added a prefix
    t_tok, f_tok = _tokens(title), _tokens(filename)
    if t_tok and f_tok:
        jaccard = len(t_tok & f_tok) / len(t_tok | f_tok)
        if jaccard >= 0.55:
            return 50.0 + 45.0 * jaccard
    return 0.0


@dataclass
class Candidate:
    document_id: UUID
    filename: str
    has_file: bool
    chunk_count: int


@dataclass
class ResolvedReference:
    # Canonical filename from the database — never the model's string.
    title: str
    section_number: str
    source_type: str
    excerpt: str
    document_id: UUID | None
    has_file: bool
    # False only for the corpus-meta reference, which has no document.
    resolved: bool
    # What the model actually emitted, when it differed from the canonical
    # filename. Kept for debugging/telemetry; the UI does not show it.
    model_title: str | None = None


def build_candidates(sources) -> list[Candidate]:
    """Collapse chunk-level citations into one candidate per document.

    `sources` is the SourceCitation list for the turn: several chunks
    routinely come from the same file, and the chunk count is a useful
    tie-breaker when two near-duplicate documents both match a title.
    """
    by_doc: dict[UUID, Candidate] = {}
    for s in sources:
        if s.document_id is None:
            continue
        existing = by_doc.get(s.document_id)
        if existing is None:
            by_doc[s.document_id] = Candidate(
                document_id=s.document_id,
                filename=s.document_filename,
                has_file=bool(s.has_file),
                chunk_count=1,
            )
        else:
            existing.chunk_count += 1
    return list(by_doc.values())


def resolve_references(references, sources) -> tuple[list[ResolvedReference], int]:
    """Bind references to retrieved documents.

    Returns (resolved, dropped_count). Order of the surviving references is
    preserved — the model orders them by relevance and the UI relies on it.
    """
    candidates = build_candidates(sources)
    out: list[ResolvedReference] = []
    dropped: list[str] = []

    for r in references:
        title = (r.title or "").strip()
        source_type = (r.source_type or "").strip()

        # The corpus-meta reference legitimately has no document behind it.
        if source_type.lower() == "meta" and title == META_TITLE:
            out.append(
                ResolvedReference(
                    title=title,
                    section_number=r.section_number,
                    source_type=r.source_type,
                    excerpt=r.excerpt,
                    document_id=None,
                    has_file=False,
                    resolved=False,
                )
            )
            continue

        if not title or not candidates:
            dropped.append(title)
            continue

        # Best candidate; ties broken by how much the document actually
        # contributed to this answer, which is the right signal when two
        # near-duplicate uploads (same meeting, .pdf and .docx) both match.
        best: Candidate | None = None
        best_score = 0.0
        for c in candidates:
            sc = _score(title, c.filename)
            if sc > best_score or (
                sc == best_score
                and best is not None
                and c.chunk_count > best.chunk_count
            ):
                best, best_score = c, sc

        if best is None or best_score < ACCEPT_SCORE:
            dropped.append(title)
            continue

        out.append(
            ResolvedReference(
                # Canonical name from the DB, not what the model wrote.
                title=best.filename,
                section_number=r.section_number,
                source_type=r.source_type,
                excerpt=r.excerpt,
                document_id=best.document_id,
                has_file=best.has_file,
                resolved=True,
                model_title=title if title != best.filename else None,
            )
        )

    if dropped:
        # Not an error — the guardrail working. Logged so that a matcher
        # which has become too strict is visible in the logs instead of
        # quietly thinning out answers.
        log.warning(
            "reference_resolver.dropped_unmatched",
            dropped_titles=dropped,
            retrieved_filenames=[c.filename for c in candidates],
        )

    return out, len(dropped)
