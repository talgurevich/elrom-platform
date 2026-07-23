"""Idempotency table for upload retries.

Stores (tenant_id, key) → stored response for a bounded window. Client
generates a UUID per upload *attempt* and includes it as
``X-Idempotency-Key``. Network retry / duplicate submission with the
same key returns the stored response instead of re-processing.

Distinct from content_sha256 dedup: content_sha256 catches "same bytes
uploaded again" (typically hours/days apart, unrelated attempt).
Idempotency-Key catches "same *attempt* replayed" (typically seconds
apart, network flake or double click).

Rows auto-prune after 24h via the nightly learn_lexicon script (piggy-
backing since we're there already for match-event pruning).

Revision ID: 0017_upload_idempotency
Revises: 0016_folder_taxonomy
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017_upload_idempotency"
down_revision: str | None = "0016_folder_taxonomy"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "upload_idempotency",
        sa.Column(
            "id",
            sa.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("tenant_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("key", sa.String(length=128), nullable=False),
        sa.Column(
            "document_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("documents.id", ondelete="SET NULL"),
            nullable=True,
        ),
        # Stored response body (JSON) so a retry gets byte-identical output.
        sa.Column("response_json", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    # (tenant_id, key) unique — the whole point of idempotency.
    op.create_index(
        "ix_upload_idempotency_tenant_key",
        "upload_idempotency",
        ["tenant_id", "key"],
        unique=True,
    )
    op.create_index(
        "ix_upload_idempotency_created",
        "upload_idempotency",
        ["created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_upload_idempotency_created", table_name="upload_idempotency")
    op.drop_index("ix_upload_idempotency_tenant_key", table_name="upload_idempotency")
    op.drop_table("upload_idempotency")
