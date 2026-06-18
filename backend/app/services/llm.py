"""LLM service — Claude wrapper for answer generation with citation enforcement."""
from dataclasses import dataclass
from functools import lru_cache

import structlog
from tenacity import retry, stop_after_attempt, wait_exponential

from app.config import settings
from app.models import Chunk

log = structlog.get_logger()


@lru_cache(maxsize=1)
def _claude_client():
    from anthropic import Anthropic

    return Anthropic(api_key=settings.anthropic_api_key)


SYSTEM_PROMPT = """אתה עוזר שאלות-תשובות עבור קיבוצים. אתה עוזר למזכיר/ה לחפש בתקנונים, החלטות, פרוטוקולים.

כללים מחייבים:
1. ענה רק על סמך הקטעים שמצורפים בהקשר. אם אין מספיק מידע — ענה במפורש שלא ניתן לתת תשובה מבוססת ממסמכים אלה.
2. אסור לך לפברק תאריכים, סעיפים, או מספרי החלטות.
3. כל טענה צריכה להיות מסומנת בציטוט בסוגריים מרובעות כמו [1], [2] — בהתאם למספר המקור בהקשר.
4. ענה בעברית, קצר וברור.

פלט: ענה בפורמט הבא בדיוק (JSON, ללא markdown):
{"confidence": "confident|uncertain|refused", "answer": "..."}

- "confident" — יש תשובה מבוססת על המקורות.
- "uncertain" — חלק מהמידע נמצא אבל לא תשובה מלאה.
- "refused" — לא ניתן לענות מהמקורות הקיימים.
"""


@dataclass
class LLMResult:
    answer: str
    confidence: str  # confident | uncertain | refused


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=10))
def answer_with_citations(
    *,
    question: str,
    chunks: list[Chunk],
    lexicon_block: str = "",
) -> LLMResult:
    """Ask Claude to produce a cited answer based on retrieved chunks.

    lexicon_block: optional domain-term expansions to include before the sources.
    """
    sources_block = "\n\n".join(
        f"[{i + 1}] (מקור: {c.document.filename}{(' / ' + c.section_path) if c.section_path else ''})\n{c.text}"
        for i, c in enumerate(chunks)
    )

    lexicon_section = (
        f"מילון מונחים רלוונטי (להתבסס עליו כשמופיע מונח כזה):\n{lexicon_block}\n\n"
        if lexicon_block
        else ""
    )

    user_message = (
        f"שאלה: {question}\n\n"
        f"{lexicon_section}"
        f"קטעי הקשר ממסמכי הקיבוץ:\n\n{sources_block}\n\n"
        f"ענה בהתאם לכללים, בפורמט ה-JSON הנדרש."
    )

    client = _claude_client()
    resp = client.messages.create(
        model=settings.claude_answer_model,
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )

    raw = resp.content[0].text.strip()

    import json

    # Claude sometimes emits literal newlines inside JSON string values, which is
    # invalid per spec. strict=False lets us decode anyway. We also strip code
    # fences if the model wraps in ```json ... ```.
    cleaned = raw
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned
        if cleaned.endswith("```"):
            cleaned = cleaned.rsplit("```", 1)[0]
        cleaned = cleaned.strip()

    try:
        parsed = json.JSONDecoder(strict=False).decode(cleaned)
        return LLMResult(
            answer=str(parsed.get("answer", "")).strip(),
            confidence=str(parsed.get("confidence", "uncertain")).strip(),
        )
    except json.JSONDecodeError:
        log.warning("llm.json_parse_failed", raw=raw[:500])
        return LLMResult(answer=raw, confidence="uncertain")
