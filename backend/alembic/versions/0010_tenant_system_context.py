"""Add tenants.system_context — per-tenant system-prompt block.

Free-text override that gets injected into the answerer's system prompt.
Nullable — when a tenant has no context set, the answerer falls through to
a generic hierarchy/no-fabrication template built from just the tenant name.

Revision ID: 0010_tenant_system_context
Revises: 0009_amendments
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010_tenant_system_context"
down_revision: str | None = "0009_amendments"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tenants",
        sa.Column("system_context", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("tenants", "system_context")
