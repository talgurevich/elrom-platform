"""Structural chunking — break a document into atomic units.

MVP version: split on paragraph boundaries with a soft target length. Hebrew bylaws
are usually structured by `סעיף N` markers. Week 2 will add header-aware chunking
that recognizes those structural cues.
"""
import re

TARGET_CHUNK_CHARS = 1200
MIN_CHUNK_CHARS = 200


def chunk_document(text: str) -> list[str]:
    """Split a document into chunks.

    Strategy:
    1. Split on blank lines (paragraphs)
    2. Greedily combine paragraphs up to TARGET_CHUNK_CHARS
    3. Drop chunks shorter than MIN_CHUNK_CHARS (likely noise)
    """
    text = text.strip()
    if not text:
        return []

    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]

    chunks: list[str] = []
    buffer = ""

    for para in paragraphs:
        if len(buffer) + len(para) + 2 <= TARGET_CHUNK_CHARS:
            buffer = f"{buffer}\n\n{para}" if buffer else para
        else:
            if buffer:
                chunks.append(buffer)
            buffer = para

    if buffer:
        chunks.append(buffer)

    return [c for c in chunks if len(c) >= MIN_CHUNK_CHARS or len(chunks) == 1]
