"""Populate ``chunks.section_ref`` from the existing ``section_path`` column.

Every chunk already stores a ``section_path`` string derived at ingest time
(e.g. "סעיף 44", "45.ב", "פרק א"). The amendment graph needs the canonical
section number ("44", "45.ב") to link an amendment row to the chunk it
supersedes. This backfill runs
``chunking.canonical_section_ref(chunk.section_path)`` over every chunk and
writes the result to ``chunks.section_ref``.

Idempotent. Also re-runs the supersession pass for every existing amendment,
which is now able to flip chunks that were previously unreachable because
``section_ref`` was NULL.

    .venv/bin/python -m scripts.backfill_section_ref
    .venv/bin/python -m scripts.backfill_section_ref --dry-run
"""
import argparse
import sys

from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import Amendment, Chunk, Tenant
from app.services.amendment_extractor import _apply_supersession
from app.services.chunking import canonical_section_ref


def _backfill_tenant(db: Session, tenant: Tenant, *, dry_run: bool) -> dict:
    print(f"\n[{tenant.name}]")
    chunks = (
        db.query(Chunk)
        .filter(Chunk.tenant_id == tenant.id, Chunk.section_ref.is_(None))
        .all()
    )
    print(f"  {len(chunks)} chunks with NULL section_ref")

    filled = 0
    for c in chunks:
        ref = canonical_section_ref(c.section_path)
        if ref is None:
            continue
        if not dry_run:
            c.section_ref = ref
        filled += 1
    if not dry_run and filled:
        db.commit()
    print(f"  filled {filled} chunks")

    # Now re-run supersession for existing high-confidence amendments — they
    # couldn't flip anything before because section_ref was NULL everywhere.
    superseded = 0
    if not dry_run:
        amendments = (
            db.query(Amendment)
            .filter(
                Amendment.tenant_id == tenant.id,
                Amendment.needs_review.is_(False),
                Amendment.action.in_(("replace", "delete")),
            )
            .all()
        )
        for a in amendments:
            superseded += _apply_supersession(db, a)
        if superseded:
            db.commit()
    print(f"  superseded {superseded} chunks retroactively")

    return {"tenant": tenant.name, "filled": filled, "superseded": superseded}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tenant")
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

        summaries = [_backfill_tenant(db, t, dry_run=args.dry_run) for t in tenants]

        print("\n=== summary ===")
        for s in summaries:
            print(f"  {s['tenant']}: filled={s['filled']} superseded={s['superseded']}")
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
