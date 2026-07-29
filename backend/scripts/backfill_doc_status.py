"""Backfill documents.doc_status (lifecycle maturity) for existing docs.

Two passes per document with doc_status IS NULL:

  1. Filename heuristics (free): "הצעה…" → proposal, "טיוט…" → draft,
     "סיכום דיון…" → discussion.
  2. Mini LLM pass (Haiku) on title + summary + the first ~2000 chars —
     the same rules as the ingest classifier's doc_status field.

Docs the LLM can't classify stay NULL (treated as adopted-equivalent by
retrieval: no demotion). Idempotent — only NULL rows are touched, so
re-running converges and never overwrites a human/classifier value.

Run from the backend directory:

    .venv/bin/python -m scripts.backfill_doc_status            # apply
    .venv/bin/python -m scripts.backfill_doc_status --dry-run  # heuristics report only
"""
import argparse
import json
import re
import sys

from sqlalchemy.orm import Session

from app.config import settings
from app.db import SessionLocal
from app.models import Chunk, Document
from app.routes.documents import ALLOWED_DOC_STATUS, doc_status_from_filename

MINI_PROMPT = """סווג את מעמד המסמך (עד כמה הוא מחייב) לפי הכללים:
- proposal — הצעה שהוגשה לדיון/אישור וטרם אושרה ("הצעה ל...", "מוגש לאישור").
- draft — טיוטה בעבודה ("טיוטה", גרסה לא סופית).
- discussion — סיכום דיון בתהליך קבלת החלטות, בלי הכרעה אופרטיבית.
- background — מסמך מידע/רקע: דוח (כספי, ביקורת, אקטוארי), סקירה, נייר עמדה, מצגת, נתונים, חוות דעת. מיידע — לא קובע כלל ולא מציע כלל.
- invitation — הזמנה/זימון לישיבה, אסיפה או קלפי, כולל סדר יום. מעיד על מה שעמד על סדר היום, לא על מה שהוחלט.
- adopted — מסמך מחייב: תקנון מאושר, החלטה שהתקבלה, פרוטוקול חתום, נוהל בתוקף, תוצאות קלפי. ברירת המחדל כשאין סימני הצעה/טיוטה/רקע/הזמנה.
שם קובץ שמתחיל ב"הצעה" הוא כמעט תמיד proposal. אם המסמך קובע כללים/זכויות/חובות — adopted; אם הוא רק מדווח או מציג מידע — background, גם אם רשמי וחתום.

החזר JSON בלבד: {"doc_status": "proposal|draft|discussion|background|invitation|adopted"}"""


def _classify_llm(client, *, filename: str, summary: str | None, body: str) -> str | None:
    user = f"שם קובץ: {filename}\n"
    if summary:
        user += f"תקציר: {summary}\n"
    user += f"\nתחילת המסמך:\n{body[:2000]}"
    resp = client.messages.create(
        model=settings.claude_extract_model,
        max_tokens=50,
        temperature=0,
        timeout=60.0,
        system=MINI_PROMPT,
        messages=[{"role": "user", "content": user}],
    )
    raw = resp.content[0].text.strip()
    # The model fences the JSON and appends a rationale despite the
    # JSON-only instruction — pull the first {...} object out instead of
    # parsing the whole reply.
    m = re.search(r"\{.*?\}", raw, re.S)
    if not m:
        return None
    try:
        v = str(json.loads(m.group(0)).get("doc_status") or "").strip()
    except (json.JSONDecodeError, AttributeError):
        return None
    return v if v in ALLOWED_DOC_STATUS else None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Heuristics-only report, no LLM, no writes")
    parser.add_argument(
        "--reclassify-adopted",
        action="store_true",
        help=(
            "Re-run the classifier over docs currently marked 'adopted' and "
            "apply ONLY adopted→background / adopted→invitation flips (used "
            "when new status values are introduced; never demotes a rule to "
            "proposal/draft)."
        ),
    )
    args = parser.parse_args()

    from anthropic import Anthropic

    client = None if args.dry_run else Anthropic(api_key=settings.anthropic_api_key)

    db: Session = SessionLocal()
    try:
        if args.reclassify_adopted:
            docs = (
                db.query(Document)
                .filter(Document.doc_status == "adopted")
                .order_by(Document.ingested_at)
                .all()
            )
            print(f"{len(docs)} adopted docs to re-evaluate")
        else:
            docs = db.query(Document).filter(Document.doc_status.is_(None)).order_by(Document.ingested_at).all()
            print(f"{len(docs)} docs without doc_status")
        counts = {
            "proposal": 0, "draft": 0, "discussion": 0, "background": 0,
            "invitation": 0, "adopted": 0, "unclassified": 0,
        }
        for i, doc in enumerate(docs, 1):
            status = doc_status_from_filename(doc.filename)
            via = "filename"
            if status is None and not args.dry_run:
                body = "\n\n".join(
                    c.text
                    for c in db.query(Chunk)
                    .filter(Chunk.document_id == doc.id)
                    .order_by(Chunk.position)
                    .limit(4)
                    .all()
                    if c.text
                )
                summary = (doc.doc_metadata or {}).get("summary")
                try:
                    status = _classify_llm(client, filename=doc.filename, summary=summary, body=body)
                    via = "llm"
                except Exception as e:
                    print(f"  [{i}/{len(docs)}] ERROR {doc.filename[:50]}  {str(e)[:100]}")
                    continue
            if args.reclassify_adopted and status not in ("background", "invitation"):
                # Conservative gate: only informational flips apply here;
                # anything else keeps its adopted status.
                status = None
            counts[status or "unclassified"] += 1
            if status and not args.dry_run:
                doc.doc_status = status
                db.commit()
            if status and status != "adopted":
                print(f"  [{i}/{len(docs)}] {status:10s} ({via})  {doc.filename[:60]}")
        print(f"\nsummary: {counts}")
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
