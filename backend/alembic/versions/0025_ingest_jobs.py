"""Server-side ingestion job queue.

Moves upload processing out of the HTTP request: POST /upload-async
persists the raw file + inserts a queued row here; the in-process worker
claims rows (FOR UPDATE SKIP LOCKED) and runs the shared pipeline. See
services/ingest_worker.py.

Revision ID: 0025_ingest_jobs
Revises: 0024_eval_runs
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0025_ingest_jobs"
down_revision: str | None = "0024_eval_runs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ingest_jobs",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", sa.UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("filename", sa.String, nullable=False),
        sa.Column("suffix", sa.String(16), nullable=False),
        sa.Column("stored_path", sa.String, nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=True),
        sa.Column("prefer_ocr", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("auto_classify", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("doc_type", sa.String(32), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="queued", index=True),
        sa.Column("stage", sa.String(24), nullable=True),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column("document_id", sa.UUID(as_uuid=True), nullable=True),
        sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("ingest_jobs")
