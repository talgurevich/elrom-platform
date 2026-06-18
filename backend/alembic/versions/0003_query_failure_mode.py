"""Add failure_mode + retrieval_debug to queries.

Revision ID: 0003_query_failure_mode
Revises: 0002_query_feedback
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_query_failure_mode"
down_revision: str | None = "0002_query_feedback"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("queries", sa.Column("failure_mode", sa.String, nullable=True))
    op.add_column("queries", sa.Column("retrieval_debug", sa.JSON, nullable=True))


def downgrade() -> None:
    op.drop_column("queries", "retrieval_debug")
    op.drop_column("queries", "failure_mode")
