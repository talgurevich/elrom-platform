"""Indexes supporting per-tenant usage analytics.

``queries`` carried only ``queries_tenant_idx`` (tenant_id alone, from
0001). Every engagement metric filters ``tenant_id = ? AND created_at >
?`` and groups by ``user_id``, so the planner was left doing a tenant
scan plus a filter on every panel load. Two composite indexes cover it:

  * (tenant_id, created_at)          — windowed counts, weekly buckets
  * (tenant_id, user_id, created_at) — per-user aggregates, last-seen

Index-only, no columns and no data change. Created CONCURRENTLY so a
production build takes no write lock on a table that is on the hot path
for every question asked.

Revision ID: 0019_query_analytics_indexes
Revises: 0018_document_forum
"""
from collections.abc import Sequence

from alembic import op

revision: str = "0019_query_analytics_indexes"
down_revision: str | None = "0018_document_forum"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# CREATE INDEX CONCURRENTLY cannot run inside a transaction block, and
# alembic wraps migrations in one by default.
def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.create_index(
            "ix_queries_tenant_created",
            "queries",
            ["tenant_id", "created_at"],
            postgresql_concurrently=True,
            if_not_exists=True,
        )
        op.create_index(
            "ix_queries_tenant_user_created",
            "queries",
            ["tenant_id", "user_id", "created_at"],
            postgresql_concurrently=True,
            if_not_exists=True,
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.drop_index(
            "ix_queries_tenant_user_created",
            table_name="queries",
            postgresql_concurrently=True,
            if_exists=True,
        )
        op.drop_index(
            "ix_queries_tenant_created",
            table_name="queries",
            postgresql_concurrently=True,
            if_exists=True,
        )
