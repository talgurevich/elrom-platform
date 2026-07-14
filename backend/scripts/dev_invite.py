"""One-off local helper: creates (or reuses) a dev tenant + user and prints
a ready-to-use registration link, without needing Google OAuth configured.

Run: cd backend && .venv/bin/python -m scripts.dev_invite [email]
"""
import sys
from datetime import timedelta

from sqlalchemy.orm import Session

from app.config import settings
from app.db import SessionLocal
from app.models import Tenant, User
from app.services.tokens import PURPOSE_REGISTRATION, issue_token


def main() -> None:
    email = (sys.argv[1] if len(sys.argv) > 1 else "dev-test@elrom.local").lower().strip()

    db: Session = SessionLocal()
    try:
        tenant = db.query(Tenant).first()
        if tenant is None:
            tenant = Tenant(name="קיבוץ רביבים (dev)", segment="kibbutz_shitufi")
            db.add(tenant)
            db.flush()
            print(f"Created tenant {tenant.id} ({tenant.name})")
        else:
            print(f"Using existing tenant {tenant.id} ({tenant.name})")

        user = db.query(User).filter(User.email == email).first()
        if user is None:
            user = User(
                tenant_id=tenant.id,
                email=email,
                display_name=None,
                role="admin",
            )
            db.add(user)
            db.commit()
            db.refresh(user)
            print(f"Created user {user.email}")
        else:
            print(f"Using existing user {user.email} (has_password={user.password_hash is not None})")

        raw_token = issue_token(
            db,
            user_id=user.id,
            purpose=PURPOSE_REGISTRATION,
            ttl=timedelta(days=settings.registration_token_ttl_days),
        )
        url = f"{settings.klaser_app_url.rstrip('/')}/register?token={raw_token}"
        print("\nOpen this in your browser:\n")
        print(url)
        print()
    finally:
        db.close()


if __name__ == "__main__":
    main()
