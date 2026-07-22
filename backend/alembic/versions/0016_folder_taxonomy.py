"""Folder taxonomy — turn ad-hoc AI-generated folders into a bounded per-tenant set.

Before: the classifier invented folder names as free text, biased toward
generic-sounding names ("מבנה ארגוני") that ate a majority of documents
via a Matthew effect ("that folder is already big → put new stuff there").

After: reviewer curates a small named-folder set per tenant. The
classifier picks from that list OR returns no_fit, which lands in
`folder_suggestion` for reviewer triage (same shape as lexicon pending
queue).

Two tables:
- folder_taxonomy: the tenant's curated folder set. active=false hides a
  folder from new classifications without breaking existing doc.folder
  values that reference it.
- folder_suggestion: pending "no_fit" candidates. Reviewer accepts (which
  creates a folder_taxonomy row) or rejects. Same lifecycle as
  lexicon suggestions.

Revision ID: 0016_folder_taxonomy
Revises: 0015_lexicon_rewrite
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016_folder_taxonomy"
down_revision: str | None = "0015_lexicon_rewrite"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "folder_taxonomy",
        sa.Column(
            "id",
            sa.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("tenant_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        # Free-text description shown to the classifier so it has a
        # semantic boundary, not just a name. Also shown in the UI.
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_folder_taxonomy_tenant_active",
        "folder_taxonomy",
        ["tenant_id", "active"],
    )
    # Guard against duplicates within a tenant (case-sensitive; the
    # tenant is responsible for consistent naming).
    op.create_index(
        "ix_folder_taxonomy_tenant_name",
        "folder_taxonomy",
        ["tenant_id", "name"],
        unique=True,
    )

    op.create_table(
        "folder_suggestion",
        sa.Column(
            "id",
            sa.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("tenant_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("proposed_name", sa.Text(), nullable=False),
        sa.Column("proposed_description", sa.Text(), nullable=True),
        # Doc that triggered the suggestion — reviewer can see it in context.
        sa.Column(
            "source_doc_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("documents.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("source_title", sa.Text(), nullable=True),
        sa.Column("source_summary", sa.Text(), nullable=True),
        # pending | accepted | rejected | duplicate
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default="pending",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_folder_suggestion_tenant_status",
        "folder_suggestion",
        ["tenant_id", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_folder_suggestion_tenant_status", table_name="folder_suggestion")
    op.drop_table("folder_suggestion")
    op.drop_index("ix_folder_taxonomy_tenant_name", table_name="folder_taxonomy")
    op.drop_index("ix_folder_taxonomy_tenant_active", table_name="folder_taxonomy")
    op.drop_table("folder_taxonomy")
