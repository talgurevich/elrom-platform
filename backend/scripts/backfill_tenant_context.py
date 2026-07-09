"""Seed tenant.system_context for the אל-רום tenant with the historical
hardcoded prompt block.

Idempotent — only writes if the column is currently NULL or empty. Runs
automatically on deploy via start.sh so a fresh Render deploy doesn't
regress the אל-רום answer quality (they'd otherwise get the generic
template, which has no §5 precision rules, no framing rule, no §44
amendment example).

Manual invocation:
    cd backend
    .venv/bin/python -m scripts.backfill_tenant_context
"""
import sys

from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import Tenant
from app.services.llm import ELROM_SEED_CONTEXT


def main() -> None:
    db: Session = SessionLocal()
    try:
        tenants = db.query(Tenant).filter(Tenant.name.like("%אל-רום%")).all()
        if not tenants:
            print("No אל-רום tenant found. Nothing to seed.")
            return
        seeded = 0
        for t in tenants:
            if t.system_context and t.system_context.strip():
                print(f"✓ {t.name} already has system_context ({len(t.system_context)} chars) — skipping")
                continue
            t.system_context = ELROM_SEED_CONTEXT
            seeded += 1
            print(f"✓ Seeded {t.name} with ELROM_SEED_CONTEXT ({len(ELROM_SEED_CONTEXT)} chars)")
        db.commit()
        print(f"done. seeded {seeded} tenant(s).")
    finally:
        db.close()


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        # Non-fatal — start.sh should not fail deploy over this.
        print(f"backfill_tenant_context failed: {e}", file=sys.stderr)
        sys.exit(0)
