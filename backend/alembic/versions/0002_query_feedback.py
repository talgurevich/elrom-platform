"""Add feedback column to queries (for 👍/👎 from secretary).

Revision ID: 0002_query_feedback
Revises: 0001_initial
Create Date: 2026-06-18

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_query_feedback"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("queries", sa.Column("feedback", sa.String, nullable=True))
    op.add_column("queries", sa.Column("reviewer_action", sa.String, nullable=True))


def downgrade() -> None:
    op.drop_column("queries", "reviewer_action")
    op.drop_column("queries", "feedback")
