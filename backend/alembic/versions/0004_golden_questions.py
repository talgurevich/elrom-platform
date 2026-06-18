"""Add golden_questions for regression eval.

Revision ID: 0004_golden_questions
Revises: 0003_query_failure_mode
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY, UUID

revision: str = "0004_golden_questions"
down_revision: str | None = "0003_query_failure_mode"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "golden_questions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False, index=True),
        sa.Column("question", sa.Text, nullable=False),
        sa.Column("expected_doc_filenames", ARRAY(sa.String), nullable=True),
        sa.Column("expected_keywords", ARRAY(sa.String), nullable=True),
        sa.Column("expected_answer", sa.Text, nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("source_query_id", UUID(as_uuid=True), sa.ForeignKey("queries.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_score", sa.Float, nullable=True),
        sa.Column("last_retrieval_score", sa.Float, nullable=True),
        sa.Column("last_keyword_score", sa.Float, nullable=True),
        sa.Column("last_confidence", sa.String, nullable=True),
    )


def downgrade() -> None:
    op.drop_table("golden_questions")
