"""Doc-level title_search tsvector for filename-based retrieval.

Adds documents.title_search (nullable TSVECTOR) + a GIN index. Populated at
ingest from ``normalize_hebrew(filename_without_extension)`` and consumed by
a new title-search lane in ``retrieval.hybrid_retrieve``.

Rationale: narrow-topic queries like "טורבינות רוח" or "ענף הסיידר" often
fail to surface docs where the term lives in the filename but only glancingly
in chunk bodies. Vector search dilutes rare terms; chunk-level BM25 needs
the term in the chunk text; filename was never indexed. This column closes
that gap.

Backfill: ``python -m scripts.backfill_title_search`` (idempotent).

Revision ID: 0023_document_title_search
Revises: 0022_document_text_hash
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import TSVECTOR

revision: str = "0023_document_title_search"
down_revision: str | None = "0022_document_text_hash"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column("title_search", TSVECTOR, nullable=True),
    )
    op.create_index(
        "documents_title_search_idx",
        "documents",
        ["title_search"],
        postgresql_using="gin",
    )


def downgrade() -> None:
    op.drop_index("documents_title_search_idx", table_name="documents")
    op.drop_column("documents", "title_search")
