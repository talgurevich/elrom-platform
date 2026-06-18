"""Seed a default tenant + admin user for local development.

Run: cd backend && .venv/bin/python -m scripts.seed_dev
"""
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import Tenant, User


def main() -> None:
    db: Session = SessionLocal()
    try:
        if db.query(Tenant).first():
            print("Tenant already exists, skipping.")
            return

        tenant = Tenant(name="קיבוץ רביבים (dev)", segment="kibbutz_shitufi")
        db.add(tenant)
        db.flush()

        admin = User(
            tenant_id=tenant.id,
            email="dev@elrom.local",
            display_name="Dev Admin",
            role="admin",
        )
        db.add(admin)
        db.commit()

        print(f"Created tenant {tenant.id} and admin {admin.email}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
