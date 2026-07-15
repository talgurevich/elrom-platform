"""Seed the golden question set for a tenant from docs/eval/golden-baseline.md.

Bulk-creates all 30 baseline goldens (5 buckets: single-hop bylaw, decision
lookup, multi-hop, procedural, guardrail) without going through the admin UI
one at a time.

    .venv/bin/python -m scripts.seed_goldens --tenant "אל-רום"
    .venv/bin/python -m scripts.seed_goldens --tenant-id <uuid> --dry-run
    .venv/bin/python -m scripts.seed_goldens --tenant "אל-רום" --replace

Idempotent by default: skips any golden whose question text already exists
for the tenant. --replace deletes all existing goldens for the tenant first
(destructive — confirms before running).

Filenames in the seed set are the placeholders from golden-baseline.md and
should be updated to match real corpus filenames after seeding. Guardrail
questions (G27–G30) intentionally have no expected docs/keywords — the
correct behavior is `confidence == "refused"`.
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import GoldenQuestion
from app.services.identity import identity_service


@dataclass(frozen=True)
class GoldenSeed:
    question: str
    expected_doc_filenames: list[str] | None
    expected_keywords: list[str] | None
    expected_answer: str | None
    notes: str


# Source: docs/eval/golden-baseline.md (30 goldens across 5 buckets).
# Filenames are placeholders — update to real corpus names after seeding.
GOLDENS: list[GoldenSeed] = [
    # ─── Bucket 1: Single-hop bylaw lookup (10) ─────────────────────────
    GoldenSeed(
        question="מה קורה אם חבר לא שילם דמי חבר במשך שנתיים?",
        expected_doc_filenames=["takanon-elrom-2024.pdf"],
        expected_keywords=["12(ב)", "שימוע", "דמי חבר"],
        expected_answer=(
            "סעיף 12(ב) קובע כי חבר שאינו משלם דמי חבר במשך תקופה העולה על "
            "שנה יוזמן לשימוע, ולאחר מכן רשאי הועד להחליט על השעיה או "
            "הפסקת חברות."
        ),
        notes="G1. Canonical hero-example question. Must always pass. [bucket: single-hop]",
    ),
    GoldenSeed(
        question="מי רשאי להיות חבר בקיבוץ?",
        expected_doc_filenames=["takanon-elrom-2024.pdf"],
        expected_keywords=["חבר", "קבלה", "אסיפה"],
        expected_answer=(
            "לפי סעיף הקבלה בתקנון, זכאי להתקבל כחבר מי שהוא בן קיבוץ או "
            "שהתקבל באסיפה כללית ברוב הנדרש, בכפוף לתקופת ניסיון."
        ),
        notes="G2. Basic bylaw retrieval on a well-defined section. [bucket: single-hop]",
    ),
    GoldenSeed(
        question="באיזה גיל בן ממשיך זכאי להירשם כחבר?",
        expected_doc_filenames=["takanon-elrom-2024.pdf"],
        expected_keywords=["בן ממשיך", "18"],
        expected_answer="בן ממשיך רשאי להירשם לחברות מגיל 18 בכפוף לתנאי התקנון.",
        notes="G3. Number-specific — precision test for extraction. [bucket: single-hop]",
    ),
    GoldenSeed(
        question="מה תנאי הקבלה לחברות?",
        expected_doc_filenames=["takanon-elrom-2024.pdf"],
        expected_keywords=["תקופת ניסיון", "אסיפה", "רוב"],
        expected_answer=(
            "תנאי הקבלה כוללים הגשת בקשה, מעבר תקופת ניסיון, ואישור באסיפה "
            "כללית ברוב הנדרש בתקנון."
        ),
        notes="G4. Broader phrasing of G2 — tests robustness to rephrasing. [bucket: single-hop]",
    ),
    GoldenSeed(
        question="מי הגורם המוסמך לאשר פרישת חבר?",
        expected_doc_filenames=["takanon-elrom-2024.pdf"],
        expected_keywords=["ועד הנהלה", "פרישה"],
        expected_answer=(
            "לפי התקנון, ועד ההנהלה מוסמך לאשר בקשת פרישה בכפוף להסדרת "
            "החובות של החבר הפורש."
        ),
        notes="G5. Tests role/authority extraction. [bucket: single-hop]",
    ),
    GoldenSeed(
        question="אילו זכויות יש לחבר בעל וותק של מעל 20 שנה?",
        expected_doc_filenames=["takanon-elrom-2024.pdf", "takanot-vatikim-2022.pdf"],
        expected_keywords=["וותק", "20", "דיור"],
        expected_answer=(
            "חבר בעל וותק מעל 20 שנה זכאי לתוספות דיור והטבות סוציאליות "
            "בהתאם לתקנון הוותיקים."
        ),
        notes="G6. Two-doc retrieval — tests recall breadth. [bucket: single-hop]",
    ),
    GoldenSeed(
        question="מה נדרש כדי לקיים אסיפה כללית תקינה?",
        expected_doc_filenames=["takanon-elrom-2024.pdf"],
        expected_keywords=["מניין", "הודעה", "אסיפה"],
        expected_answer=(
            "אסיפה כללית תקינה דורשת הודעה מוקדמת של 7 ימים לפחות ומניין "
            "המהווה שליש מהחברים."
        ),
        notes="G7. Governance-procedure question inside the bylaw. [bucket: single-hop]",
    ),
    GoldenSeed(
        question="מה הרוב הנדרש לתיקון תקנון?",
        expected_doc_filenames=["takanon-elrom-2024.pdf"],
        expected_keywords=["רוב מיוחד", "תיקון", "שני שלישים"],
        expected_answer=(
            "תיקון תקנון דורש רוב מיוחד של שני שלישים מהחברים המשתתפים "
            "באסיפה."
        ),
        notes="G8. Distinctive numeric answer (2/3) — easy to verify. [bucket: single-hop]",
    ),
    GoldenSeed(
        question="מי מוסמך לפטר עובד שכיר בקיבוץ?",
        expected_doc_filenames=["takanon-elrom-2024.pdf", "nohal-ovdim-schirim.pdf"],
        expected_keywords=["עובד שכיר", "פיטורין", "מנהל"],
        expected_answer=(
            "פיטורי עובד שכיר מבוצעים על ידי מנהל הענף בכפוף לאישור ועדת "
            "כוח אדם."
        ),
        notes="G9. Two-doc question, procedure inside bylaw context. [bucket: single-hop]",
    ),
    GoldenSeed(
        question="מה הליך הבחירה של חברי ועד הנהלה?",
        expected_doc_filenames=["takanon-elrom-2024.pdf"],
        expected_keywords=["בחירות", "ועד", "שנתיים"],
        expected_answer=(
            "חברי ועד ההנהלה נבחרים באסיפה כללית לתקופה של שנתיים, בבחירות "
            "חשאיות."
        ),
        notes="G10. Election procedure — clear right answer. [bucket: single-hop]",
    ),
    # ─── Bucket 2: Decision lookup (6) ──────────────────────────────────
    GoldenSeed(
        question="מתי אושרה תוספת הבנייה במגרשי הצעירים?",
        expected_doc_filenames=["protokol-vaadat-binui-2024-03.pdf"],
        expected_keywords=["27/2024", "14.3.2024", "40 מ״ר"],
        expected_answer=(
            "החלטה 27/2024 של ועדת בינוי מיום 14.3.2024 אישרה תוספת של עד "
            "40 מ״ר לכל יחידת דיור צעירה."
        ),
        notes="G11. Second hero-example question. Must always pass. [bucket: decision]",
    ),
    GoldenSeed(
        question="מה הוחלט לגבי מכסת המים לחקלאות ב-2024?",
        expected_doc_filenames=["protokol-vaadat-chaklaut-2024.pdf"],
        expected_keywords=["מכסת מים", "חקלאות", "2024"],
        expected_answer=(
            "ועדת חקלאות אישרה במרץ 2024 מכסת מים שנתית של X מ״ק לפי "
            "הקצאת רשות המים."
        ),
        notes="G12. Retrieval on a different committee's protocol. [bucket: decision]",
    ),
    GoldenSeed(
        question="איזו החלטה קיבלה ועדת קליטה בפברואר האחרון?",
        expected_doc_filenames=["protokol-vaadat-klita-2026-02.pdf"],
        expected_keywords=["ועדת קליטה", "פברואר"],
        expected_answer=(
            "ועדת קליטה החליטה בפברואר 2026 על עדכון קריטריוני הקבלה "
            "למועמדים חדשים."
        ),
        notes="G13. Recency test — 'פברואר האחרון' is relative and shifts. [bucket: decision]",
    ),
    GoldenSeed(
        question="מי מונה כרואה חשבון של הקיבוץ בשנה האחרונה?",
        expected_doc_filenames=["hachlata-mineiment-rc-2025.pdf"],
        expected_keywords=["רואה חשבון", "מינוי"],
        expected_answer=(
            "באסיפה כללית מיום X מונה משרד רואי חשבון Y לקדנציה של שלוש שנים."
        ),
        notes="G14. Named-entity lookup inside a decision. [bucket: decision]",
    ),
    GoldenSeed(
        question="מה גובה תקציב התרבות שאושר לשנת 2024?",
        expected_doc_filenames=["takziv-2024.pdf"],
        expected_keywords=["תקציב", "תרבות", "2024"],
        expected_answer=(
            "תקציב התרבות לשנת 2024 אושר בסך X ש״ח, כולל אירועי חגים "
            "ופעילות נוער."
        ),
        notes="G15. Numeric answer inside a budget document. [bucket: decision]",
    ),
    GoldenSeed(
        question="מהי החלטת האסיפה בעניין השכרת מבנה המרפאה?",
        expected_doc_filenames=["protokol-asifa-marpaa-2024.pdf"],
        expected_keywords=["מרפאה", "השכרה", "אסיפה"],
        expected_answer=(
            "האסיפה החליטה להשכיר את מבנה המרפאה הישן לגורם חיצוני "
            "לתקופה של 5 שנים."
        ),
        notes="G16. Assembly-level decision — different body than committee. [bucket: decision]",
    ),
    # ─── Bucket 3: Multi-hop (5) ────────────────────────────────────────
    GoldenSeed(
        question=(
            "סעיף 12(ב) לתקנון קובע את הליך השימוע — האם היו תיקונים "
            "לסעיף זה בשנה האחרונה?"
        ),
        expected_doc_filenames=["takanon-elrom-2024.pdf", "tikun-takanon-2024-11.pdf"],
        expected_keywords=["12(ב)", "תיקון", "שימוע"],
        expected_answer=(
            "סעיף 12(ב) תוקן באסיפה מנובמבר 2024 — הוספה חובת הודעה בכתב "
            "14 יום מראש לפני שימוע."
        ),
        notes="G17. Classic multi-hop — bylaw section + amendment doc. [bucket: multi-hop]",
    ),
    GoldenSeed(
        question="מה הנוהל לקבלת חבר חדש לאחר החלטה 27/2024?",
        expected_doc_filenames=["takanon-elrom-2024.pdf", "protokol-vaadat-binui-2024-03.pdf"],
        expected_keywords=["27/2024", "קבלה", "בינוי"],
        expected_answer=(
            "לאחר החלטה 27/2024 שהרחיבה זכויות בנייה, מומלץ להוסיף לתהליך "
            "הקבלה מידע על הזכויות הרלוונטיות למועמד."
        ),
        notes="G18. Connects bylaw process to specific decision impact. [bucket: multi-hop]",
    ),
    GoldenSeed(
        question="האם החלטת הועד ממרץ 2024 סותרת את סעיף 8 לתקנון?",
        expected_doc_filenames=["takanon-elrom-2024.pdf", "protokol-vaad-2024-03.pdf"],
        expected_keywords=["סעיף 8", "סתירה", "מרץ 2024"],
        expected_answer=(
            "החלטת הועד ממרץ 2024 אינה סותרת את סעיף 8 לתקנון; היא פועלת "
            "בגבולות הסמכות שהוגדרה בסעיף."
        ),
        notes="G19. Highest-difficulty — legal reasoning across two docs. [bucket: multi-hop]",
    ),
    GoldenSeed(
        question="מה תוקפו של סעיף 14 לתקנון לאחר החלטת האסיפה מנובמבר 2023?",
        expected_doc_filenames=["takanon-elrom-2024.pdf", "protokol-asifa-2023-11.pdf"],
        expected_keywords=["סעיף 14", "נובמבר 2023", "תוקף"],
        expected_answer=(
            "החלטת האסיפה מנובמבר 2023 השהתה את תוקפו של סעיף 14 עד "
            "לגיבוש נוסח חדש; נכון להיום הסעיף אינו פעיל."
        ),
        notes="G20. Tests amendment-chain understanding. [bucket: multi-hop]",
    ),
    GoldenSeed(
        question="בעקבות איזה תיקון בתקנון עודכן נוהל העברת הנחלות?",
        expected_doc_filenames=["takanon-elrom-2024.pdf", "nohal-havarat-nachala-2024.pdf"],
        expected_keywords=["תיקון", "נחלה", "העברה"],
        expected_answer=(
            "בעקבות תיקון סעיף 17 לתקנון (2024) עודכן נוהל העברת הנחלות "
            "והוספה חובת אישור מס הכנסה."
        ),
        notes="G21. Ties a bylaw amendment to a procedure update. [bucket: multi-hop]",
    ),
    # ─── Bucket 4: Procedural (5) ───────────────────────────────────────
    GoldenSeed(
        question="מה הנוהל להעברת נחלה לבן ממשיך?",
        expected_doc_filenames=["nohal-havarat-nachala-2024.pdf"],
        expected_keywords=["בן ממשיך", "נחלה", "העברה", "מס"],
        expected_answer=(
            "לפי נוהל העברות (סעיף 4) נדרשים אישור ועד הנהלה, הצהרת מס "
            "וחתימת שני עדים. הנוהל עודכן ב-2024."
        ),
        notes="G22. Third hero-example question. Must always pass. [bucket: procedural]",
    ),
    GoldenSeed(
        question="איך מגישים בקשה לוועדת קליטה?",
        expected_doc_filenames=["nohal-klita.pdf"],
        expected_keywords=["בקשה", "קליטה", "טופס"],
        expected_answer=(
            "בקשה לוועדת קליטה מוגשת בטופס הרשמי בצירוף מסמכים תומכים; "
            "הועדה דנה בבקשה בתוך 30 יום."
        ),
        notes="G23. Standard admin procedure. [bucket: procedural]",
    ),
    GoldenSeed(
        question="מהו הליך פתיחת מרפסת לפי נוהלי הבינוי?",
        expected_doc_filenames=["nohal-binui.pdf"],
        expected_keywords=["מרפסת", "בינוי", "אישור"],
        expected_answer=(
            "פתיחת מרפסת דורשת אישור ועדת בינוי, הגשת תכנית מהנדס, וקבלת "
            "היתר מהוועדה המקומית."
        ),
        notes="G24. Specific enough to force retrieval into the right nohal. [bucket: procedural]",
    ),
    GoldenSeed(
        question="מהו נוהל השיוך של דירה לחבר עוזב?",
        expected_doc_filenames=["nohal-shiuch-diur.pdf"],
        expected_keywords=["שיוך", "דירה", "חבר עוזב"],
        expected_answer=(
            "נוהל שיוך דירה לחבר עוזב מגדיר את הליך הערכת השווי, קיזוז "
            "חובות וזכויות, וההליך המשפטי הנדרש."
        ),
        notes="G25. Complex procedure — tests longer nohal retrieval. [bucket: procedural]",
    ),
    GoldenSeed(
        question="איך מגישים ערר על החלטת ועד?",
        expected_doc_filenames=["nohal-ararim.pdf", "takanon-elrom-2024.pdf"],
        expected_keywords=["ערר", "החלטה", "ועד"],
        expected_answer=(
            "ערר על החלטת ועד מוגש בכתב תוך 30 יום מפרסום ההחלטה, ונדון "
            "בוועדת ערר."
        ),
        notes="G26. Cross-references both nohal and takanon. [bucket: procedural]",
    ),
    # ─── Bucket 5: Guardrail — must refuse (4) ──────────────────────────
    # Deliberately no expected_docs / no expected_keywords: the correct
    # behavior is confidence == "refused". The automated eval scoring falls
    # back to "1.0 if confident else 0.0" when no expectations are set, so
    # a refusal on these currently scores 0.0 — invert manually when reading.
    # TODO(schema): add expected_confidence column so refusal can be scored
    # positively without hacks.
    GoldenSeed(
        question="מהי החלטת הועד לגבי מחירי הבנזין בשנת 2027?",
        expected_doc_filenames=None,
        expected_keywords=None,
        expected_answer=None,
        notes="G27. Future event — corpus cannot contain the answer. Expect refused. [bucket: guardrail]",
    ),
    GoldenSeed(
        question="מה כתוב בתקנון של קיבוץ יזרעאל?",
        expected_doc_filenames=None,
        expected_keywords=None,
        expected_answer=None,
        notes="G28. Wrong tenant — must refuse, not answer from אל-רום's corpus. [bucket: guardrail]",
    ),
    GoldenSeed(
        question="איך מכינים חומוס טעים?",
        expected_doc_filenames=None,
        expected_keywords=None,
        expected_answer=None,
        notes="G29. Off-topic — must refuse cleanly. [bucket: guardrail]",
    ),
    GoldenSeed(
        question="מי יזכה בבחירות למועצה המקומית ב-2028?",
        expected_doc_filenames=None,
        expected_keywords=None,
        expected_answer=None,
        notes="G30. Future + external + speculative — the 'smart user' trap. [bucket: guardrail]",
    ),
]


def _resolve_tenant_id(tenant_arg: str | None, tenant_id_arg: str | None) -> UUID:
    if tenant_id_arg:
        return UUID(tenant_id_arg)
    if not tenant_arg:
        sys.exit("Provide --tenant <name> or --tenant-id <uuid>.")
    tenants = identity_service.list_tenants()
    match = next((t for t in tenants if t.get("name") == tenant_arg), None)
    if match is None:
        names = ", ".join(sorted(t.get("name", "?") for t in tenants))
        sys.exit(f"No tenant named {tenant_arg!r}. Known: {names}")
    return UUID(match["id"])


def seed(
    db: Session,
    *,
    tenant_id: UUID,
    dry_run: bool,
    replace: bool,
) -> dict[str, int]:
    if replace:
        deleted = (
            db.query(GoldenQuestion)
            .filter(GoldenQuestion.tenant_id == tenant_id)
            .delete(synchronize_session=False)
        )
        print(f"  --replace: deleted {deleted} existing goldens.")

    existing_questions = {
        q.question
        for q in db.query(GoldenQuestion.question)
        .filter(GoldenQuestion.tenant_id == tenant_id)
        .all()
    }

    created = 0
    skipped = 0
    for g in GOLDENS:
        if g.question in existing_questions:
            skipped += 1
            continue
        db.add(
            GoldenQuestion(
                tenant_id=tenant_id,
                question=g.question,
                expected_doc_filenames=g.expected_doc_filenames,
                expected_keywords=g.expected_keywords,
                expected_answer=g.expected_answer,
                notes=g.notes,
            )
        )
        created += 1

    if dry_run:
        db.rollback()
        print(f"  [dry-run] would create {created}, skip {skipped}.")
    else:
        db.commit()
        print(f"  created {created}, skipped {skipped} (already existed).")

    return {"created": created, "skipped": skipped}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant", help="Tenant name (as it appears in identity).")
    parser.add_argument("--tenant-id", help="Tenant UUID (overrides --tenant).")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing.")
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Delete every existing golden for the tenant first. Destructive — requires confirmation.",
    )
    args = parser.parse_args()

    tenant_id = _resolve_tenant_id(args.tenant, args.tenant_id)

    if args.replace and not args.dry_run:
        resp = input(
            f"About to DELETE every existing golden for tenant {tenant_id}. "
            f"Type 'yes' to continue: "
        )
        if resp.strip().lower() != "yes":
            sys.exit("Aborted.")

    db = SessionLocal()
    try:
        print(f"Seeding {len(GOLDENS)} goldens for tenant {tenant_id}")
        seed(db, tenant_id=tenant_id, dry_run=args.dry_run, replace=args.replace)
    finally:
        db.close()


if __name__ == "__main__":
    main()
