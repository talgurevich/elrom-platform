"""Re-run the decision-type classifier over existing chunks, in place.

The escalation detector in ``services/chunking._classify_decision`` was
broadened (2026-07-28) after a corpus audit showed real protocols phrase
escalations with the object between verb and destination ("להעביר את
הנושא להצבעה בקלפי") — the original fixed phrase list caught almost
nothing. This script recomputes ``chunk_metadata.decision_type`` from
the stored chunk text. Texts are unchanged, so embeddings and the FTS
column stay valid — this is metadata-only.

Idempotent: re-running converges (same classifier, same texts).

Run from the backend directory:

    .venv/bin/python -m scripts.reclassify_decision_types            # apply
    .venv/bin/python -m scripts.reclassify_decision_types --dry-run  # report only
"""
import argparse
import sys

from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import Chunk
from app.services.chunking import _classify_decision


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Report changes without writing")
    args = parser.parse_args()

    db: Session = SessionLocal()
    try:
        chunks = db.query(Chunk).all()
        changed = {"added_escalation": 0, "added_terminal": 0, "flipped": 0, "cleared": 0}
        for c in chunks:
            old = (c.chunk_metadata or {}).get("decision_type")
            new = _classify_decision(c.text or "")
            if old == new:
                continue
            if old is None:
                changed["added_escalation" if new == "escalation" else "added_terminal"] += 1
            elif new is None:
                changed["cleared"] += 1
            else:
                changed["flipped"] += 1
            if not args.dry_run:
                meta = dict(c.chunk_metadata or {})
                if new is None:
                    meta.pop("decision_type", None)
                else:
                    meta["decision_type"] = new
                c.chunk_metadata = meta or None
        if not args.dry_run:
            db.commit()
        total = sum(changed.values())
        mode = "would change" if args.dry_run else "changed"
        print(
            f"{mode} {total} of {len(chunks)} chunks — "
            f"+escalation={changed['added_escalation']} +terminal={changed['added_terminal']} "
            f"flipped={changed['flipped']} cleared={changed['cleared']}"
        )
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
