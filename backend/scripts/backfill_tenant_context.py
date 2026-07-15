"""Seed tenant.system_context for the אל-רום tenant with the historical
hardcoded prompt block.

Post-identity-cutover: tenants live in klaser-identity, so this script
now calls identity's PATCH /api/service/tenants/{id}/system-context via
the SDK instead of writing to a local Tenant row. Behavior otherwise
unchanged — idempotent, only writes when the column is empty.

Manual invocation:
    cd backend
    .venv/bin/python -m scripts.backfill_tenant_context
"""
import sys

from app.services.identity import (
    identity_service,
    list_tenants_as_rows,
)
from app.services.llm import ELROM_SEED_CONTEXT


def main() -> None:
    tenants = [t for t in list_tenants_as_rows() if "אל-רום" in t.name]
    if not tenants:
        print("No אל-רום tenant found. Nothing to seed.")
        return
    seeded = 0
    for t in tenants:
        if t.system_context and t.system_context.strip():
            print(
                f"✓ {t.name} already has system_context "
                f"({len(t.system_context)} chars) — skipping"
            )
            continue
        identity_service.update_tenant_system_context(str(t.id), ELROM_SEED_CONTEXT)
        seeded += 1
        print(
            f"✓ Seeded {t.name} with ELROM_SEED_CONTEXT "
            f"({len(ELROM_SEED_CONTEXT)} chars)"
        )
    print(f"done. seeded {seeded} tenant(s).")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        # Non-fatal — start.sh should not fail deploy over this.
        print(f"backfill_tenant_context failed: {e}", file=sys.stderr)
        sys.exit(0)
