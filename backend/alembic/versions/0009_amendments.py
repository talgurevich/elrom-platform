"""Amendments graph — cross-document supersession.

Sub-bylaws and later resolutions routinely amend earlier bylaws (e.g. a
sub-bylaw says "סעיף 44 לתקנון הראשי ייקרא כדלקמן..."). Vanilla RAG treats
every chunk as equally true, so retrieval happily returns the superseded
original alongside the amendment and the answerer has to reason its way out
at answer time — fragile.

This migration adds the persistent structures the retriever needs to filter
supersession *before* the LLM sees the chunks:

- ``documents.parent_doc_id`` — the doc this document amends, if any.
- ``chunks.section_ref`` — canonical section number (e.g. "12.3") so
  amendments can be tied to the specific chunk they replace.
- ``chunks.superseded_by_amendment_id`` — points at the amendment row that
  replaces this chunk. Retrieval filters `IS NULL` by default; historical
  queries include supersededs.
- ``amendments`` — one row per structured edit extracted from an amendment
  doc. ``target_doc_id`` + ``target_section`` + ``effective_date`` form
  the replay key.

Revision ID: 0009_amendments
Revises: 0008_conversations
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "0009_amendments"
down_revision: str | None = "0008_conversations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column("parent_doc_id", UUID(as_uuid=True), sa.ForeignKey("documents.id"), nullable=True),
    )
    op.create_index("ix_documents_parent", "documents", ["parent_doc_id"])

    op.add_column("chunks", sa.Column("section_ref", sa.String, nullable=True))
    op.add_column(
        "chunks",
        sa.Column("superseded_by_amendment_id", UUID(as_uuid=True), nullable=True),
    )
    op.create_index(
        "ix_chunks_section_ref",
        "chunks",
        ["document_id", "section_ref"],
    )
    op.create_index(
        "ix_chunks_superseded",
        "chunks",
        ["superseded_by_amendment_id"],
    )

    op.create_table(
        "amendments",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False, index=True),
        sa.Column(
            "amendment_doc_id",
            UUID(as_uuid=True),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "target_doc_id",
            UUID(as_uuid=True),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("target_section", sa.String, nullable=False),
        sa.Column("action", sa.String, nullable=False),
        sa.Column("old_text", sa.Text, nullable=True),
        sa.Column("new_text", sa.Text, nullable=True),
        sa.Column("effective_date", sa.Date, nullable=True),
        sa.Column("rationale", sa.Text, nullable=True),
        sa.Column("extractor_confidence", sa.Float, nullable=True),
        sa.Column("needs_review", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("evidence_span", sa.Text, nullable=True),
        sa.Column("extractor_model", sa.String, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "action IN ('replace','add_after','add_before','delete','clarify')",
            name="ck_amendments_action",
        ),
    )
    op.create_index(
        "ix_amendments_target",
        "amendments",
        ["target_doc_id", "target_section", "effective_date"],
    )
    op.create_index("ix_amendments_source", "amendments", ["amendment_doc_id"])

    # Foreign key from chunks -> amendments, added after the table exists.
    op.create_foreign_key(
        "fk_chunks_superseded_amendment",
        "chunks",
        "amendments",
        ["superseded_by_amendment_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_chunks_superseded_amendment", "chunks", type_="foreignkey")
    op.drop_index("ix_amendments_source", table_name="amendments")
    op.drop_index("ix_amendments_target", table_name="amendments")
    op.drop_table("amendments")

    op.drop_index("ix_chunks_superseded", table_name="chunks")
    op.drop_index("ix_chunks_section_ref", table_name="chunks")
    op.drop_column("chunks", "superseded_by_amendment_id")
    op.drop_column("chunks", "section_ref")

    op.drop_index("ix_documents_parent", table_name="documents")
    op.drop_column("documents", "parent_doc_id")
