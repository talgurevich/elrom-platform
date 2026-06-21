"""Provision a new tenant + first admin user. Idempotent on email.

Usage:
    cd backend
    .venv/bin/python -m scripts.create_tenant \\
        --name "קיבוץ דגניה" \\
        --segment kibbutz_mitchadesh \\
        --admin-email admin@degania.tv \\
        [--admin-name "ראש המזכירות"]

After this, the admin user can sign in via Google with the matching email
and will land in the new tenant. Add more users with --extra-email later.
"""
import argparse
import sys

from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import Tenant, User

VALID_SEGMENTS = {"kibbutz_shitufi", "kibbutz_mitchadesh", "moshav"}


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--name", required=True, help="Display name of the tenant (e.g. 'קיבוץ דגניה')")
    p.add_argument(
        "--segment",
        required=True,
        choices=sorted(VALID_SEGMENTS),
        help="Tenant segment — drives default prompt tuning, billing tier",
    )
    p.add_argument("--admin-email", required=True, help="Google email of the first admin user")
    p.add_argument("--admin-name", default=None, help="Display name for the admin (optional)")
    p.add_argument(
        "--role",
        default="admin",
        choices=("admin", "reviewer", "secretary"),
        help="Role of the first user (default: admin)",
    )
    args = p.parse_args()

    email = args.admin_email.strip().lower()
    if not email or "@" not in email:
        print(f"Invalid email: {email!r}", file=sys.stderr)
        sys.exit(1)

    db: Session = SessionLocal()
    try:
        # Refuse if the email is already mapped to a different tenant — we don't
        # want to silently move users across tenants.
        existing = db.query(User).filter(User.email == email).first()
        if existing is not None:
            print(
                f"✗ User {email} already exists (id={existing.id}, "
                f"tenant_id={existing.tenant_id}). Aborting — pick a different "
                f"admin email or remove the existing user first.",
                file=sys.stderr,
            )
            sys.exit(2)

        # Refuse if a tenant with the same name already exists — almost certainly a typo / re-run.
        if db.query(Tenant).filter(Tenant.name == args.name).first() is not None:
            print(
                f"✗ Tenant named {args.name!r} already exists. Pick a unique "
                f"name or delete the existing one first.",
                file=sys.stderr,
            )
            sys.exit(3)

        tenant = Tenant(name=args.name, segment=args.segment)
        db.add(tenant)
        db.flush()

        admin = User(
            tenant_id=tenant.id,
            email=email,
            display_name=args.admin_name,
            role=args.role,
        )
        db.add(admin)
        db.commit()

        print(f"✓ Created tenant: {tenant.id}  name={args.name!r}  segment={args.segment}")
        print(f"✓ Created {args.role}: {admin.id}  email={email}")
        print()
        print("Next steps:")
        print(f"  1. {email} signs into the app via Google → lands in this tenant.")
        print("  2. They upload documents, ask questions, etc. — fully isolated from other tenants.")
        print("  3. To add more users, run this script again with --admin-email (they share the tenant).")
    finally:
        db.close()


if __name__ == "__main__":
    main()
