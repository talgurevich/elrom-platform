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
    # For chunks that start with a decision marker: "terminal" (הוחלט:
    # substantive outcome) vs "escalation" (הוחלט להעביר לאסיפה / לקלפי —
    # not the final decision on the substance). None for non-decision chunks.
    # Drives the provenance chain rules in the answerer prompt.
    decision_type: str | None = None


# Escalation markers — the chunk is a decision to *escalate*, not a decision
# on the substance. When seen, the answerer should look for the outcome at
# the higher forum, not treat this as the terminal decision.
_ESCALATION_PHRASES = (
    "להעביר לאסיפה",
    "להעביר לקלפי",
    "להביא לאסיפה",
    "להביא בפני האסיפה",
    "יובא לאישור האסיפה",
    "יובא לאישור אסיפה",
    "יועלה להצבעה",
    "יעלה להצבעה",
    "יובא לקלפי",
    "יועבר לקלפי",
    "להביא בפני חברי הקיבוץ",
)


def _classify_decision(text: str) -> str | None:
    """Return 'terminal', 'escalation', or None for a chunk. Only fires
    when the chunk starts with a decision-marker (הוחלט / החלטה / החלטה N).

    Only the *leading* decision's outcome classifies the chunk — we scan
    for escalation phrases up to the next hard boundary (paragraph break,
    or another "הוחלט"/"החלטה" line). Otherwise a chunk containing
    "הוחלט: X" followed by an unrelated "הוחלט להעביר לאסיפה" would
    misclassify as escalation."""
    if not text:
        return None
    head = text.lstrip()
    if not (head.startswith("הוחלט") or head.startswith("החלטה")):
        return None

    # Trim to the leading decision's scope: stop at first blank line, or
    # at the next הוחלט/החלטה line.
    scope_end = len(head)
    for i, line in enumerate(head.split("\n")):
        if i == 0:
            continue
        stripped = line.strip()
        if not stripped:
            # Blank line ends the current decision.
            scope_end = sum(len(l) + 1 for l in head.split("\n")[:i])
            break
        if stripped.startswith(("הוחלט", "החלטה")):
            scope_end = sum(len(l) + 1 for l in head.split("\n")[:i])
            break
    leading = head[:scope_end]

    for phrase in _ESCALATION_PHRASES:
        if phrase in leading:
            return "escalation"
    return "terminal"


def build_contextual_input(
    *,
    text: str,
    section_path: str | None,
    document_title: str | None,
) -> str:
    """Compose the string we actually send to the embedding model.

    Why prepend metadata: Cohere only sees the chunk text by default, so a chunk
    of legal prose has no signal about which document or section it came from.
    Queries that reference the section by name ("מה אומר סעיף 4.1 בתקנון פנסיה")
    then can't match. Prepending a short header binds each chunk to its
    document + section in vector space, which empirically lifts recall a lot on
    structured corpora.

    The chunk text stored in the DB is unchanged — this is only the embedding
    input. Citations and the UI keep showing the clean text.
    """
    header_parts: list[str] = []
    if document_title:
        header_parts.append(document_title.strip())
    if section_path:
        header_parts.append(section_path.strip())
    if not header_parts:
        return text
    header = " — ".join(header_parts)
    return f"{header}\n\n{text}"


# Matches a line beginning with a structural marker. Group 1 captures the
# marker label (e.g. "סעיף 4א").
SECTION_RE = re.compile(
    r"^("
    r"סעיף\s+\d[\dא-ת./\-]*"                             # סעיף 4, סעיף 4א, סעיף 4.2
    r"|פרק\s+(?:[א-ת]{1,3}|\d[\dא-ת./\-]*)"              # פרק א, פרק 1
    r"|נוהל\s+(?:[א-ת]{1,3}|\d[\dא-ת./\-]*)"             # נוהל א, נוהל 1
    r"|החלטה\s+(?:מספר\s+)?\d[\dא-ת./\-]*"               # החלטה 5, החלטה מספר 5/2024
    r"|החלטה(?=\s*[:.])"                                 # bare "החלטה:" — common in unstructured protocols
    r"|הוחלט(?:\s+פה\s+אחד|\s+ברוב|\s+כי|\s+ש)?(?=\s*(?:[:.]|ל[א-ת]))"
    # ↑ "הוחלט:", "הוחלט פה אחד:", "הוחלט ברוב:", plus infinitive forms
    # like "הוחלט להעביר לאסיפה" / "הוחלט לאשר" / "הוחלט למנות"
    # (colon isn't required — verb-prefix "ל" + Hebrew letter is enough).
    r"|פרוטוקול\s+(?:מספר\s+)?\d[\dא-ת./\-]*"            # פרוטוקול 12
    r"|\d+(?:\.\d+){1,3}(?=\s+[א-ת])"                    # dotted decimal: 1.1, 2.13, 3.4.2 — only if followed by Hebrew text
    r"|\d+\.(?=\s+[א-ת])"                                # top-level numbered: 1.  כותרת
    r")",
    re.MULTILINE,
)


# Extract the canonical section number from a section_path. Section paths
# look like "סעיף 44", "סעיף 45.ב", "45.ב", "פרק א", "החלטה 5".
# The amendment graph uses **section numbers only** — chapter/decision headers
# aren't amendable units. Returns e.g. "44", "45.ב", or None for non-section paths.
_CANONICAL_SECTION_RE = re.compile(r"(?:סעיף\s+)?(\d+(?:\.(?:\d+|[א-ת]))*)")


def canonical_section_ref(section_path: str | None) -> str | None:
    if not section_path:
        return None
    sp = section_path.strip()
    # Chapter / decision / procedure / protocol headers are not amendable
    # targets — the amendment graph only tracks סעיף-level edits.
    if sp.startswith(("פרק", "החלטה", "הוחלט", "נוהל", "פרוטוקול")):
        return None
    m = _CANONICAL_SECTION_RE.match(sp)
    return m.group(1) if m else None


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
                StructuralChunk(
                    text=section_text,
                    section_path=section_path,
                    position=len(chunks),
                    decision_type=_classify_decision(section_text),
                )
            )
        else:
            for sub_text in _split_long_section(section_text):
                chunks.append(
                    StructuralChunk(
                        text=sub_text,
                        section_path=section_path,
                        position=len(chunks),
                        decision_type=_classify_decision(sub_text),
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
