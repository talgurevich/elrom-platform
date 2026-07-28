"""Backfill decision chains + corpus reconciliation across an existing corpus.

Walks every document in ingest order and runs the two governance passes
that new uploads get automatically:

  1. ``resolve_chains_for_document`` — link escalation chunks (הוחלט
     להעביר לאסיפה / לקלפי) to the terminal decision in the higher forum.
  2. ``reconcile_document`` — flag contradictions / de-facto
     supersessions / duplicates against the rest of the corpus.

Both are idempotent: chains dedupe per escalation chunk, reconciliation
skips docs that already have flags. Docs without a classified forum are
skipped by the chain pass — run scripts.backfill_forum first if needed.

Run from the backend directory:

    .venv/bin/python -m scripts.backfill_governance                 # all tenants
    .venv/bin/python -m scripts.backfill_governance --tenant "אל-רום"
    .venv/bin/python -m scripts.backfill_governance --dry-run       # counts only
    .venv/bin/python -m scripts.backfill_governance --limit 5       # first N docs
    .venv/bin/python -m scripts.backfill_governance --skip-reconcile

Tenant selection: by default tenants are listed from the identity
service (needs IDENTITY_SERVICE_TOKEN). Pass ``--tenant-id <uuid>`` or
``--all-from-db`` to derive tenants from the documents table instead —
useful when running against the DB directly without identity access.
"""
import argparse
import sys
import time
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import Document
from app.services.decision_chain import resolve_chains_for_document
from app.services.reconciliation import reconcile_document


@dataclass
class _Tenant:
    id: UUID
    name: str


def _tenants_from_db(db: Session) -> list[_Tenant]:
    rows = db.query(Document.tenant_id).distinct().all()
    return [_Tenant(id=r[0], name=str(r[0])[:8]) for r in rows]


def _short(s: str, n: int = 40) -> str:
    return s if len(s) <= n else s[: n - 1] + "…"


def backfill_for_tenant(
    db: Session,
    tenant,
    *,
    dry_run: bool,
    limit: int | None,
    skip_reconcile: bool,
) -> dict:
    docs = (
        db.query(Document)
        .filter(Document.tenant_id == tenant.id)
        .order_by(Document.ingested_at)
        .all()
    )
    if limit:
        docs = docs[:limit]

    print(f"\n[{tenant.name}] {len(docs)} docs to process")
    totals = {
        "docs": len(docs),
        "chains_written": 0,
        "chains_review": 0,
        "flags_written": 0,
        "skipped": 0,
        "errors": 0,
    }
    if dry_run:
        return {"tenant": tenant.name, **totals}

    for i, doc in enumerate(docs, 1):
        started = time.time()
        line_parts = []
        try:
            chain = resolve_chains_for_document(db, doc)
            if chain.get("status") == "ok":
                totals["chains_written"] += chain.get("written", 0)
                totals["chains_review"] += chain.get("needs_review", 0)
                line_parts.append(
                    f"chains={chain.get('written', 0)} review={chain.get('needs_review', 0)}"
                )
            else:
                line_parts.append(f"chains:{chain.get('reason') or chain.get('status')}")
        except Exception as e:
            db.rollback()
            totals["errors"] += 1
            line_parts.append(f"chains:ERROR {str(e)[:80]}")

        if not skip_reconcile:
            try:
                recon = reconcile_document(db, doc)
                if recon.get("status") == "ok":
                    totals["flags_written"] += recon.get("flags_written", 0)
                    line_parts.append(
                        f"pairs={recon.get('pairs_checked', 0)} flags={recon.get('flags_written', 0)}"
                    )
                else:
                    line_parts.append(f"recon:{recon.get('reason') or recon.get('status')}")
            except Exception as e:
                db.rollback()
                totals["errors"] += 1
                line_parts.append(f"recon:ERROR {str(e)[:80]}")

        elapsed = time.time() - started
        print(f"  [{i}/{len(docs)}] {_short(doc.filename):40s}  {'  '.join(line_parts)}  ({elapsed:.1f}s)")

    print(
        f"[{tenant.name}] done — chains={totals['chains_written']} "
        f"(review={totals['chains_review']}) flags={totals['flags_written']} "
        f"errors={totals['errors']}"
    )
    return {"tenant": tenant.name, **totals}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tenant", help="Restrict to a single tenant by name (via identity)")
    parser.add_argument("--tenant-id", help="Restrict to a single tenant by UUID (no identity call)")
    parser.add_argument(
        "--all-from-db",
        action="store_true",
        help="Derive tenants from the documents table instead of identity",
    )
    parser.add_argument("--dry-run", action="store_true", help="Just count docs, don't call the LLM")
    parser.add_argument("--limit", type=int, help="Process only the first N docs per tenant")
    parser.add_argument(
        "--skip-reconcile",
        action="store_true",
        help="Only build decision chains, skip the contradiction pass",
    )
    args = parser.parse_args()

    db: Session = SessionLocal()
    try:
        if args.tenant_id:
            tenants = [_Tenant(id=UUID(args.tenant_id), name=args.tenant_id[:8])]
        elif args.all_from_db:
            tenants = _tenants_from_db(db)
        else:
            from app.services.identity import list_tenants_as_rows

            tenants = list(list_tenants_as_rows())
            if args.tenant:
                tenants = [t for t in tenants if t.name == args.tenant]
        if not tenants:
            print(f"No tenants matched (filter={args.tenant!r})", file=sys.stderr)
            return 1

        summaries = [
            backfill_for_tenant(
                db,
                t,
                dry_run=args.dry_run,
                limit=args.limit,
                skip_reconcile=args.skip_reconcile,
            )
            for t in tenants
        ]

        print("\n=== summary ===")
        for s in summaries:
            print(
                f"  {s['tenant']}: docs={s['docs']} chains={s['chains_written']} "
                f"(review={s['chains_review']}) flags={s['flags_written']} "
                f"skipped={s['skipped']} errors={s['errors']}"
            )
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
