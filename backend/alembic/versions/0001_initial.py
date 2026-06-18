"""Initial schema with pgvector.

Revision ID: 0001_initial
Revises:
Create Date: 2026-06-18

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import ARRAY, JSON, TSVECTOR, UUID

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EMBED_DIM = 1024


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')

    op.create_table(
        "tenants",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String, nullable=False),
        sa.Column("segment", sa.String, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "users",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("email", sa.String, unique=True, nullable=False),
        sa.Column("display_name", sa.String),
        sa.Column("role", sa.String, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "documents",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("filename", sa.String, nullable=False),
        sa.Column("doc_type", sa.String),
        sa.Column("effective_date", sa.Date),
        sa.Column("superseded_by_id", UUID(as_uuid=True), sa.ForeignKey("documents.id")),
        sa.Column("source_uri", sa.String),
        sa.Column("ingested_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("metadata", JSON),
    )
    op.create_index("documents_tenant_idx", "documents", ["tenant_id"])

    op.create_table(
        "chunks",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("document_id", UUID(as_uuid=True), sa.ForeignKey("documents.id"), nullable=False),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("position", sa.Integer),
        sa.Column("section_path", sa.String),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("embedding", Vector(EMBED_DIM)),
        sa.Column("text_search", TSVECTOR),
        sa.Column("metadata", JSON),
        sa.Column("effective_date", sa.Date),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("chunks_tenant_idx", "chunks", ["tenant_id"])
    op.execute(
        "CREATE INDEX chunks_embedding_idx ON chunks USING hnsw (embedding vector_cosine_ops)"
    )
    op.create_index("chunks_text_search_idx", "chunks", ["text_search"], postgresql_using="gin")

    op.create_table(
        "authoritative_answers",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("canonical_question", sa.Text, nullable=False),
        sa.Column("canonical_question_embedding", Vector(EMBED_DIM)),
        sa.Column("answer", sa.Text, nullable=False),
        sa.Column("source_chunk_ids", ARRAY(UUID(as_uuid=True))),
        sa.Column("approved_by_id", UUID(as_uuid=True), sa.ForeignKey("users.id")),
        sa.Column("approved_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("internal_note", sa.Text),
        sa.Column("status", sa.String, server_default="active"),
        sa.Column("similarity_threshold", sa.Float, server_default="0.92"),
    )
    op.create_index("authoritative_tenant_idx", "authoritative_answers", ["tenant_id"])

    op.create_table(
        "queries",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id")),
        sa.Column("question", sa.Text, nullable=False),
        sa.Column("question_embedding", Vector(EMBED_DIM)),
        sa.Column("answer", sa.Text),
        sa.Column("source_chunk_ids", ARRAY(UUID(as_uuid=True))),
        sa.Column("confidence", sa.String),
        sa.Column("llm_used", sa.Boolean, server_default=sa.true()),
        sa.Column(
            "authoritative_answer_id",
            UUID(as_uuid=True),
            sa.ForeignKey("authoritative_answers.id"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("queries_tenant_idx", "queries", ["tenant_id"])

    op.create_table(
        "lexicon",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("term", sa.Text, nullable=False),
        sa.Column("expansion", sa.Text, nullable=False),
        sa.Column("notes", sa.Text),
        sa.Column("updated_by_id", UUID(as_uuid=True), sa.ForeignKey("users.id")),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
    )
    op.create_index("lexicon_tenant_idx", "lexicon", ["tenant_id"])


def downgrade() -> None:
    op.drop_table("lexicon")
    op.drop_table("queries")
    op.drop_table("authoritative_answers")
    op.drop_table("chunks")
    op.drop_table("documents")
    op.drop_table("users")
    op.drop_table("tenants")
