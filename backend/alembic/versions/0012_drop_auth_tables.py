"""Drop the auth tables now that everything runs through klaser-identity.

Users, tenants, and auth_tokens moved to the identity service on
2026-07-14. Every read + write for those tables has since been rewired
through the identity SDK (see services/identity.py and route files).
This migration removes the last local traces:

  1. Drop every FK constraint elsewhere in the schema that pointed at
     users(id) or tenants(id). Column data (the UUIDs themselves) is
     preserved on every table — retrieval and admin flows still use
     them, they're just no longer database-enforced FKs.
  2. Drop auth_tokens (references users; cascade unused now).
  3. Drop users (references tenants).
  4. Drop tenants.

Point of no return: once committed, tenant + user data can only be
restored from the identity DB (which has been the source of truth
since cutover) or from a pre-migration Postgres snapshot.

Downgrade intentionally raises. This migration is not reversible in
any meaningful sense — the data would come back empty.

Revision ID: 0012_drop_auth_tables
Revises: 0011_password_auth
"""
from collections.abc import Sequence

from alembic import op

revision: str = "0012_drop_auth_tables"
down_revision: str | None = "0011_password_auth"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# (constraint_name, table_name) — enumerated from prod on 2026-07-15.
_FKS_TO_DROP = [
    ("amendments_tenant_id_fkey", "amendments"),
    ("authoritative_answers_tenant_id_fkey", "authoritative_answers"),
    ("authoritative_answers_approved_by_id_fkey", "authoritative_answers"),
    ("chunks_tenant_id_fkey", "chunks"),
    ("conversations_user_id_fkey", "conversations"),
    ("conversations_tenant_id_fkey", "conversations"),
    ("documents_tenant_id_fkey", "documents"),
    ("golden_questions_tenant_id_fkey", "golden_questions"),
    ("lexicon_tenant_id_fkey", "lexicon"),
    ("lexicon_updated_by_id_fkey", "lexicon"),
    ("queries_user_id_fkey", "queries"),
    ("queries_tenant_id_fkey", "queries"),
]


def upgrade() -> None:
    # 1. Drop external FKs. Use IF EXISTS so a partial re-run doesn't
    #    abort on a constraint that's already gone.
    for name, table in _FKS_TO_DROP:
        op.execute(f'ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {name}')

    # 2. auth_tokens → users FK is intrinsic to the table; drops with it.
    op.execute("DROP TABLE IF EXISTS auth_tokens")

    # 3. users → tenants FK is intrinsic to users; drops with it.
    op.execute("DROP TABLE IF EXISTS users")

    # 4. tenants last.
    op.execute("DROP TABLE IF EXISTS tenants")


def downgrade() -> None:
    raise NotImplementedError(
        "0012_drop_auth_tables is one-way. Restore from a Postgres "
        "snapshot taken before 2026-07-15 if you need the auth tables "
        "back locally."
    )
