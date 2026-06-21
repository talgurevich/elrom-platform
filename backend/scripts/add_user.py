"""Add a user to an existing tenant.

Usage:
    cd backend
    .venv/bin/python -m scripts.add_user \\
        --tenant-name "קיבוץ דגניה" \\
        --email reviewer@degania.tv \\
        --role reviewer \\
        [--name "שם תצוגה"]

The user signs in via Google with the matching email and lands in that tenant.
"""
import argparse
import sys

from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import Tenant, User


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--tenant-name", required=True, help="Name of the existing tenant")
    p.add_argument("--email", required=True, help="Google email of the new user")
    p.add_argument("--role", default="reviewer", choices=("admin", "reviewer", "secretary"))
    p.add_argument("--name", default=None, help="Display name (optional)")
    args = p.parse_args()

    email = args.email.strip().lower()
    if not email or "@" not in email:
        print(f"Invalid email: {email!r}", file=sys.stderr)
        sys.exit(1)

    db: Session = SessionLocal()
    try:
        tenant = db.query(Tenant).filter(Tenant.name == args.tenant_name).first()
        if tenant is None:
            print(
                f"✗ Tenant {args.tenant_name!r} not found. Use create_tenant.py first.",
                file=sys.stderr,
            )
            sys.exit(2)

        existing = db.query(User).filter(User.email == email).first()
        if existing is not None:
            print(
                f"✗ User {email} already exists (tenant_id={existing.tenant_id}). "
                f"To move a user across tenants, delete first.",
                file=sys.stderr,
            )
            sys.exit(3)

        u = User(tenant_id=tenant.id, email=email, display_name=args.name, role=args.role)
        db.add(u)
        db.commit()
        print(f"✓ Added {args.role}: {u.id}  email={email}  tenant={tenant.name!r}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
