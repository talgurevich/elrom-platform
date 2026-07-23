"""One-off: re-chunk existing protocols + decisions with the updated chunker.

Motivation: the chunker gained הוחלט:/הוחלט פה אחד:/החלטה: line-start markers
(see backend/app/services/chunking.SECTION_RE). Historical protocols were
chunked before those markers existed, so their decisions are buried inside
paragraph chunks and don't get their own section_path. Retrieval improvements
for decisions/protocols (recency boost, higher per-doc cap, rerank hints)
can't help chunks that were never split correctly in the first place.

What this does per doc where ``doc_type IN ('minutes', 'decision')``:
1. Reconstruct the full text by concatenating existing chunks in position
   order (chunker is deterministic on marker patterns — no OCR needed).
2. Delete the old chunks.
3. Re-run chunk_document, re-embed via Cohere, re-insert with text_search.
4. Update doc.chunks_created.

Side effect: any Query/AuthoritativeAnswer.source_chunk_ids that pointed
at the old chunks become orphan references (same accepted tradeoff as the
dedup batch-delete flow — historical citations may show as empty). This
is documented in the CLI output at the end.

Idempotent: sets ``doc.doc_metadata["rechunked_v2"] = true`` after
processing, and skips any doc that already has that marker. Safe to
run on every deploy — first run re-chunks, subsequent runs are no-ops
(no wasted Cohere embed calls). If chunker rules change again, bump
the marker key (e.g., ``rechunked_v3``).

    .venv/bin/python -m scripts.rechunk_protocols
    .venv/bin/python -m scripts.rechunk_protocols --tenant "אל-רום"
    .venv/bin/python -m scripts.rechunk_protocols --dry-run
"""
from __future__ import annotations

import argparse
from collections import Counter

from sqlalchemy import text as sa_text
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import Chunk, Document
from app.services.chunking import (
    build_contextual_input,
    canonical_section_ref,
    chunk_document,
)
from app.services.embedding import embed_texts
from app.services.hebrew_text import normalize_hebrew
from app.services.identity import get_tenant_row_by_name, list_tenants_as_rows

RECHUNK_TYPES = ("minutes", "decision")

# Bump this key if the chunker gets a substantive protocol/decision
# rule change and previously-rechunked docs need to be redone.
# v3: chunks now tagged with decision_type (terminal / escalation) via
# chunk_metadata — see chunking._classify_decision.
_RECHUNK_MARKER = "rechunked_v3"


def _reconstruct_text(db: Session, doc: Document) -> str:
    """Join existing chunks in position order. Since the chunker never
    added synthetic content, this reproduces the original extracted text
    modulo inter-section whitespace (which the chunker collapsed via
    .strip() anyway)."""
    rows = (
        db.query(Chunk.text)
        .filter(Chunk.document_id == doc.id)
        .order_by(Chunk.position)
        .all()
    )
    return "\n\n".join(r[0] for r in rows if r[0])


def rechunk_doc(db: Session, doc: Document, *, dry_run: bool) -> tuple[int, int]:
    """Returns (old_chunks, new_chunks)."""
    original_text = _reconstruct_text(db, doc)
    if not original_text.strip():
        return (0, 0)

    old_count = (
        db.query(Chunk).filter(Chunk.document_id == doc.id).count()
    )

    new_chunks = chunk_document(original_text)
    if not new_chunks:
        # Shouldn't happen — text is non-empty. Skip safely.
        return (old_count, 0)

    if dry_run:
        return (old_count, len(new_chunks))

    # Delete old chunks. Orphans any Query.source_chunk_ids references —
    # accepted tradeoff, same as dedup batch-delete.
    db.query(Chunk).filter(Chunk.document_id == doc.id).delete(synchronize_session=False)

    # Embed the new chunks with the same contextual header we use at
    # ingest time (title + section — see build_contextual_input).
    embeddings = embed_texts(
        [
            build_contextual_input(
                text=sc.text,
                section_path=sc.section_path,
                document_title=doc.filename,
            )
            for sc in new_chunks
        ]
    )

    for sc, embedding in zip(new_chunks, embeddings, strict=True):
        chunk = Chunk(
            document_id=doc.id,
            tenant_id=doc.tenant_id,
            position=sc.position,
            section_path=sc.section_path,
            section_ref=canonical_section_ref(sc.section_path),
            text=sc.text,
            embedding=embedding,
            effective_date=doc.effective_date,
            chunk_metadata={"decision_type": sc.decision_type} if sc.decision_type else None,
        )
        db.add(chunk)
        db.flush()
        db.execute(
            sa_text(
                "UPDATE chunks SET text_search = to_tsvector('simple', :norm) WHERE id = :cid"
            ),
            {"cid": chunk.id, "norm": normalize_hebrew(sc.text)},
        )

    doc.chunks_created = len(new_chunks)
    doc.doc_metadata = {**(doc.doc_metadata or {}), _RECHUNK_MARKER: True}
    db.commit()
    return (old_count, len(new_chunks))


def run_for_tenant(db: Session, tenant_id, *, dry_run: bool) -> dict:
    # Skip docs already re-chunked at this marker version — makes the
    # script cheap to leave in start.sh on every deploy.
    all_docs = (
        db.query(Document)
        .filter(Document.tenant_id == tenant_id)
        .filter(Document.doc_type.in_(RECHUNK_TYPES))
        .all()
    )
    docs = [
        d for d in all_docs
        if not (d.doc_metadata or {}).get(_RECHUNK_MARKER)
    ]
    if not docs:
        return {"docs_scanned": 0, "already_marked": len(all_docs)}

    delta_counter: Counter = Counter()
    total_old = 0
    total_new = 0
    for d in docs:
        old, new = rechunk_doc(db, d, dry_run=dry_run)
        total_old += old
        total_new += new
        if new > old:
            delta_counter["gained_chunks"] += new - old
        elif old > new:
            delta_counter["lost_chunks"] += old - new
        else:
            delta_counter["unchanged"] += 1
    return {
        "docs_scanned": len(docs),
        "chunks_before": total_old,
        "chunks_after": total_new,
        "delta": dict(delta_counter),
        "dry_run": dry_run,
    }


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--tenant", help="Limit to a single tenant by name.")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    db = SessionLocal()
    try:
        if args.tenant:
            t = get_tenant_row_by_name(args.tenant)
            tenants = [t] if t else []
        else:
            tenants = list_tenants_as_rows()
        if not tenants:
            print("No tenants matched.")
            return
        for t in tenants:
            res = run_for_tenant(db, t.id, dry_run=args.dry_run)
            print(f"{t.name}: {res}")
        print(
            "\nNote: chunks were replaced with new IDs. Any historical "
            "Query/AuthoritativeAnswer citations that referenced old chunks "
            "will show as orphan links; re-asking those questions produces "
            "fresh citations against the new chunks."
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()
