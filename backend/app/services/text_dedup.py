"""Cross-format duplicate detection via normalized-text hashing.

Problem: ``content_sha256`` catches only byte-identical re-uploads.
A PDF and a DOCX of the same document, or a re-scanned PDF, or the same
file re-exported through Word, all have different bytes → they slip
through the exact-hash dedup even though the *text* is the same.

Approach: hash a heavily-normalized form of the extracted text. Two
documents whose bytes differ but whose normalized text matches share a
``text_sha256`` and get filed as a ``CorpusFlag(kind='duplicates')`` for
reviewer confirmation. This is a **soft** signal — near-duplicates are
legitimate (revised drafts, re-exports) and we let the reviewer choose,
so we never reject at ingest time.

The normalization is aggressive on purpose: OCR jitter and format
round-trips produce small textual differences that a naive whitespace
normalize would miss. We strip:
  * Unicode combining marks (nikud, cantillation) — an OCR run might
    or might not preserve these.
  * Zero-width chars, bidi controls, other formatting oddities.
  * All non-alphanumeric characters (punctuation, quotes, dashes) —
    Word/PDF differ on "smart quotes" and dash width.
  * Whitespace runs → single space, then finally all whitespace is
    dropped before hashing so paragraph re-flow doesn't matter.
The residue is Hebrew/Latin/digit codepoints only, which is the most
stable extractable surface across formats.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from uuid import UUID

from sqlalchemy.orm import Session

from app.models import Document

# Anything that's not a letter or digit gets dropped. Category prefixes:
#   L* — letters (Hebrew, Latin, everything)
#   N* — numbers
_KEEP_CATEGORY_PREFIXES = ("L", "N")


def normalize_for_hash(text: str) -> str:
    """Reduce arbitrary extracted text to a stable canonical form for hashing.

    Idempotent: ``normalize_for_hash(normalize_for_hash(x)) == normalize_for_hash(x)``.
    Empty input returns empty string (caller should treat that as "no hash").
    """
    if not text:
        return ""
    # NFKD splits combined chars into base + combining marks, so the
    # category filter below can drop the marks (Mn, Mc, Me) uniformly.
    decomposed = unicodedata.normalize("NFKD", text)
    kept = [
        ch for ch in decomposed
        if unicodedata.category(ch)[0] in _KEEP_CATEGORY_PREFIXES
    ]
    return "".join(kept).casefold()


def hash_normalized(text: str) -> str | None:
    """SHA256 of the normalized form. Returns None for empty/whitespace-only
    input so callers can skip storing meaningless hashes."""
    norm = normalize_for_hash(text)
    if not norm:
        return None
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()


def find_text_duplicate(
    db: Session,
    *,
    tenant_id: UUID,
    text_sha256: str,
    exclude_doc_id: UUID | None = None,
) -> Document | None:
    """Return one existing document in the same tenant that shares this
    normalized-text hash, or None. Prefers the oldest match so successive
    re-uploads all point at the same "original" as the existing doc."""
    q = (
        db.query(Document)
        .filter(Document.tenant_id == tenant_id)
        .filter(Document.text_sha256 == text_sha256)
    )
    if exclude_doc_id is not None:
        q = q.filter(Document.id != exclude_doc_id)
    return q.order_by(Document.ingested_at.asc()).first()
