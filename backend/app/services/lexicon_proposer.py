"""Turn a raw candidate term (harvested from any signal) into a structured
pending Lexicon row.

Inputs from a collector:
  - candidate_term: the surface phrase we noticed (quoted phrase, acronym,
    reviewer-added word, corpus-mined term, etc.)
  - context_snippet: the sentence/answer chunk it appeared in, so the LLM
    can guess entry_type and expansion
  - signal_type: which harvester saw it (used only for evidence/logging)

Output: a dict shaped like a Lexicon row (short_gloss, answerer_expansion,
entry_type, surface_forms, confidence). The caller decides whether to
insert as pending or drop.

Model: `settings.claude_extract_model` (Haiku by default). One call per
candidate — batching not worth it for the volumes we expect.
"""
from __future__ import annotations

from functools import lru_cache

import structlog

from app.config import settings
from app.services.hebrew_prefixes import expand_hebrew_prefixes

log = structlog.get_logger()


_PROPOSER_TOOL = {
    "name": "propose_entry",
    "description": (
        "Given a candidate term that showed up in an org's answer/question, "
        "produce a structured lexicon entry OR indicate that this candidate "
        "isn't worth adding to the lexicon."
    ),
    "input_schema": {
        "type": "object",
        "required": ["worth_adding"],
        "properties": {
            "worth_adding": {
                "type": "boolean",
                "description": (
                    "false when the candidate is generic (common Hebrew "
                    "word, non-domain), a person name, a place name that "
                    "isn't org-internal, or otherwise not a term a "
                    "reviewer would want in a bylaw glossary."
                ),
            },
            "canonical_term": {
                "type": "string",
                "description": (
                    "The clean canonical form of the term (strip prefix "
                    "letters like ה/ל/ב if present, use singular). Only "
                    "provide when worth_adding=true."
                ),
            },
            "short_gloss": {
                "type": "string",
                "description": (
                    "One-sentence Hebrew tooltip for a reader hovering over "
                    "the term in an answer. Max ~120 chars."
                ),
            },
            "answerer_expansion": {
                "type": "string",
                "description": (
                    "Guidance for the answerer LLM when this term appears "
                    "in a question: what it means, which document(s) "
                    "usually address it, any nuance. 1-3 sentences."
                ),
            },
            "entry_type": {
                "type": "string",
                "enum": ["definition", "pointer", "rule"],
                "description": (
                    "definition = 'here's what X means'; "
                    "pointer = 'when X comes up, look at document Y'; "
                    "rule = 'when X appears, apply this policy'."
                ),
            },
            "confidence": {
                "type": "number",
                "description": "0.0-1.0 estimate that this is a genuine term worth keeping.",
            },
        },
    },
}

_PROPOSER_SYSTEM = """אתה עוזר לבנות מילון מונחים פנים-קיבוצי לצורך צ'אט תקנון. תקבל מונח מועמד ואת ההקשר שבו הופיע. שקול:
- האם זה מונח פנים-ארגוני / משפטי / תקנוני שמנוע חיפוש כללי לא יזהה? (worth_adding=true)
- אם כן — נסח short_gloss קצר (משפט אחד) למשתמש קצה שמרחף מעל המונח בתשובה, ו-answerer_expansion (1-3 משפטים) שיוזרק להקשר של ה-LLM כשהמונח יופיע בשאלה עתידית.
- קבע entry_type: definition (הגדרה), pointer (הפניה למסמך), rule (כלל התנהגות).

אל תוסיף מונחים גנריים (פעלים יומיומיים, שמות אנשים, שמות מקומות שאינם פנים-ארגוניים). עדיף worth_adding=false על פני רשומה חלשה."""


@lru_cache(maxsize=1)
def _claude_client():
    from anthropic import Anthropic

    return Anthropic(api_key=settings.anthropic_api_key)


def propose_entry(
    *, candidate_term: str, context_snippet: str, signal_type: str
) -> dict | None:
    """Return a dict ready to insert as a pending Lexicon row, or None if
    the proposer said "not worth adding" (or the LLM call failed)."""
    candidate_term = (candidate_term or "").strip()
    if not candidate_term:
        return None

    client = _claude_client()
    user_message = (
        f"מונח מועמד: {candidate_term}\n\n"
        f"מקור האיתות: {signal_type}\n\n"
        f"הקשר שבו הופיע (קטע קצר מתוך תשובה/שאלה):\n{context_snippet[:800]}\n\n"
        "החזר קריאה לכלי propose_entry."
    )
    try:
        resp = client.messages.create(
            model=settings.claude_extract_model,
            max_tokens=500,
            system=_PROPOSER_SYSTEM,
            tools=[_PROPOSER_TOOL],
            tool_choice={"type": "tool", "name": "propose_entry"},
            messages=[{"role": "user", "content": user_message}],
        )
    except Exception as e:  # noqa: BLE001
        log.warning("lexicon_proposer.failed", term=candidate_term, err=str(e))
        return None

    for block in resp.content:
        if getattr(block, "type", None) != "tool_use":
            continue
        inp = getattr(block, "input", None)
        if not isinstance(inp, dict):
            continue
        if not inp.get("worth_adding"):
            return None
        canonical = (inp.get("canonical_term") or candidate_term).strip()
        return {
            "term": canonical,
            "surface_forms": expand_hebrew_prefixes(canonical),
            "short_gloss": (inp.get("short_gloss") or "").strip(),
            "answerer_expansion": (inp.get("answerer_expansion") or "").strip(),
            "entry_type": inp.get("entry_type") or "definition",
            "confidence": float(inp.get("confidence") or 0.5),
        }
    return None
