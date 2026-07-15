"""Link Query rows back to the GoldenQuestion they were run against.

Adds queries.golden_id (nullable FK → golden_questions.id) so that when a
golden is dispatched through the live chat pipeline, the resulting Query
row (with its 👍/👎 feedback) can be tied back to the golden. This is
what powers the per-golden pass-rate report in /api/eval/report.

Not backfilled — pre-existing Query rows have no reliable link to a
golden, so they stay NULL and are simply excluded from the report.

Revision ID: 0013_query_golden_id
Revises: 0012_drop_auth_tables
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0013_query_golden_id"
down_revision: str | None = "0012_drop_auth_tables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "queries",
        sa.Column(
            "golden_id",
            UUID(as_uuid=True),
            sa.ForeignKey("golden_questions.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_queries_golden_id", "queries", ["golden_id"])


def downgrade() -> None:
    op.drop_index("ix_queries_golden_id", table_name="queries")
    op.drop_column("queries", "golden_id")
