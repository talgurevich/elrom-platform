"""Chat triage — decide whether to answer a turn immediately or to clarify
first.

Design rationale
================

The original v0.2 pipeline went straight from question to retrieval to LLM
answer. That's the right shape for sharp, well-formed questions ("מה אומר
סעיף 4.1?"), but a wrong shape for vague or ambiguous ones ("ירשתי בית
בקיבוץ, מה עושים?") — there's no single right answer until we know whether
the user is a member, whether they're asking about שיוך / רישום, etc.

The clarification-first model treats the assistant as a *consultant*: on
vague turns, ask one targeted clarifying question, then answer once the user
confirms. This:

1. Lifts retrieval quality dramatically — a clarified question contains the
   vocabulary that retrieval needs (the same effect you get when a user
   manually says "תקנון השיוך" in turn 2).
2. Reduces wrong-but-confident answers — the system says "let me check" on
   genuinely ambiguous cases instead of charging ahead.
3. Generates training data for the lexicon learner (P6): each clarified
   turn pair is a labeled "lay phrasing → bylaw phrasing" example.

Failure modes to avoid:

- **Over-clarification.** Asking on every question annoys users. Default
  to ANSWER; clarify only on genuine ambiguity.
- **No escape hatch.** Recognize bypass phrases ("ענה ישירות", "פשוט תענה",
  "תן תשובה מהירה") and "yes" replies to a prior clarifying turn.

Returns one ``TriageDecision``:

- ``mode = "answer"`` → caller proceeds to retrieval with ``canonical_query``
  (which folds in conversation context + lexicon expansions — replaces the
  separate query_rewriter step).
- ``mode = "clarify"`` → caller short-circuits the pipeline, saves a Query
  row marked as a clarification turn, and returns ``clarifying_message`` to
  the user.
"""
from dataclasses import dataclass, field
from functools import lru_cache
from uuid import UUID

import structlog
from sqlalchemy import text as sa_text
from sqlalchemy.orm import Session
from tenacity import retry, stop_after_attempt, wait_exponential

from app.config import settings
from app.services.hebrew_text import normalize_hebrew_to_tsquery
from app.services.query_rewriter import PriorTurn, rewrite_query

log = structlog.get_logger()


@dataclass
class TriageDecision:
    mode: str  # "answer" | "clarify"
    canonical_query: str
    clarifying_message: str = ""
    candidate_docs: list[str] = field(default_factory=list)
    reason: str = ""


@lru_cache(maxsize=1)
def _claude_client():
    from anthropic import Anthropic

    return Anthropic(api_key=settings.anthropic_api_key)


_TRIAGE_TOOL = {
    "name": "triage",
    "description": (
        "Decide whether to answer the user's turn immediately or to ask one "
        "clarifying question first. Default to answering — clarify only when "
        "the question is genuinely ambiguous and a brief follow-up would "
        "materially improve retrieval."
    ),
    "input_schema": {
        "type": "object",
        "required": ["mode", "canonical_query", "reason"],
        "properties": {
            "mode": {
                "type": "string",
                "enum": ["answer", "clarify"],
                "description": (
                    "answer: question is precise enough to retrieve and answer. "
                    "clarify: ambiguity that one short follow-up would resolve."
                ),
            },
            "canonical_query": {
                "type": "string",
                "description": (
                    "A single self-contained Hebrew query suitable for semantic "
                    "search over kibbutz bylaws. Fold in context from prior "
                    "turns and any matched lexicon expansions. Even when "
                    "mode=clarify, return your best-guess canonical query so "
                    "the caller can surface candidate documents to the user."
                ),
            },
            "clarifying_message": {
                "type": "string",
                "description": (
                    "Only when mode=clarify. One concise Hebrew question that "
                    "would resolve the ambiguity. Offer concrete options when "
                    "you can ('האם אתה חבר הקיבוץ או יורש בלבד?'). Avoid "
                    "open-ended 'מה כוונתך' phrasing."
                ),
            },
            "candidate_docs": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Document titles from the tenant's library that look "
                    "relevant. Surface to user as 'הכוונה שלך לאחד מאלה?' "
                    "Max 3."
                ),
            },
            "reason": {
                "type": "string",
                "description": "One short Hebrew sentence explaining the decision, for logs.",
            },
        },
    },
}


