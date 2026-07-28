"""Decision chains + corpus reconciliation flags.

Two tables:

``decision_resolutions`` — one row per (escalation chunk → terminal
decision) link. An escalation chunk is a protocol item that ends with
"הוחלט להעביר לאסיפה" / "יובא לקלפי" — a decision to escalate, not a
decision on the substance. The terminal decision lives in a document
produced by a higher forum (committee → assembly → ballot). Retrieval
uses approved rows (needs_review=false) to expand any retrieved
escalation chunk with the terminal decision that resolved it — the
"kept but demoted" model: the escalation text stays visible, annotated,
while the terminal decision is injected as the binding source.

``corpus_flags`` — one row per reconciliation finding raised when a new
document is ingested and compared against the existing corpus:
contradicts / supersedes / duplicates. Surfaced in the reviewer queue;
never affects retrieval directly.

Revision ID: 0020_decision_chains_and_flags
Revises: 0019_query_analytics_indexes
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0020_decision_chains_and_flags"
down_revision: str | None = "0019_query_analytics_indexes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "decision_resolutions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "escalation_chunk_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("chunks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "escalation_doc_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "terminal_doc_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "terminal_chunk_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("chunks.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("topic", sa.Text(), nullable=True),
        sa.Column("evidence_span", sa.Text(), nullable=True),
        sa.Column("extractor_confidence", sa.Float(), nullable=True),
        sa.Column(
            "needs_review", sa.Boolean(), nullable=False, server_default="false"
        ),
        sa.Column("extractor_model", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_decision_resolutions_tenant",
        "decision_resolutions",
        ["tenant_id"],
    )
    op.create_index(
        "ix_decision_resolutions_escalation_chunk",
        "decision_resolutions",
        ["escalation_chunk_id"],
    )

    op.create_table(
        "corpus_flags",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "new_doc_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "existing_doc_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "new_chunk_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("chunks.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "existing_chunk_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("chunks.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("topic", sa.Text(), nullable=True),
        sa.Column("explanation", sa.Text(), nullable=True),
        sa.Column("evidence_new", sa.Text(), nullable=True),
        sa.Column("evidence_existing", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column(
            "status", sa.String(length=32), nullable=False, server_default="pending"
        ),
        sa.Column("extractor_model", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_corpus_flags_tenant_status",
        "corpus_flags",
        ["tenant_id", "status"],
    )
    op.create_index(
        "ix_corpus_flags_new_doc",
        "corpus_flags",
        ["new_doc_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_corpus_flags_new_doc", table_name="corpus_flags")
    op.drop_index("ix_corpus_flags_tenant_status", table_name="corpus_flags")
    op.drop_table("corpus_flags")
    op.drop_index(
        "ix_decision_resolutions_escalation_chunk", table_name="decision_resolutions"
    )
    op.drop_index("ix_decision_resolutions_tenant", table_name="decision_resolutions")
    op.drop_table("decision_resolutions")
