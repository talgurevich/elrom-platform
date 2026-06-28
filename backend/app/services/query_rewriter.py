"""Query rewriter — turn a chat-turn user message into a single canonical query
that retrieval can embed and search against.

Why this exists:
  - When a user refines across turns ("ירשתי בית" → "אני יורש של חבר שנפטר, מה
    קורה עם הדירה?") the *intent* is cumulative but the current-turn text is
    fragmentary. Embedding just the latest turn loses context. Naive
    concatenation of all turns dilutes the vector. We ask Claude Haiku to
    fuse the conversation into one sharp standalone question.
  - When the lexicon matches a term in the current turn ("ירושה"), we want
    the expansion ("שיוך, רישום דירות, מקבל הזכות, ...") to enter the
    retrieval vocabulary — *not just* the LLM context. We pass matched
    lexicon entries to the rewriter so it can weave them into the canonical
    form naturally.

This is the bridge between P3 (conversation-aware) and P4 (lexicon-into-
embedding): a single rewrite step that does both.

Output is plain text — the canonical question. Apply ``normalize_hebrew`` on
top of it for the BM25 path.
"""
from dataclasses import dataclass
from functools import lru_cache

import structlog
from tenacity import retry, stop_after_attempt, wait_exponential

from app.config import settings

log = structlog.get_logger()


@dataclass
class PriorTurn:
    role: str  # "user" | "assistant"
    text: str


@lru_cache(maxsize=1)
def _claude_client():
    from anthropic import Anthropic

    return Anthropic(api_key=settings.anthropic_api_key)


_REWRITER_SYSTEM = (
    "אתה משכתב שאילתות לחיפוש סמנטי בתוך תקנוני קיבוץ בעברית. "
    "מטרתך: לקבל שאלת המשך של משתמש בשיחה, אופציונלית עם תורות קודמים ועם "
    "מילון מונחים פנים-קיבוצי, ולהפיק שאילתה אחת קצרה ועצמאית שיש בה את "
    "כל ההקשר הדרוש כדי לאחזר את הסעיפים הרלוונטיים — בלי לוותר על מונחים "
    "מקצועיים שעולים במילון. אל תענה על השאלה. אל תוסיף הסברים. החזר רק את "
    "השאילתה המשוכתבת בשורה אחת."
)


def _format_turns(prior: list[PriorTurn]) -> str:
    if not prior:
        return ""
    lines = []
    for t in prior:
        speaker = "משתמש" if t.role == "user" else "מערכת"
        lines.append(f"{speaker}: {t.text.strip()}")
    return "\n".join(lines)


def _format_lexicon(expansions: list[tuple[str, str]]) -> str:
    if not expansions:
        return ""
    return "\n".join(f'- "{term}" → {exp}' for term, exp in expansions)


def _fallback_canonical(
    *, question: str, prior: list[PriorTurn], lexicon: list[tuple[str, str]]
) -> str:
    """Used when the LLM call fails or is skipped. Mechanical concatenation —
    not as sharp as the LLM rewrite but still gives retrieval more signal than
    the raw turn alone."""
    parts: list[str] = []
    # Include the most recent prior user turn for context (one is enough —
    # more dilutes the vector).
    last_user_prior = next(
        (t for t in reversed(prior) if t.role == "user"), None
    )
    if last_user_prior is not None:
        parts.append(last_user_prior.text.strip())
    parts.append(question.strip())
    for _, expansion in lexicon:
        if expansion:
            parts.append(expansion.strip())
    return " ".join(p for p in parts if p)


@retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=1, min=1, max=4))
def _call_claude(*, system: str, user: str) -> str:
    client = _claude_client()
    resp = client.messages.create(
        model=settings.claude_extract_model,
        max_tokens=300,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    for block in resp.content:
        if getattr(block, "type", None) == "text":
            return block.text.strip()
    return ""


def rewrite_query(
    *,
    question: str,
    prior_turns: list[PriorTurn] | None = None,
    lexicon_expansions: list[tuple[str, str]] | None = None,
) -> str:
    """Return a canonical standalone query for retrieval.

    Skips the LLM call entirely (returns the original) when there's no
    conversation context AND no lexicon hit — there's nothing to rewrite.
    Otherwise asks Haiku to fuse turns + lexicon into one query. On any LLM
    failure, falls back to mechanical concatenation.
    """
    prior = prior_turns or []
    lexicon = lexicon_expansions or []
    if not prior and not lexicon:
        return question.strip()

    turns_block = _format_turns(prior)
    lex_block = _format_lexicon(lexicon)

    sections = []
    if turns_block:
        sections.append(f"שיחה עד כה:\n{turns_block}")
    if lex_block:
        sections.append(f"מונחים פנים-קיבוציים שזוהו בשאלה:\n{lex_block}")
    sections.append(f"שאלה נוכחית של המשתמש: {question.strip()}")
    sections.append("החזר שאילתה אחת קצרה ועצמאית לחיפוש (בלי תשובה).")
    user_message = "\n\n".join(sections)

    try:
        canonical = _call_claude(system=_REWRITER_SYSTEM, user=user_message)
        if canonical:
            log.info(
                "query_rewriter.ok",
                original=question[:120],
                canonical=canonical[:200],
                prior_turns=len(prior),
                lexicon_hits=len(lexicon),
            )
            return canonical
    except Exception as e:
        log.warning("query_rewriter.failed", err=str(e))

    return _fallback_canonical(question=question, prior=prior, lexicon=lexicon)
