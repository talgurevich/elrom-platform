"""Health check — verifies DB connectivity."""
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Tenant, User

router = APIRouter()

# Bootstrap admin emails — added on every /admin/seed-tenant call. Idempotent.
BOOTSTRAP_ADMINS = [
    ("dev@elrom.local", "Dev Admin"),
    ("tal.gurevich@gmail.com", "Tal Gurevich"),
    ("noam@elrom.tv", "Noam"),
]


@router.get("/health")
def health(db: Session = Depends(get_db)) -> dict:
    """Health check including DB ping."""
    db.execute(text("SELECT 1"))
    return {"status": "ok"}


@router.post("/admin/seed-tenant")
def seed_tenant(db: Session = Depends(get_db)) -> dict:
    tenant = db.query(Tenant).first()
    if not tenant:
        tenant = Tenant(name="קיבוץ רביבים (dev)", segment="kibbutz_shitufi")
        db.add(tenant)
        db.flush()

    added: list[str] = []
    for email, display_name in BOOTSTRAP_ADMINS:
        email_norm = email.lower().strip()
        existing = db.query(User).filter(User.email == email_norm).first()
        if existing:
            continue
        db.add(
            User(
                tenant_id=tenant.id,
                email=email_norm,
                display_name=display_name,
                role="admin",
            )
        )
        added.append(email_norm)
    db.commit()

    return {
        "status": "ok",
        "tenant_id": str(tenant.id),
        "admins_added": added,
        "admins_total": db.query(User).count(),
    }
