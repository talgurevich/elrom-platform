"""Add is_super_admin flag to users (cross-tenant read-only inspector).

Revision ID: 0007_user_superadmin
Revises: 0006_doc_folder
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_user_superadmin"
down_revision: str | None = "0006_doc_folder"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("is_super_admin", sa.Boolean, nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("users", "is_super_admin")