_TRIAGE_SYSTEM = """אתה ראש-שיחה ליועץ תקנון של קיבוץ. תפקידך לקבל החלטה אחת: האם השאלה הנוכחית של המשתמש ברורה מספיק כדי לאחזר תשובה, או שצריך שאלת הבהרה אחת לפני שעונים.

הכלל הראשון: ברירת המחדל היא לענות, אבל לא בכל מחיר. שיחה שבה המערכת מקפיצה תשובה לא רלוונטית גרועה משיחה שבה היא מבקשת הבהרה אחת קצרה.

🚨 **כלל-על: אל תבקש הבהרה אם ההבהרה לא תשנה את התוצאה.** אם הצצת בקטע המקורות שמסופק לך למטה, ונראה בבירור שהחומר לא מכיל את המידע שהמשתמש מחפש (למשל: שאל "מי חבר בוועדה X" והקטעים לא כוללים רשימת חברי ועדות בכלל) — עדיף לענות (התשובה תהיה סירוב נקי "לא מצאתי") מאשר לשאול שאלת הבהרה שכל תשובה עליה תוביל לאותו סירוב. שאלה שכל ענפיה נופלים לאותו "לא מצאתי" היא רעש טהור מבחינת המשתמש.

מתי כן להבהיר (mode=clarify) — אלה טריגרים חזקים, אל תתעלם מהם:

1. תפקיד המשתמש מהותית לתשובה ולא מצוין (חבר/יורש/לא-חבר/בן ממשיך) — וההבדל בין התשובות גדול.

2. מספר תקנונים שונים יכולים להיות רלוונטיים (תקנון שיוך דירות מול הסדר רישום מול תקנון ראשי) ולא ניתן להחליט בלעדי המשתמש.

3. כינוי גוף או מילת רמיזה ("הם", "זה", "אלה", "ההוא", "הסעיף הזה", "הדבר הזה") + התור הקודם של המערכת הזכיר *שתי ישויות שונות או יותר* שהמילה יכולה להפנות אליהן. דוגמה: התשובה הקודמת דיברה על "רווחים, יחידות השתתפות, מענקים" — והמשתמש אומר "אבל הם מחולקים". "הם" עמום לחלוטין — הבהר לפני שתענה. *זה לא רק "אין הקשר" — זה גם "יש כמה הקשרים אפשריים בו זמנית".*

4. השאלה מערבת שני נושאים ולא ברור על איזה המשתמש שואל.

5. **חוסר הסכמה עם התור הקודם, ללא פירוט.** אם המשתמש פותח ב"אבל…", "אבל להבנתי…", "זה לא נכון", "אני לא בטוח", "לא הבנתי", או מבטא ספק — והוא לא מציין על איזה נקודה ספציפית מהתשובה הקודמת הוא חולק — *תמיד הבהר*. אל תניח מה הוא חולק עליו ואל תיכנס לפירוט חדש שעלול להחמיא לוויכוח השגוי. שאל: "על איזו נקודה בתשובה הקודמת אתה חולק?" או "אילו רווחים — היחידות, המענקים, או חלוקת ההון?"

6. **תור קצר אחרי תשובה ארוכה.** אם השאלה הנוכחית קצרה (פחות מ-10 מילים) והתשובה הקודמת של המערכת כיסתה *שלושה נושאים או יותר*, וברור שהמשתמש מתייחס לאחד מהם בלי לציין איזה — הבהר. זה כמעט תמיד יישא פרי.

מתי לעולם לא להבהיר:
- כשהמשתמש ביקש מפורשות תשובה ישירה ("ענה ישירות", "פשוט תענה", "תן תשובה מהירה", "תשובה קצרה").
- כשבתור הקודם של המערכת הופיעה שאלת הבהרה והמשתמש ענה בחיוב ("כן", "נכון", "בדיוק", "אכן") או בחר אחת מהאפשרויות שהוצעו.
- 🚨 **כשהתור הקודם של המערכת היה שאלת הבהרה עם 2+ צירים, והתור הנוכחי של המשתמש עונה על חלק מהצירים — אל תשאל שוב על הצירים שנענו.** דוגמה: המערכת שאלה "האם הכוונה להנהלה כלכלית או לוועדת ביקורת כלכלית? ויו״ר בלבד או כל החברים?" — והמשתמש עונה "אני שואל על הנהלה כלכלית". *ציר הגוף נסגר.* אל תשאל אותה שאלה שוב. אם הציר השני (יו״ר/כל החברים) עדיין קריטי — ענה עם ההנחה הסבירה ("כל החברים") במקום לשאול שוב, אלא אם ההנחה שגויה תוביל לתשובה שגויה מהותית.
- כשהשאלה כבר מכילה את המונח המקצועי הנכון (שיוך/רישום/תקנון X) או מציינת בבירור את הסעיף/הישות הספציפיים.
- 🚨 **שאלות רשימתיות** ("מי חבר ב-X", "מי מכהן ב-X", "אילו X קיימים") — ברירת המחדל הבלתי מפורשת היא **הרשימה המלאה**, לא ראש בלבד. אל תשאל "יו״ר בלבד או כל החברים?" — ההנחה הסבירה היא כל החברים. הבהר רק אם התור הקודם עסק ספציפית באדם/תפקיד יחיד ואז המשתמש שואל "מי חבר בוועדה?" (אז ההקשר יוצר עמימות אמיתית).

ניסוח שאלת ההבהרה (כשהיא נדרשת):
- שאלה אחת קצרה. לא רשימה.
- הצע אפשרויות ספציפיות במקום "מה כוונתך?". כשאתה רואה ש"הם"/"זה" עמום — שאל ישירות על הישויות שעלו בתור הקודם של המערכת: "אילו רווחים — היחידות, המענקים, או חלוקת הון האגודה?".
- היעזר ברשימת המסמכים — "הכוונה שלך לתקנון שיוך דירות או להסדר רישום הדירות?".
- מקסימום שני משפטים.

על השאילתה הקנונית (canonical_query):
- שאילתה אחת בעברית, עצמאית, שתיתן רטריבר מצוין על תקנונים.
- שלב מונחים מהמילון אם הוצגו לך — אבל בלי לאבד את הלקסיקון של המשתמש המקורי.
- כשיש תורים קודמים — שלב את ההקשר. אל תחזור על הציטוט המלא.
- גם כאשר mode=clarify, החזר ניחוש סביר — הוא משמש להצגת מסמכים מועמדים."""


