"""Add folder column to documents (AI-assigned topical grouping).

Revision ID: 0006_doc_folder
Revises: 0005_doc_telemetry
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_doc_folder"
down_revision: str | None = "0005_doc_telemetry"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("folder", sa.String, nullable=True))


def downgrade() -> None:
    op.drop_column("documents", "folder")
