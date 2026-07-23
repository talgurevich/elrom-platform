"""Add documents.forum — which decision-making body produced the doc.

Distinct from ``doc_type`` (what the doc IS: bylaw / decision / minutes /
other). ``forum`` captures WHERE the doc was produced, which drives the
supersession chain: committee → assembly → ballot.

Values (see docs / classifier prompt for definitions):
- assembly, committee, ballot, sub_committee
- external_law, external_ruling, contract, legal_opinion
- report, notice, procedure, budget, agreement_internal
- other

Nullable during rollout — the backfill script assigns forum to
historical docs via a mini-classifier pass, marker-guarded so it runs
once.

Revision ID: 0018_document_forum
Revises: 0017_upload_idempotency
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018_document_forum"
down_revision: str | None = "0017_upload_idempotency"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column("forum", sa.String(length=32), nullable=True),
    )
    op.create_index(
        "ix_documents_tenant_forum",
        "documents",
        ["tenant_id", "forum"],
    )


def downgrade() -> None:
    op.drop_index("ix_documents_tenant_forum", table_name="documents")
    op.drop_column("documents", "forum")
