"""Content-hash column on documents for duplicate-upload prevention.

Adds documents.content_sha256 (nullable, 64-char hex) + a composite index
on (tenant_id, content_sha256). Ingest computes the hash at upload time
and rejects a new upload if the same tenant already has a row with the
matching hash — the "same file uploaded under a different filename"
problem.

Nullable + no backfill in the migration itself: pre-existing rows keep
working, but they can't participate in the dedup check until
scripts/backfill_content_hash.py hashes their stored source files. The
migration stays a schema-only change so it's fast and reversible.

Revision ID: 0014_document_content_hash
Revises: 0013_query_golden_id
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014_document_content_hash"
down_revision: str | None = "0013_query_golden_id"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column("content_sha256", sa.String(length=64), nullable=True),
    )
    op.create_index(
        "ix_documents_tenant_content_sha256",
        "documents",
        ["tenant_id", "content_sha256"],
    )


def downgrade() -> None:
    op.drop_index("ix_documents_tenant_content_sha256", table_name="documents")
    op.drop_column("documents", "content_sha256")
