"""Structural chunking — break a document into atomic units.

Hebrew bylaws and meeting protocols have clear structural markers:
  - "סעיף N:" / "סעיף N." — clause / item
  - "פרק N" / "פרק א" — chapter
  - "נוהל N" — procedure
  - "החלטה N" — decision (in meeting protocols)

We split on those boundaries so each chunk = one atomic unit of legal/policy
meaning. The section_path is carried as metadata so citations can point to it.

Pre-section text (the document title block) gets chunked separately so that
"תקנון קליטה לחברות" isn't merged into "סעיף 1: ..." and dilute the embedding.

For documents with no detectable structure we fall back to paragraph-based
chunking (T1 behavior).
"""
import re
from dataclasses import dataclass

TARGET_CHUNK_CHARS = 1500
MIN_HEADER_CHARS = 80   # only keep doc preamble if it's substantial
MIN_SECTION_CHARS = 25  # keep short legal clauses — they're often meaningful
MIN_PARAGRAPH_CHARS = 80
MAX_CHUNK_CHARS = 3500 # split oversized sections


@dataclass
class StructuralChunk:
    text: str
    section_path: str | None  # e.g. "סעיף 2" or None for the header
    position: int


# Matches a line beginning with a structural marker. Group 1 captures the
# marker label (e.g. "סעיף 4א").
SECTION_RE = re.compile(
    r"^(סעיף\s+[֐-׿0-9א-ת]+(?:[א-ת]?)|פרק\s+[א-ת0-9]+|נוהל\s+[א-ת0-9]+|החלטה(?:\s+מספר)?\s+[א-ת0-9./\-]+)",
    re.MULTILINE,
)


def chunk_document(text: str) -> list[StructuralChunk]:
    """Split a document into structural chunks.

    Returns ordered list of StructuralChunk. Position is 0-indexed and matches
    output ordering.
    """
    text = text.strip()
    if not text:
        return []

    matches = list(SECTION_RE.finditer(text))

    if not matches:
        return _paragraph_chunks(text)

    chunks: list[StructuralChunk] = []

    # Header / pre-section content (title, preamble)
    if matches[0].start() > 0:
        header = text[: matches[0].start()].strip()
        if len(header) >= MIN_HEADER_CHARS:
            chunks.append(StructuralChunk(text=header, section_path=None, position=len(chunks)))

    # Each detected section
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        section_text = text[m.start() : end].strip()
        if len(section_text) < MIN_SECTION_CHARS:
            continue
        section_path = m.group(1).strip()
        if len(section_text) <= MAX_CHUNK_CHARS:
            chunks.append(
                StructuralChunk(text=section_text, section_path=section_path, position=len(chunks))
            )
        else:
            for sub_text in _split_long_section(section_text):
                chunks.append(
                    StructuralChunk(
                        text=sub_text, section_path=section_path, position=len(chunks)
                    )
                )

    return chunks


def _paragraph_chunks(text: str) -> list[StructuralChunk]:
    """Fallback chunker for documents with no structural markers."""
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]

    out: list[StructuralChunk] = []
    buffer = ""
    for para in paragraphs:
        if len(buffer) + len(para) + 2 <= TARGET_CHUNK_CHARS:
            buffer = f"{buffer}\n\n{para}" if buffer else para
        else:
            if buffer:
                out.append(StructuralChunk(text=buffer, section_path=None, position=len(out)))
            buffer = para
    if buffer:
        out.append(StructuralChunk(text=buffer, section_path=None, position=len(out)))

    return [c for c in out if len(c.text) >= MIN_PARAGRAPH_CHARS or len(out) == 1]


def _split_long_section(text: str) -> list[str]:
    """Split an oversized section into roughly TARGET_CHUNK_CHARS-sized pieces."""
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    out: list[str] = []
    buffer = ""
    for para in paragraphs:
        if len(buffer) + len(para) + 2 <= TARGET_CHUNK_CHARS:
            buffer = f"{buffer}\n\n{para}" if buffer else para
        else:
            if buffer:
                out.append(buffer)
            buffer = para
    if buffer:
        out.append(buffer)
    return out
