"""Google OAuth login (invite-only).

Flow: frontend uses Google Identity Services to obtain an ID token, POSTs it
here. We verify the token against Google's public keys, look up the user by
email — if they exist they're signed in (session cookie), otherwise rejected.
"""
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.models import User

router = APIRouter()


class GoogleLoginRequest(BaseModel):
    credential: str  # Google ID token (JWT) from GIS


class MeResponse(BaseModel):
    id: str
    email: str
    display_name: str | None
    role: str
    tenant_id: str


def _user_to_response(user: User) -> MeResponse:
    return MeResponse(
        id=str(user.id),
        email=user.email,
        display_name=user.display_name,
        role=user.role,
        tenant_id=str(user.tenant_id),
    )


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        request.session.clear()
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


@router.post("/google", response_model=MeResponse)
def google_login(
    payload: GoogleLoginRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> MeResponse:
    if not settings.google_client_id:
        raise HTTPException(500, "Google OAuth not configured on server")
    try:
        info = google_id_token.verify_oauth2_token(
            payload.credential,
            google_requests.Request(),
            settings.google_client_id,
        )
    except ValueError as e:
        raise HTTPException(401, f"Invalid Google credential: {e}") from e

    email = (info.get("email") or "").lower().strip()
    if not email or not info.get("email_verified"):
        raise HTTPException(401, "Google account email not verified")

    user = db.query(User).filter(User.email == email).first()
    if not user:
        raise HTTPException(
            403,
            "המשתמש לא קיים במערכת. פנה למנהל לקבלת הרשאה.",
        )

    if not user.display_name and info.get("name"):
        user.display_name = info["name"]
        db.commit()

    request.session["user_id"] = str(user.id)
    return _user_to_response(user)


@router.get("/me", response_model=MeResponse)
def me(user: User = Depends(current_user)) -> MeResponse:
    return _user_to_response(user)


@router.post("/logout")
def logout(request: Request) -> dict:
    request.session.clear()
    return {"status": "ok"}