def _format_prior_turns(prior: list[PriorTurn]) -> str:
    if not prior:
        return "(אין תורים קודמים — זו הפנייה הראשונה בשיחה.)"
    lines = []
    for t in prior[-6:]:  # last 6 turns is plenty of context
        speaker = "משתמש" if t.role == "user" else "מערכת"
        lines.append(f"{speaker}: {t.text.strip()}")
    return "\n".join(lines)


def _format_doc_index(doc_titles: list[str]) -> str:
    if not doc_titles:
        return "(אין רשימת מסמכים זמינה.)"
    return "\n".join(f"- {t}" for t in doc_titles)


def _format_lexicon(expansions: list[tuple[str, str]]) -> str:
    if not expansions:
        return "(אין התאמות מילון.)"
    return "\n".join(f'- "{term}" → {exp}' for term, exp in expansions)


def _format_snippets(snippets: list[str]) -> str:
    """Peek at the top FTS chunks so triage can judge whether the answer
    plausibly exists in the corpus. Not a substitute for full retrieval —
    it's just a "does anything look related?" signal."""
    if not snippets:
        return "(לא נמצאו קטעים רלוונטיים — סימן שהתשובה כנראה לא במאגר.)"
    return "\n---\n".join(s.strip() for s in snippets if s and s.strip())


