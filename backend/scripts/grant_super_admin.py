"""Grant or revoke cross-tenant read-only inspector ("super admin").

A super-admin can switch into any tenant via the UI tenant-switcher and view
its data + ask questions in search. They CANNOT write (upload, delete,
classify, approve, etc.) while in switch-mode — read-only enforced server-side.

Usage:
    cd backend
    .venv/bin/python -m scripts.grant_super_admin --email tal.gurevich@gmail.com
    .venv/bin/python -m scripts.grant_super_admin --email tal.gurevich@gmail.com --revoke

If the user doesn't exist yet, you must add them first:
    .venv/bin/python -m scripts.add_user --tenant-name "אל-רום" \\
        --email tal.gurevich@gmail.com --role admin --name "Tal Gurevich"
"""
import argparse
import sys

from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import User


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--email", required=True, help="User's email address")
    p.add_argument("--revoke", action="store_true", help="Remove super-admin instead of granting")
    args = p.parse_args()

    email = args.email.strip().lower()
    db: Session = SessionLocal()
    try:
        user = db.query(User).filter(User.email == email).first()
        if user is None:
            print(
                f"✗ No user found with email {email!r}. Create them first with "
                f"`scripts.add_user`.",
                file=sys.stderr,
            )
            sys.exit(2)

        was = user.is_super_admin
        user.is_super_admin = not args.revoke
        db.commit()
        if args.revoke:
            print(
                f"✓ Revoked super-admin from {email} "
                f"(was: {was}, now: False)."
            )
        else:
            print(
                f"✓ Granted super-admin to {email} "
                f"(was: {was}, now: True). They can now switch tenants in the UI."
            )
    finally:
        db.close()


if __name__ == "__main__":
    main()
