"""Re-embed every chunk in the database with the new contextual format.

What this does
--------------
Today's embeddings are computed from raw chunk text only — Cohere has no
signal about which document or section a chunk came from. The new format
prepends "<document title> — <section_path>\\n\\n<text>" before embedding,
which (per published research and the Anthropic contextual-retrieval writeup)
materially boosts recall on structured corpora.

This script walks every Chunk row in the DB, rebuilds the contextual input,
re-embeds in provider-batches, and writes the new vector back. Document text,
filenames, classifications, and chunk text are untouched. Only the `embedding`
column is rewritten.

Run from the backend directory:

    .venv/bin/python -m scripts.reembed_contextual          # all tenants
    .venv/bin/python -m scripts.reembed_contextual --tenant "אל-רום"
    .venv/bin/python -m scripts.reembed_contextual --dry-run

Idempotent — running it twice in a row is fine.
"""
import argparse
import sys
import time

from sqlalchemy.orm import Session, joinedload

from app.db import SessionLocal
from app.services.identity import TenantRow, get_tenant_row_by_name, list_tenants_as_rows
from app.models import Chunk
from app.services.chunking import build_contextual_input
from app.services.embedding import embed_texts

# Commit after this many chunks; balances "don't lose progress on crash"
# against "don't thrash the DB."
COMMIT_EVERY = 96


def reembed_for_tenant(db: Session, tenant_id, *, dry_run: bool) -> tuple[int, int]:
    """Returns (chunks_seen, chunks_reembedded)."""
    chunks = (
        db.query(Chunk)
        .options(joinedload(Chunk.document))
        .filter(Chunk.tenant_id == tenant_id)
        .order_by(Chunk.document_id, Chunk.position)
        .all()
    )
    if not chunks:
        return 0, 0

    seen = len(chunks)
    print(f"  found {seen} chunks across {len({c.document_id for c in chunks})} documents")

    if dry_run:
        # Print a sample of what the new inputs would look like
        for c in chunks[:3]:
            sample_input = build_contextual_input(
                text=c.text or "",
                section_path=c.section_path,
                document_title=c.document.filename if c.document else None,
            )
            preview = sample_input[:200].replace("\n", " / ")
            print(f"    sample: {preview}…")
        return seen, 0

    inputs = [
        build_contextual_input(
            text=c.text or "",
            section_path=c.section_path,
            document_title=c.document.filename if c.document else None,
        )
        for c in chunks
    ]
    t0 = time.time()
    new_vecs = embed_texts(inputs, input_type="search_document")
    elapsed = time.time() - t0
    print(f"  embedded {len(new_vecs)} vectors in {elapsed:.1f}s")

    written = 0
    for c, v in zip(chunks, new_vecs, strict=True):
        c.embedding = v
        written += 1
        if written % COMMIT_EVERY == 0:
            db.commit()
            print(f"  committed {written}/{seen}")
    db.commit()
    print(f"  ✓ committed {written}/{seen}")
    return seen, written


def main() -> None:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--tenant", default=None, help="Only re-embed this tenant (by name)")
    p.add_argument("--dry-run", action="store_true", help="Show what would change")
    args = p.parse_args()

    db: Session = SessionLocal()
    try:
        if args.tenant:
            t = get_tenant_row_by_name(args.tenant)
            if t is None:
                print(f"✗ Tenant {args.tenant!r} not found", file=sys.stderr)
                sys.exit(2)
            tenants = [t]
        else:
            tenants = list_tenants_as_rows()
            if not tenants:
                print("No tenants in DB. Nothing to do.")
                return

        total_seen = 0
        total_written = 0
        for t in tenants:
            print(f"\n▶ tenant: {t.name}  ({t.id})")
            seen, written = reembed_for_tenant(db, t.id, dry_run=args.dry_run)
            total_seen += seen
            total_written += written

        print()
        if args.dry_run:
            print(f"DRY RUN: would re-embed {total_seen} chunks. No changes written.")
        else:
            print(f"DONE: re-embedded {total_written}/{total_seen} chunks.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
