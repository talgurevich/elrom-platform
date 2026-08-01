"""Populate ``documents.title_search`` for existing rows.

Run once after migration 0023 lands so historical docs participate in the
title lane. Idempotent — re-running rewrites the same tsvector.

Usage:
    python -m scripts.backfill_title_search [--tenant <name>] [--batch 200]

Without --tenant, backfills across all tenants.
"""
import argparse

from sqlalchemy import text

from app.db import SessionLocal
from app.models import Document
from app.services.hebrew_text import normalize_filename_for_tsvector, normalize_hebrew
from app.services.identity import get_tenant_row_by_name


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--tenant", help="Tenant name to limit the backfill to.")
    p.add_argument("--batch", type=int, default=200)
    args = p.parse_args()

    db = SessionLocal()
    try:
        q = db.query(Document.id, Document.filename, Document.doc_metadata)
        if args.tenant:
            tenant = get_tenant_row_by_name(args.tenant)
            if tenant is None:
                raise SystemExit(f"Tenant not found: {args.tenant}")
            q = q.filter(Document.tenant_id == tenant.id)
            print(f"Backfilling title_search for tenant {tenant.name} ({tenant.id})")
        else:
            print("Backfilling title_search across all tenants")

        rows = q.all()
        print(f"  {len(rows)} documents")

        updated = 0
        for i in range(0, len(rows), args.batch):
            batch = rows[i : i + args.batch]
            for doc_id, filename, meta in batch:
                norm = normalize_filename_for_tsvector(filename or "")
                # AI-classified Hebrew title adds retrieval terms the raw
                # filename lacks — index both (tsvector dedups overlap).
                ai_title = str((meta or {}).get("ai_title") or "").strip()
                if ai_title:
                    norm = f"{norm} {normalize_hebrew(ai_title)}".strip()
                db.execute(
                    text(
                        "UPDATE documents SET title_search = to_tsvector('simple', :norm) "
                        "WHERE id = :did"
                    ),
                    {"norm": norm, "did": doc_id},
                )
                updated += 1
            db.commit()
            print(f"  committed {updated}/{len(rows)}")

        print(f"done. updated {updated} documents.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
