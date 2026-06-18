"""Health check — verifies DB connectivity."""
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db import get_db

router = APIRouter()


@router.get("/health")
def health(db: Session = Depends(get_db)) -> dict:
    """Health check including DB ping."""
    db.execute(text("SELECT 1"))
    return {"status": "ok"}
