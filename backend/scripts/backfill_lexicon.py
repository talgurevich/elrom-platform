"""Backfill surface_forms + answerer_expansion on existing lexicon rows.

Migration 0015 populates the two columns to a minimal working state
(surface_forms = [term], answerer_expansion = expansion). This script
enriches surface_forms with Hebrew prefix/plural variants so the matcher
starts firing on real user phrasings ("השיוך" hits an entry stored as
"שיוך"), and leaves the reviewer a note in `notes` that says "auto-expanded
surface_forms — please trim what doesn't fit."

Idempotent: rows that already have >1 surface_form are skipped so re-runs
after reviewer edits don't clobber trimmed lists.

Usage:
    python -m scripts.backfill_lexicon
    python -m scripts.backfill_lexicon --tenant "אל-רום" --dry-run
"""
import argparse

from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import Lexicon
from app.services.hebrew_prefixes import expand_hebrew_prefixes
from app.services.identity import get_tenant_row_by_name


def _backfill_row(row: Lexicon) -> tuple[bool, int]:
    """Returns (changed, num_forms_after)."""
    already_expanded = row.surface_forms and len(row.surface_forms) > 1
    if already_expanded:
        return (False, len(row.surface_forms))
    forms = expand_hebrew_prefixes(row.term or "")
    if not forms:
        return (False, len(row.surface_forms or []))
    row.surface_forms = forms
    # Only touch short_gloss/answerer_expansion if they're still empty.
    if not (row.answerer_expansion or "").strip():
        row.answerer_expansion = row.expansion
    return (True, len(forms))


def run(db: Session, *, tenant_id=None, dry_run: bool = False) -> dict:
    q = db.query(Lexicon)
    if tenant_id is not None:
        q = q.filter(Lexicon.tenant_id == tenant_id)
    rows = q.all()
    changed = 0
    total_forms = 0
    for r in rows:
        did, n = _backfill_row(r)
        if did:
            changed += 1
        total_forms += n
    if not dry_run and changed:
        db.commit()
    return {
        "rows": len(rows),
        "changed": changed,
        "avg_forms_per_row": (total_forms / len(rows)) if rows else 0,
        "dry_run": dry_run,
    }


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--tenant", help="Limit to a single tenant by name.")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    tenant_id = None
    if args.tenant:
        t = get_tenant_row_by_name(args.tenant)
        if not t:
            print(f"Tenant not found: {args.tenant}")
            return
        tenant_id = t.id

    db = SessionLocal()
    try:
        result = run(db, tenant_id=tenant_id, dry_run=args.dry_run)
        print(result)
    finally:
        db.close()


if __name__ == "__main__":
    main()
