"""Conversations + lexicon learning fields.

- ``conversations`` table: groups successive ``queries`` into a chat thread.
- ``queries.conversation_id`` + ``queries.turn_index``: each query is a turn.
- ``lexicon.source / status / confidence / evidence / learned_from_query_id``:
  support automatic lexicon entries learned from chat refinement pairs.
  Existing rows default to source='manual', status='active' (preserves current
  semantics — every existing entry is human-curated).

Revision ID: 0008_conversations
Revises: 0007_user_superadmin
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "0008_conversations"
down_revision: str | None = "0007_user_superadmin"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "conversations",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False, index=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("title", sa.String, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_conversations_tenant_updated", "conversations", ["tenant_id", "updated_at"])

    op.add_column(
        "queries",
        sa.Column("conversation_id", UUID(as_uuid=True), sa.ForeignKey("conversations.id"), nullable=True),
    )
    op.add_column("queries", sa.Column("turn_index", sa.Integer, nullable=True))
    op.create_index("ix_queries_conversation", "queries", ["conversation_id", "turn_index"])

    op.add_column(
        "lexicon",
        sa.Column("source", sa.String, nullable=False, server_default="manual"),
    )
    op.add_column(
        "lexicon",
        sa.Column("status", sa.String, nullable=False, server_default="active"),
    )
    op.add_column("lexicon", sa.Column("confidence", sa.Float, nullable=True))
    op.add_column("lexicon", sa.Column("evidence", JSONB, nullable=True))
    op.add_column(
        "lexicon",
        sa.Column(
            "learned_from_query_id",
            UUID(as_uuid=True),
            sa.ForeignKey("queries.id"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("lexicon", "learned_from_query_id")
    op.drop_column("lexicon", "evidence")
    op.drop_column("lexicon", "confidence")
    op.drop_column("lexicon", "status")
    op.drop_column("lexicon", "source")

    op.drop_index("ix_queries_conversation", table_name="queries")
    op.drop_column("queries", "turn_index")
    op.drop_column("queries", "conversation_id")

    op.drop_index("ix_conversations_tenant_updated", table_name="conversations")
    op.drop_table("conversations")
