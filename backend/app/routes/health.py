"""Health check — verifies DB connectivity."""
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Tenant, User

router = APIRouter()


@router.get("/health")
def health(db: Session = Depends(get_db)) -> dict:
    """Health check including DB ping."""
    db.execute(text("SELECT 1"))
    return {"status": "ok"}


@router.post("/admin/seed-tenant")
def seed_tenant(db: Session = Depends(get_db)) -> dict:
    existing = db.query(Tenant).first()
    if existing:
        return {"status": "exists", "tenant_id": str(existing.id)}
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
    return {"status": "created", "tenant_id": str(tenant.id)}
