"""Add extraction telemetry to documents.

Revision ID: 0005_document_extraction_telemetry
Revises: 0004_golden_questions
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_doc_telemetry"
down_revision: str | None = "0004_golden_questions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("extractor", sa.String, nullable=True))
    op.add_column("documents", sa.Column("used_ocr", sa.Boolean, nullable=False, server_default=sa.false()))
    op.add_column("documents", sa.Column("pages", sa.Integer, nullable=True))
    op.add_column("documents", sa.Column("chars_extracted", sa.Integer, nullable=True))
    op.add_column("documents", sa.Column("chunks_created", sa.Integer, nullable=True))
    op.add_column("documents", sa.Column("extraction_partial", sa.Boolean, nullable=False, server_default=sa.false()))
    op.add_column("documents", sa.Column("extraction_note", sa.Text, nullable=True))


def downgrade() -> None:
    for col in (
        "extraction_note",
        "extraction_partial",
        "chunks_created",
        "chars_extracted",
        "pages",
        "used_ocr",
        "extractor",
    ):
        op.drop_column("documents", col)
