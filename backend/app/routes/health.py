"""Health check — verifies DB connectivity."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db import get_db

router = APIRouter()


@router.get("/health")
def health(db: Session = Depends(get_db)) -> dict:
    """Health check including DB ping."""
    db.execute(text("SELECT 1"))
    return {"status": "ok"}


@router.post("/admin/seed-tenant")
def seed_tenant() -> dict:
    """Legacy dev-only bootstrap. Users + tenants moved to klaser-identity
    on 2026-07-14; seeding now happens against identity's DB via its own
    admin tools (or SQL). Left as 410 rather than removed entirely so any
    stale caller sees a clear reason rather than a mysterious 404."""
    raise HTTPException(
        status_code=410,
        detail=(
            "seed-tenant הועבר לשירות הזהויות. יש לזרוע ארגונים ומשתמשים "
            "דרך klaser-identity (או להשתמש ב-POST /admin/tenants בפאנל)."
        ),
    )
