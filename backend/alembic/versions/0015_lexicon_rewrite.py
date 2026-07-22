"""Lexicon rewrite — surface_forms, split expansions, entry_type, match events.

Turns the lexicon from "term + free-text expansion" into a proper glossary:

- surface_forms text[]: matchable variants (canonical first). Hebrew prefix
  letters (ה, ל, ב, ש, ו, מ, כ) don't survive substring matching, so the
  matcher now iterates a list of forms per entry. Backfill auto-generates
  common prefixed forms; reviewer edits down.
- entry_type varchar: definition | pointer | rule. Three distinct jobs the
  old free-text field was conflating.
- short_gloss text: reader-facing hover tooltip (one sentence).
- answerer_expansion text: renamed from `expansion`, kept for the LLM
  context injection. Split from short_gloss so the two consumers stop
  fighting over one field.

Also adds ``lexicon_match_event`` for stats (context = query|answer_render
|answerer_context) — feeds the "living asset" reviewer panel.

Revision ID: 0015_lexicon_rewrite
Revises: 0014_document_content_hash
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015_lexicon_rewrite"
down_revision: str | None = "0014_document_content_hash"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "lexicon",
        sa.Column(
            "surface_forms",
            sa.ARRAY(sa.Text()),
            nullable=False,
            server_default="{}",
        ),
    )
    op.add_column(
        "lexicon",
        sa.Column(
            "entry_type",
            sa.String(length=32),
            nullable=False,
            server_default="definition",
        ),
    )
    op.add_column("lexicon", sa.Column("short_gloss", sa.Text(), nullable=True))
    op.add_column("lexicon", sa.Column("answerer_expansion", sa.Text(), nullable=True))

    # Copy the old free-text `expansion` into `answerer_expansion` so nothing
    # breaks before the backfill script runs. `short_gloss` stays NULL — the
    # reviewer fills it in, or the auto-proposer generates it for new entries.
    op.execute(
        "UPDATE lexicon SET answerer_expansion = expansion WHERE answerer_expansion IS NULL"
    )
    # Seed surface_forms with the canonical term so the matcher works
    # immediately post-migration; scripts/backfill_lexicon.py enriches with
    # prefixed/inflected variants.
    op.execute(
        "UPDATE lexicon "
        "SET surface_forms = ARRAY[term] "
        "WHERE cardinality(surface_forms) = 0 AND term IS NOT NULL"
    )

    op.create_table(
        "lexicon_match_event",
        sa.Column(
            "id",
            sa.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("tenant_id", sa.UUID(as_uuid=True), nullable=False, index=True),
        sa.Column(
            "lexicon_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("lexicon.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("surface_form", sa.Text(), nullable=False),
        # "query"           — matched in a user question (retrieval-side)
        # "answer_render"   — matched in an answer for hover annotation
        # "answerer_context" — expansion was injected into the LLM prompt
        sa.Column("context", sa.String(length=32), nullable=False),
        sa.Column("query_id", sa.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_lexicon_match_event_lexicon_created",
        "lexicon_match_event",
        ["lexicon_id", "created_at"],
    )
    op.create_index(
        "ix_lexicon_match_event_tenant_created",
        "lexicon_match_event",
        ["tenant_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_lexicon_match_event_tenant_created", table_name="lexicon_match_event"
    )
    op.drop_index(
        "ix_lexicon_match_event_lexicon_created", table_name="lexicon_match_event"
    )
    op.drop_table("lexicon_match_event")
    op.drop_column("lexicon", "answerer_expansion")
    op.drop_column("lexicon", "short_gloss")
    op.drop_column("lexicon", "entry_type")
    op.drop_column("lexicon", "surface_forms")
