"""documents.doc_status — lifecycle maturity of the document.

The third classification axis, orthogonal to doc_type (what it is) and
forum (who produced it): how binding the document is. A corpus holds,
on the same topic, proposals (הצעה), drafts (טיוטה), discussion papers
(דיון/סיכום דיון) and the adopted rule (החלטה/בתוקף) — and retrieval
previously weighed them all equally, so an unapproved הצעה could be
cited as if it were the operative נוהל.

Values: proposal | draft | discussion | adopted. Nullable during
rollout; scripts/backfill_doc_status.py stamps historical docs.

Revision ID: 0021_document_status
Revises: 0020_decision_chains_and_flags
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0021_document_status"
down_revision: str | None = "0020_decision_chains_and_flags"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column("doc_status", sa.String(length=32), nullable=True),
    )
    op.create_index(
        "ix_documents_tenant_doc_status",
        "documents",
        ["tenant_id", "doc_status"],
    )


def downgrade() -> None:
    op.drop_index("ix_documents_tenant_doc_status", table_name="documents")
    op.drop_column("documents", "doc_status")
