"""Seed folder_taxonomy from existing distinct documents.folder values.

Idempotent: skips folders that already exist. Adds a per-folder document
count as the description (reviewer can edit later) so the initial
taxonomy is self-describing.

Usage:
    python -m scripts.backfill_folder_taxonomy
    python -m scripts.backfill_folder_taxonomy --tenant "אל-רום"
"""
import argparse
from collections import Counter

from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import Document, FolderTaxonomy
from app.services.identity import get_tenant_row_by_name, list_tenants_as_rows


def run_for_tenant(db: Session, tenant_id) -> dict:
    existing = {
        f.name
        for f in db.query(FolderTaxonomy)
        .filter(FolderTaxonomy.tenant_id == tenant_id)
        .all()
    }
    counts: Counter = Counter()
    for (name,) in (
        db.query(Document.folder)
        .filter(Document.tenant_id == tenant_id)
        .filter(Document.folder.isnot(None))
        .all()
    ):
        if name and name.strip():
            counts[name.strip()] += 1
    added = 0
    for name, n in counts.most_common():
        if name in existing:
            continue
        db.add(
            FolderTaxonomy(
                tenant_id=tenant_id,
                name=name,
                description=f"תיקייה שנוצרה אוטומטית; {n} מסמכים בעת האיחזור.",
                active=True,
            )
        )
        added += 1
    if added:
        db.commit()
    return {"folders_added": added, "distinct_folders_seen": len(counts)}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--tenant")
    args = p.parse_args()

    db = SessionLocal()
    try:
        if args.tenant:
            t = get_tenant_row_by_name(args.tenant)
            tenants = [t] if t else []
        else:
            tenants = list_tenants_as_rows()
        for t in tenants:
            res = run_for_tenant(db, t.id)
            print(f"{t.name}: {res}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
