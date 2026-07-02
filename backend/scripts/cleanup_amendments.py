"""Apply post-hoc fixes to already-extracted amendments.

Two cheap corrections that don't need re-running the LLM:

1. Force ``needs_review=true`` on any row whose ``target_section`` doesn't
   look like a real section number (e.g. "מבוא.ה", "כללי", or a document
   title the extractor misread as a section). See
   ``amendment_extractor.looks_like_real_section_ref``.

2. Break bidirectional ``documents.parent_doc_id`` edges — same repair the
   live extractor now runs after every extraction.

Run from the backend directory:

    .venv/bin/python -m scripts.cleanup_amendments
    .venv/bin/python -m scripts.cleanup_amendments --dry-run
"""
import argparse
import sys

from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import Amendment, Tenant
from app.services.amendment_extractor import break_circular_parents, looks_like_real_section_ref


def _cleanup_tenant(db: Session, tenant: Tenant, *, dry_run: bool) -> dict:
    print(f"\n[{tenant.name}]")

    # 1. Bad section refs.
    bad = (
        db.query(Amendment)
        .filter(Amendment.tenant_id == tenant.id, Amendment.needs_review.is_(False))
        .all()
    )
    flagged = 0
    for a in bad:
        if not looks_like_real_section_ref(a.target_section or ""):
            print(f"  flag needs_review  section={a.target_section!r}  action={a.action}  conf={a.extractor_confidence}")
            if not dry_run:
                a.needs_review = True
            flagged += 1
    if not dry_run and flagged:
        db.commit()

    # 2. Circular parents.
    if dry_run:
        circular = 0  # break_circular_parents commits; skip in dry run
        print("  (dry-run: skipping circular-parent repair)")
    else:
        circular = break_circular_parents(db, tenant.id)
        print(f"  broke {circular} circular parent edge(s)")

    return {"tenant": tenant.name, "flagged": flagged, "circular_broken": circular}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tenant", help="Restrict to one tenant by name")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    db: Session = SessionLocal()
    try:
        q = db.query(Tenant)
        if args.tenant:
            q = q.filter(Tenant.name == args.tenant)
        tenants = q.all()
        if not tenants:
            print(f"No tenants matched (filter={args.tenant!r})", file=sys.stderr)
            return 1

        summaries = [_cleanup_tenant(db, t, dry_run=args.dry_run) for t in tenants]

        print("\n=== summary ===")
        for s in summaries:
            print(f"  {s['tenant']}: flagged_for_review={s['flagged']} circular_broken={s['circular_broken']}")
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