def peek_snippets(
    db: Session, *, tenant_id: UUID, question: str, limit: int = 2, max_chars: int = 400
) -> list[str]:
    """Cheap tsvector-only peek: top-N chunk excerpts matching `question`.

    Runs on the raw question (no rewrite) so it's fast and doesn't need
    the canonical query that triage is deciding whether to produce.
    Never raises — retrieval failure returns []."""
    q = normalize_hebrew_to_tsquery(question)
    if not q:
        return []
    try:
        rows = db.execute(
            sa_text(
                """
                SELECT text
                FROM chunks
                WHERE tenant_id = :tid
                  AND text_search @@ to_tsquery('simple', :q)
                ORDER BY ts_rank(text_search, to_tsquery('simple', :q)) DESC
                LIMIT :lim
                """
            ),
            {"tid": str(tenant_id), "q": q, "lim": limit},
        ).all()
    except Exception as e:  # noqa: BLE001
        log.warning("chat_triage.peek_failed", err=str(e))
        return []
    return [(r[0] or "")[:max_chars] for r in rows if r[0]]


@retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=1, min=1, max=4))
def _call_triage(*, user_message: str) -> dict:
    client = _claude_client()
    resp = client.messages.create(
        model=settings.claude_extract_model,
        max_tokens=600,
        system=_TRIAGE_SYSTEM,
        tools=[_TRIAGE_TOOL],
        tool_choice={"type": "tool", "name": "triage"},
        messages=[{"role": "user", "content": user_message}],
    )
    for block in resp.content:
        if getattr(block, "type", None) == "tool_use" and getattr(block, "name", "") == "triage":
            inp = block.input  # type: ignore[attr-defined]
            if isinstance(inp, dict):
                return inp
    return {}


def triage_turn(
    *,
    question: str,
    prior_turns: list[PriorTurn] | None = None,
    lexicon_expansions: list[tuple[str, str]] | None = None,
    doc_titles: list[str] | None = None,
    doc_snippets: list[str] | None = None,
) -> TriageDecision:
    """Decide answer-vs-clarify and produce the canonical query.

    `doc_snippets` (top-N FTS excerpts from `peek_snippets`) let the
    triage model tell whether the answer plausibly exists in the corpus.
    Without them the model over-clarifies on questions whose answer
    isn't in the docs anyway — every clarification prong ends in the
    same "לא מצאתי" refusal.

    Failure modes are absorbed gracefully: any LLM failure falls back to
    ``mode=answer`` with the mechanical canonical query from the rewriter,
    matching pre-triage behavior. Better to answer than to stall.
    """
    prior = prior_turns or []
    lexicon = lexicon_expansions or []
    titles = doc_titles or []
    snippets = doc_snippets or []

    user_message = (
        f"שיחה עד כה:\n{_format_prior_turns(prior)}\n\n"
        f"שאלה נוכחית של המשתמש:\n{question.strip()}\n\n"
        f"מסמכי הקיבוץ הזמינים (כותרות):\n{_format_doc_index(titles)}\n\n"
        f"קטעים מהמאגר שנמצאו רלוונטיים לשאלה (peek — לא רטריבל מלא):\n"
        f"{_format_snippets(snippets)}\n\n"
        f"מונחי מילון שזוהו בשאלה:\n{_format_lexicon(lexicon)}\n\n"
        "הפעל את הכלי `triage` עם החלטתך."
    )

    try:
        decision = _call_triage(user_message=user_message)
        if decision and decision.get("mode") in ("answer", "clarify"):
            mode = decision["mode"]
            canonical = (decision.get("canonical_query") or "").strip() or question.strip()
            log.info(
                "chat_triage.decision",
                mode=mode,
                reason=decision.get("reason", "")[:200],
                prior_turns=len(prior),
                lexicon_hits=len(lexicon),
            )
            return TriageDecision(
                mode=mode,
                canonical_query=canonical,
                clarifying_message=(decision.get("clarifying_message") or "").strip(),
                candidate_docs=[
                    str(d).strip() for d in (decision.get("candidate_docs") or []) if str(d).strip()
                ][:3],
                reason=(decision.get("reason") or "").strip(),
            )
        log.warning("chat_triage.malformed", raw=str(decision)[:200])
    except Exception as e:
        log.warning("chat_triage.failed", err=str(e))

    # Fallback: behave like the pre-triage pipeline. Answer with the
    # mechanical-concat canonical query.
    canonical = rewrite_query(
        question=question, prior_turns=prior, lexicon_expansions=lexicon
    )
    return TriageDecision(
        mode="answer",
        canonical_query=canonical,
        reason="triage_fallback",
    )
