"""Backfill the amendment graph across an existing corpus.

Walks every document in ingest order and runs the amendment extractor. Each
call sees the docs that came before it — same view the extractor gets on a
fresh upload. Idempotent: the extractor skips docs that already have rows
in ``amendments``.

Run from the backend directory:

    .venv/bin/python -m scripts.backfill_amendments               # all tenants
    .venv/bin/python -m scripts.backfill_amendments --tenant "אל-רום"
    .venv/bin/python -m scripts.backfill_amendments --dry-run     # counts only
    .venv/bin/python -m scripts.backfill_amendments --limit 5     # first N docs

Prints one line per document with the extractor result, and a summary at the
end. Errors on any one doc are logged and the loop continues.
"""
import argparse
import sys
import time

from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import Document, Tenant
from app.services.amendment_extractor import extract_amendments


def _short(s: str, n: int = 40) -> str:
    return s if len(s) <= n else s[: n - 1] + "…"


def backfill_for_tenant(db: Session, tenant: Tenant, *, dry_run: bool, limit: int | None) -> dict:
    docs = (
        db.query(Document)
        .filter(Document.tenant_id == tenant.id)
        .order_by(Document.ingested_at)
        .all()
    )
    if limit:
        docs = docs[:limit]

    print(f"\n[{tenant.name}] {len(docs)} docs to process")
    if dry_run:
        return {
            "tenant": tenant.name,
            "docs": len(docs),
            "processed": 0,
            "edits_written": 0,
            "chunks_superseded": 0,
            "needs_review": 0,
            "skipped": 0,
            "errors": 0,
        }

    totals = {"processed": 0, "edits_written": 0, "chunks_superseded": 0, "needs_review": 0, "skipped": 0, "errors": 0}
    for i, doc in enumerate(docs, 1):
        started = time.time()
        try:
            result = extract_amendments(db, doc)
        except Exception as e:
            print(f"  [{i}/{len(docs)}] ERROR {_short(doc.filename):40s}  {str(e)[:120]}")
            totals["errors"] += 1
            continue
        elapsed = time.time() - started
        status = result.get("status", "?")
        if status == "skipped":
            totals["skipped"] += 1
            print(f"  [{i}/{len(docs)}] skip  {_short(doc.filename):40s}  ({result.get('reason')})")
            continue
        totals["processed"] += 1
        edits = result.get("edits_written", 0)
        supersed = result.get("chunks_superseded", 0)
        review = result.get("needs_review", 0)
        totals["edits_written"] += edits
        totals["chunks_superseded"] += supersed
        totals["needs_review"] += review
        print(
            f"  [{i}/{len(docs)}] ok    {_short(doc.filename):40s}  "
            f"edits={edits} superseded={supersed} review={review}  ({elapsed:.1f}s)"
        )

    print(
        f"[{tenant.name}] done — processed={totals['processed']} skipped={totals['skipped']} "
        f"errors={totals['errors']} edits={totals['edits_written']} "
        f"superseded={totals['chunks_superseded']} needs_review={totals['needs_review']}"
    )
    return {"tenant": tenant.name, "docs": len(docs), **totals}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tenant", help="Restrict to a single tenant by name")
    parser.add_argument("--dry-run", action="store_true", help="Just count docs, don't call the LLM")
    parser.add_argument("--limit", type=int, help="Process only the first N docs per tenant")
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

        summaries = [backfill_for_tenant(db, t, dry_run=args.dry_run, limit=args.limit) for t in tenants]

        print("\n=== summary ===")
        for s in summaries:
            print(
                f"  {s['tenant']}: docs={s['docs']} processed={s['processed']} "
                f"edits={s['edits_written']} superseded={s['chunks_superseded']} "
                f"review={s['needs_review']} skipped={s['skipped']} errors={s['errors']}"
            )
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
