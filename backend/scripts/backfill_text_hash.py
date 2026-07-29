"""Backfill documents.text_sha256 for docs ingested before migration 0022.

Reads each document's stored chunks, concatenates them in position order
to reconstruct the extracted text, and hashes the normalized form via
services/text_dedup.hash_normalized. Idempotent — only rows with
text_sha256 IS NULL are touched. Per-doc commit so a mid-run failure
doesn't roll back everything.

After hashing, groups by (tenant_id, text_sha256) and files a
CorpusFlag(kind='duplicates') for each collision found in existing docs.
The reviewer queue picks them up alongside newly-ingested collisions —
so historical PDF/DOCX pairs surface for cleanup.

Run from the backend directory:

    .venv/bin/python -m scripts.backfill_text_hash             # apply
    .venv/bin/python -m scripts.backfill_text_hash --dry-run   # report only
    .venv/bin/python -m scripts.backfill_text_hash --skip-flags  # backfill only, don't file CorpusFlag rows
"""
import argparse
import sys
from collections import defaultdict
from uuid import UUID

from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import Chunk, CorpusFlag, Document
from app.services.text_dedup import hash_normalized


def _reconstruct_text(db: Session, doc: Document) -> str:
    chunks = (
        db.query(Chunk)
        .filter(Chunk.document_id == doc.id)
        .order_by(Chunk.position.asc())
        .all()
    )
    return "\n\n".join(c.text or "" for c in chunks)


def _existing_flag_pair(db: Session, a: UUID, b: UUID) -> bool:
    """True if a CorpusFlag(kind='duplicates') already exists between these
    two docs in either direction — keeps the backfill idempotent when
    re-run after new docs land."""
    from sqlalchemy import or_, and_

    hit = (
        db.query(CorpusFlag.id)
        .filter(CorpusFlag.kind == "duplicates")
        .filter(
            or_(
                and_(CorpusFlag.new_doc_id == a, CorpusFlag.existing_doc_id == b),
                and_(CorpusFlag.new_doc_id == b, CorpusFlag.existing_doc_id == a),
            )
        )
        .first()
    )
    return hit is not None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Report changes without writing")
    parser.add_argument("--skip-flags", action="store_true", help="Only backfill hashes, don't file CorpusFlag rows for collisions")
    args = parser.parse_args()

    db: Session = SessionLocal()
    hashed = 0
    skipped_empty = 0
    flags_created = 0
    try:
        # Pass 1 — backfill text_sha256 on rows that don't have one.
        pending = (
            db.query(Document)
            .filter(Document.text_sha256.is_(None))
            .all()
        )
        print(f"Pass 1: {len(pending)} docs need text_sha256 backfill")
        for doc in pending:
            text = _reconstruct_text(db, doc)
            sha = hash_normalized(text)
            if not sha:
                skipped_empty += 1
                continue
            if args.dry_run:
                hashed += 1
                continue
            doc.text_sha256 = sha
            db.commit()
            hashed += 1

        # Pass 2 — group by (tenant_id, text_sha256) and file flags for
        # collisions. Runs over *all* docs, not just newly-backfilled, so
        # a mixed corpus (some hashed at ingest, some via this script)
        # still surfaces every duplicate pair.
        if not args.skip_flags:
            all_docs = (
                db.query(Document)
                .filter(Document.text_sha256.isnot(None))
                .order_by(Document.ingested_at.asc())
                .all()
            )
            groups: dict[tuple[UUID, str], list[Document]] = defaultdict(list)
            for d in all_docs:
                groups[(d.tenant_id, d.text_sha256)].append(d)

            colliding = [g for g in groups.values() if len(g) > 1]
            print(f"Pass 2: {len(colliding)} text-hash groups with >1 doc")

            for group in colliding:
                # Oldest is the "existing"; every newer doc gets flagged
                # against it. Skip pairs that already have a flag row.
                existing = group[0]
                for newer in group[1:]:
                    if _existing_flag_pair(db, newer.id, existing.id):
                        continue
                    if args.dry_run:
                        flags_created += 1
                        continue
                    db.add(
                        CorpusFlag(
                            tenant_id=newer.tenant_id,
                            new_doc_id=newer.id,
                            existing_doc_id=existing.id,
                            kind="duplicates",
                            topic="duplicate_text_hash",
                            explanation=(
                                "טקסט מנורמל זהה למסמך קיים "
                                f"({existing.filename!r}). זוהה בבקאפיל היסטורי."
                            ),
                            confidence=1.0,
                            status="pending",
                            extractor_model="text_sha256_exact_backfill",
                        )
                    )
                    db.commit()
                    flags_created += 1

        mode = "would apply" if args.dry_run else "applied"
        print(
            f"{mode}: hashed={hashed} skipped_empty={skipped_empty} "
            f"flags_created={flags_created}"
        )
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
