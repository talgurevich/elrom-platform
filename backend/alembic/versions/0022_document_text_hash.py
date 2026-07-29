"""Normalized-text hash column on documents for cross-format dedup.

Adds documents.text_sha256 (nullable, 64-char hex) + a composite index on
(tenant_id, text_sha256). Populated at ingest by hashing the normalized
extracted text (see services/text_dedup.py). Two documents whose raw
bytes differ (a PDF and a DOCX of the same text, a re-scanned copy) but
whose normalized text matches will share a text_sha256 — the ingest hook
files that as a CorpusFlag(kind='duplicates') for reviewer confirmation
rather than rejecting the upload.

Nullable + no unique constraint on purpose: near-duplicates are common
(revised drafts, re-exports) and we want the reviewer to decide, not the
database. Backfill via scripts/backfill_text_hash.py.

Revision ID: 0022_document_text_hash
Revises: 0021_document_status
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0022_document_text_hash"
down_revision: str | None = "0021_document_status"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column("text_sha256", sa.String(length=64), nullable=True),
    )
    op.create_index(
        "ix_documents_tenant_text_sha256",
        "documents",
        ["tenant_id", "text_sha256"],
    )


def downgrade() -> None:
    op.drop_index("ix_documents_tenant_text_sha256", table_name="documents")
    op.drop_column("documents", "text_sha256")
