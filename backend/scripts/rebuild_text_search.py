"""Rebuild the ``chunks.text_search`` tsvector column for every chunk using the
Hebrew-normalized form of the chunk text.

Run this once after deploying the Hebrew BM25 fix (ROADMAP-v0.3 P1) so the
existing corpus is queryable via the same normalization the new query path
uses. Safe to re-run — idempotent.

Usage:
    python -m scripts.rebuild_text_search [--tenant <name>] [--batch 200]

Without --tenant, rebuilds across all tenants.
"""
import argparse

from sqlalchemy import text

from app.db import SessionLocal
from app.services.identity import TenantRow, get_tenant_row_by_name, list_tenants_as_rows
from app.models import Chunk
from app.services.hebrew_text import normalize_hebrew


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--tenant", help="Tenant name to limit the rebuild to.")
    p.add_argument("--batch", type=int, default=200)
    args = p.parse_args()

    db = SessionLocal()
    try:
        q = db.query(Chunk.id, Chunk.text)
        if args.tenant:
            tenant = get_tenant_row_by_name(args.tenant)
            if tenant is None:
                raise SystemExit(f"Tenant not found: {args.tenant}")
            q = q.filter(Chunk.tenant_id == tenant.id)
            print(f"Rebuilding text_search for tenant {tenant.name} ({tenant.id})")
        else:
            print("Rebuilding text_search across all tenants")

        rows = q.all()
        print(f"  {len(rows)} chunks")

        updated = 0
        for i in range(0, len(rows), args.batch):
            batch = rows[i : i + args.batch]
            for chunk_id, chunk_text in batch:
                norm = normalize_hebrew(chunk_text or "")
                db.execute(
                    text(
                        "UPDATE chunks SET text_search = to_tsvector('simple', :norm) "
                        "WHERE id = :cid"
                    ),
                    {"norm": norm, "cid": chunk_id},
                )
                updated += 1
            db.commit()
            print(f"  committed {updated}/{len(rows)}")

        print(f"done. updated {updated} chunks.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
