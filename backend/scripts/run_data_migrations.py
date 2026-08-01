"""Versioned one-time data-migration runner — replaces the start.sh
backfill pile.

Each registry entry is (name, module). A name that exists in the
data_migrations table is skipped; otherwise the module runs via
``python -m`` and, on exit 0, the name is recorded. A failing entry is
logged and NOT recorded, so it retries on the next deploy — same net
behavior as the old ``|| true`` lines, minus the every-deploy cost of
re-running finished work.

Adding a new backfill = append a registry entry with a fresh name. If an
existing backfill's semantics change (e.g. title_search now includes AI
titles), register it AGAIN under a new versioned name — the old record
stays as history.

Usage:
    python -m scripts.run_data_migrations [--dry-run]
"""
import argparse
import subprocess
import sys

from sqlalchemy import text

from app.db import SessionLocal

# Ordered registry. Names are permanent — never rename a recorded entry.
MIGRATIONS: list[tuple[str, str]] = [
    ("0001_backfill_lexicon_surface_forms", "scripts.backfill_lexicon"),
    ("0002_backfill_content_hash", "scripts.backfill_content_hash"),
    ("0003_rechunk_protocols_decision_markers", "scripts.rechunk_protocols"),
    ("0004_backfill_forum", "scripts.backfill_forum"),
    ("0005_backfill_effective_date", "scripts.backfill_effective_date"),
    ("0006_backfill_folder_taxonomy", "scripts.backfill_folder_taxonomy"),
    # v2: includes AI-classified Hebrew titles alongside filenames.
    ("0007_title_search_v2_ai_titles", "scripts.backfill_title_search"),
    # Gershayim fix (2026-08-01) changed index-side lexemes; full rebuild.
    ("0008_text_search_gershayim_rebuild", "scripts.rebuild_text_search"),
]


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true", help="List pending migrations, run nothing.")
    args = p.parse_args()

    db = SessionLocal()
    try:
        applied = {
            r[0]
            for r in db.execute(text("SELECT name FROM data_migrations")).fetchall()
        }
    finally:
        db.close()

    pending = [(n, m) for n, m in MIGRATIONS if n not in applied]
    if not pending:
        print("data-migrations: nothing pending.")
        return
    print(f"data-migrations: {len(pending)} pending → {[n for n, _ in pending]}")
    if args.dry_run:
        return

    failures = 0
    for name, module in pending:
        print(f"▶ {name} ({module}) …")
        result = subprocess.run(
            [sys.executable, "-m", module],
            capture_output=True,
            text=True,
        )
        tail = "\n".join((result.stdout or "").strip().splitlines()[-5:])
        if tail:
            print(f"  {tail}")
        if result.returncode != 0:
            failures += 1
            err_tail = "\n".join((result.stderr or "").strip().splitlines()[-10:])
            print(f"  ✗ FAILED (exit {result.returncode}) — will retry next deploy.\n{err_tail}")
            continue
        db = SessionLocal()
        try:
            db.execute(
                text("INSERT INTO data_migrations (name) VALUES (:n) ON CONFLICT DO NOTHING"),
                {"n": name},
            )
            db.commit()
        finally:
            db.close()
        print(f"  ✓ {name} recorded.")

    if failures:
        print(f"data-migrations: {failures} failed (unrecorded, will retry).")
        # Exit 0 on purpose — a failed backfill must not block startup,
        # matching the old `|| true` behavior.


if __name__ == "__main__":
    main()
