"""Eval run history — regression tracking for the golden set.

Each row is one full pass over a tenant's goldens: aggregate scores +
compact per-golden results. Written by the post-deploy eval task and by
the manual /api/eval/run endpoint, so score history accumulates in one
place and regression detection can compare consecutive runs.

The partial unique index on (tenant_id, git_sha) WHERE trigger='deploy'
is the claim guard: with WEB_CONCURRENCY=2, both workers race to insert
the deploy-run row; the loser gets an IntegrityError and skips.

Revision ID: 0024_eval_runs
Revises: 0023_document_title_search
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0024_eval_runs"
down_revision: str | None = "0023_document_title_search"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "eval_runs",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", sa.UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("git_sha", sa.String(64), nullable=True),
        sa.Column("trigger", sa.String(16), nullable=False, server_default="manual"),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("total", sa.Integer, nullable=True),
        sa.Column("avg_score", sa.Float, nullable=True),
        sa.Column("avg_retrieval", sa.Float, nullable=True),
        sa.Column("avg_keyword", sa.Float, nullable=True),
        sa.Column("confidence_counts", sa.JSON, nullable=True),
        sa.Column("results", sa.JSON, nullable=True),
    )
    op.create_index(
        "eval_runs_deploy_claim_idx",
        "eval_runs",
        ["tenant_id", "git_sha"],
        unique=True,
        postgresql_where=sa.text("trigger = 'deploy'"),
    )


def downgrade() -> None:
    op.drop_index("eval_runs_deploy_claim_idx", table_name="eval_runs")
    op.drop_table("eval_runs")
