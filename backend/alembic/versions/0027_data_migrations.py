"""Bookkeeping table for one-time data migrations (backfills).

start.sh used to run ~10 idempotent backfill scripts on EVERY deploy —
each opens DB connections and scans tables, adding minutes of startup and
load for work that finished long ago. scripts/run_data_migrations.py now
runs each registered backfill exactly once and records it here; a failed
backfill stays unrecorded and retries next deploy.

Revision ID: 0027_data_migrations
Revises: 0026_embedding_model
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0027_data_migrations"
down_revision: str | None = "0026_embedding_model"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "data_migrations",
        sa.Column("name", sa.String(128), primary_key=True),
        sa.Column("applied_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("data_migrations")
