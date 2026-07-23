"""Backfill Document.effective_date from filename patterns.

Legacy docs uploaded before the metadata classifier ran (or ones where
the classifier couldn't parse the Hebrew date) have effective_date=NULL.
That breaks year-anchored retrieval (see services.retrieval
_extract_year_range) — the "מה קרה ב2014" boost has nothing to boost.

Most kibbutz filenames encode a date, e.g.:
    תוצאות הצבעה בקלפי 2-14 15.08.14.docx
    פרוטוקול אסיפה 4-25 21.12.2025.pdf
    החלטה 47_22 מיום 3.11.2022.pdf

This script parses those patterns and populates effective_date. Cheap
(no LLM calls), deterministic, idempotent — only touches docs where
effective_date is NULL.

Also propagates the extracted date onto every chunk of the doc so
retrieval date filters work at chunk level.

    .venv/bin/python -m scripts.backfill_effective_date
    .venv/bin/python -m scripts.backfill_effective_date --dry-run
    .venv/bin/python -m scripts.backfill_effective_date --tenant "אל-רום"
"""
from __future__ import annotations

import argparse
import re
from collections import Counter
from datetime import date

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import Chunk, Document
from app.services.identity import get_tenant_row_by_name, list_tenants_as_rows

# DD.MM.YY or DD.MM.YYYY (Hebrew dates in filenames almost always use this).
# Digit-lookarounds so "15.08.14.docx" doesn't glue with adjacent digits.
_DDMMYY_RE = re.compile(r"(?<!\d)(\d{1,2})\.(\d{1,2})\.(\d{2,4})(?!\d)")
# ISO-ish YYYY-MM-DD, occasionally seen.
_ISO_RE = re.compile(r"(?<!\d)(\d{4})-(\d{1,2})-(\d{1,2})(?!\d)")


def _interpret_year(raw: int) -> int:
    """Two-digit years: 00–30 → 20XX, 31–99 → 19XX. Anything else pass-through."""
    if raw < 100:
        return 2000 + raw if raw <= 30 else 1900 + raw
    return raw


def parse_filename_date(filename: str) -> date | None:
    """Return a date parsed from the filename, or None if no plausible
    date pattern is present. Prefers ISO if both patterns match (rare)."""
    if not filename:
        return None
    m = _ISO_RE.search(filename)
    if m:
        try:
            y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
            return date(y, mo, d)
        except ValueError:
            pass
    m = _DDMMYY_RE.search(filename)
    if m:
        try:
            d, mo, y = int(m.group(1)), int(m.group(2)), _interpret_year(int(m.group(3)))
            # Validate — the regex allows things like 32.13.24 (invalid).
            return date(y, mo, d)
        except ValueError:
            return None
    return None


def run_for_tenant(db: Session, tenant_id, *, dry_run: bool) -> dict:
    docs = (
        db.query(Document)
        .filter(Document.tenant_id == tenant_id)
        .filter(Document.effective_date.is_(None))
        .all()
    )
    if not docs:
        return {"scanned": 0}

    by_year: Counter = Counter()
    filled = 0
    for d in docs:
        parsed = parse_filename_date(d.filename)
        if parsed is None:
            continue
        by_year[parsed.year] += 1
        filled += 1
        if not dry_run:
            d.effective_date = parsed
            # Propagate onto chunks so retrieval date filters work at chunk
            # level (same denormalization the ingest path already does).
            db.execute(
                update(Chunk)
                .where(Chunk.document_id == d.id)
                .values(effective_date=parsed)
            )
    if not dry_run and filled:
        db.commit()
    return {
        "scanned": len(docs),
        "filled": filled,
        "by_year": dict(sorted(by_year.items())),
        "dry_run": dry_run,
    }


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--tenant")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    db = SessionLocal()
    try:
        if args.tenant:
            t = get_tenant_row_by_name(args.tenant)
            tenants = [t] if t else []
        else:
            tenants = list_tenants_as_rows()
        for t in tenants:
            res = run_for_tenant(db, t.id, dry_run=args.dry_run)
            print(f"{t.name}: {res}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
