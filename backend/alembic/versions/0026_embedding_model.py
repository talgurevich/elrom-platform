"""Track which embedding model produced each document's chunk vectors.

Vectors carried no record of their producing model, so switching provider
(Cohere → OpenAI) or model version would silently mix incompatible vector
spaces in one HNSW index. With the marker, a switch becomes a measurable
migration: re-embed WHERE embedding_model != current, verify counts, done.

Backfill: existing rows get the current configured model — correct as
long as the switch hasn't happened yet, which is exactly the window in
which this migration runs.

Revision ID: 0026_embedding_model
Revises: 0025_ingest_jobs
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0026_embedding_model"
down_revision: str | None = "0025_ingest_jobs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column("embedding_model", sa.String(64), nullable=True),
    )
    # Backfill with the current production model. Hardcoded (not read from
    # config) so the migration is deterministic — it documents what was
    # true at migration time.
    op.execute(
        "UPDATE documents SET embedding_model = 'cohere/embed-multilingual-v3.0' "
        "WHERE embedding_model IS NULL"
    )


def downgrade() -> None:
    op.drop_column("documents", "embedding_model")
