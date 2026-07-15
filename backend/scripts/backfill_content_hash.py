"""Populate documents.content_sha256 for pre-existing rows.

Migration 0014 added the column but left it NULL for historical rows.
This script hashes the stored source file for every Document that has
source_uri set + points at a readable file on disk, and writes the
SHA-256 hex to content_sha256.

Idempotent — skips rows that already have a hash. Rows without a source
file (source_uri is None, or file was pruned) stay NULL and simply can't
participate in the dedup check going forward.

    .venv/bin/python -m scripts.backfill_content_hash                  # writes
    .venv/bin/python -m scripts.backfill_content_hash --dry-run        # preview
    .venv/bin/python -m scripts.backfill_content_hash --report-dupes   # find + print collisions
"""
from __future__ import annotations

import argparse
import hashlib
import sys
from collections import defaultdict

from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import Document
from app.services.storage import resolve_stored_file


def _hash_file(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def backfill(db: Session, *, dry_run: bool) -> dict[str, int]:
    rows = (
        db.query(Document)
        .filter(Document.content_sha256.is_(None))
        .filter(Document.source_uri.isnot(None))
        .all()
    )
    print(f"{len(rows)} documents need hashing.")

    filled = 0
    missing = 0
    for d in rows:
        path = resolve_stored_file(d.source_uri)
        if path is None or not path.exists():
            missing += 1
            continue
        try:
            digest = _hash_file(path)
        except OSError as e:
            print(f"  ! {d.filename}: read failed: {e}")
            missing += 1
            continue
        if not dry_run:
            d.content_sha256 = digest
        filled += 1

    if dry_run:
        db.rollback()
        print(f"[dry-run] would fill {filled}, {missing} unreadable/missing.")
    else:
        db.commit()
        print(f"filled {filled}, {missing} unreadable/missing.")

    return {"filled": filled, "missing": missing}


def report_duplicates(db: Session) -> None:
    """Group documents by (tenant_id, content_sha256) and print any group
    with more than one member — these are the existing dupes worth cleaning."""
    rows = (
        db.query(Document)
        .filter(Document.content_sha256.isnot(None))
        .all()
    )
    groups: dict[tuple, list[Document]] = defaultdict(list)
    for d in rows:
        groups[(d.tenant_id, d.content_sha256)].append(d)

    dup_groups = [g for g in groups.values() if len(g) > 1]
    if not dup_groups:
        print("No duplicates found (by content_sha256).")
        return

    print(f"Found {len(dup_groups)} duplicate groups:\n")
    for group in dup_groups:
        first = group[0]
        print(f"  tenant={first.tenant_id} sha256={first.content_sha256[:12]}…")
        for d in group:
            print(f"    - {d.id}  {d.filename!r}  ingested={d.ingested_at}")
        print()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing.")
    parser.add_argument(
        "--report-dupes",
        action="store_true",
        help="After backfilling, list rows sharing a hash so you can decide which to delete.",
    )
    args = parser.parse_args()

    db = SessionLocal()
    try:
        backfill(db, dry_run=args.dry_run)
        if args.report_dupes:
            print("\n─── Duplicate report ───")
            report_duplicates(db)
    finally:
        db.close()


if __name__ == "__main__":
    main()
