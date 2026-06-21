"""Google OAuth login (invite-only).

Flow: frontend uses Google Identity Services to obtain an ID token, POSTs it
here. We verify the token against Google's public keys, look up the user by
email — if they exist they're signed in (session cookie), otherwise rejected.

Super-admin tenant switching: a flagged user may set session.viewing_tenant_id
via POST /switch-tenant. While that's set, current_user swaps user.tenant_id
in memory for the request, and the middleware in app.main enforces read-only.
"""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.models import Tenant, User

router = APIRouter()


class GoogleLoginRequest(BaseModel):
    credential: str  # Google ID token (JWT) from GIS


class MeResponse(BaseModel):
    id: str
    email: str
    display_name: str | None
    role: str
    tenant_id: str            # the *effective* tenant — what the user is seeing
    tenant_name: str | None = None
    is_super_admin: bool = False
    home_tenant_id: str | None = None    # the user's actual tenant (when in switch-mode)
    home_tenant_name: str | None = None
    viewing_other_tenant: bool = False   # convenience for the UI banner


def _user_to_response(user: User, db: Session, *, request: Request | None = None) -> MeResponse:
    """Build the /me payload. When the super-admin is in switch-mode, the
    effective tenant (what they're viewing) is reported as tenant_id while
    the home_tenant_* fields carry their real account's tenant for context."""
    effective_tenant_id = user.tenant_id
    home_tenant_id = getattr(user, "_home_tenant_id", None) or effective_tenant_id
    viewing_other = bool(getattr(user, "_in_switch_mode", False))

    effective_tenant = db.get(Tenant, effective_tenant_id)
    home_tenant = (
        db.get(Tenant, home_tenant_id)
        if home_tenant_id != effective_tenant_id
        else effective_tenant
    )

    return MeResponse(
        id=str(user.id),
        email=user.email,
        display_name=user.display_name,
        role=user.role,
        tenant_id=str(effective_tenant_id),
        tenant_name=effective_tenant.name if effective_tenant else None,
        is_super_admin=user.is_super_admin,
        home_tenant_id=str(home_tenant_id),
        home_tenant_name=home_tenant.name if home_tenant else None,
        viewing_other_tenant=viewing_other,
    )


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    """Return the authenticated User. If they're a super-admin in switch-mode
    (session has a valid viewing_tenant_id), mutate user.tenant_id in memory
    so every downstream route reads the *viewed* tenant. The DB row is never
    written back — this is purely per-request.
    """
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        request.session.clear()
        raise HTTPException(status_code=401, detail="Not authenticated")

    # Cache the home tenant before we possibly swap it out.
    user._home_tenant_id = user.tenant_id  # type: ignore[attr-defined]
    user._in_switch_mode = False  # type: ignore[attr-defined]

    if user.is_super_admin:
        viewing = request.session.get("viewing_tenant_id")
        if viewing and viewing != str(user.tenant_id):
            try:
                viewing_uuid = UUID(viewing)
            except (ValueError, TypeError):
                viewing_uuid = None
            if viewing_uuid is not None and db.get(Tenant, viewing_uuid) is not None:
                user.tenant_id = viewing_uuid  # type: ignore[assignment]
                user._in_switch_mode = True  # type: ignore[attr-defined]

    # Expose switch-mode to the middleware via request.state (the middleware
    # runs before any Depends; we set this here so by the time a route handler
    # would otherwise process a write, we've already 403'd in middleware… but
    # actually middleware can't see request.state set in a dep. So the
    # middleware reads the session directly — this attr is just for handlers
    # that want to react in-handler.)
    request.state.in_switch_mode = user._in_switch_mode  # type: ignore[attr-defined]

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
    # Cache is_super_admin on the session so the middleware can enforce
    # read-only in switch-mode without a DB lookup on every request.
    request.session["is_super_admin"] = bool(user.is_super_admin)
    # Fresh login: clear any leftover viewing_tenant_id from a prior session.
    request.session.pop("viewing_tenant_id", None)
    return _user_to_response(user, db)


@router.get("/me", response_model=MeResponse)
def me(
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> MeResponse:
    return _user_to_response(user, db)


@router.post("/logout")
def logout(request: Request) -> dict:
    request.session.clear()
    return {"status": "ok"}


# ─────────────────────────────────────────────────────────────────────────
# Super-admin tenant switching
# ─────────────────────────────────────────────────────────────────────────


class SwitchTenantRequest(BaseModel):
    tenant_id: str


class TenantItem(BaseModel):
    id: str
    name: str
    segment: str


@router.get("/tenants", response_model=list[TenantItem])
def list_tenants_for_switcher(
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> list[TenantItem]:
    """List every tenant — only available to super-admins, drives the UI
    tenant-switcher dropdown."""
    if not user.is_super_admin:
        raise HTTPException(403, "Forbidden")
    rows = db.query(Tenant).order_by(Tenant.name).all()
    return [TenantItem(id=str(t.id), name=t.name, segment=t.segment) for t in rows]


@router.post("/switch-tenant", response_model=MeResponse)
def switch_tenant(
    req: SwitchTenantRequest,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> MeResponse:
    """Set session.viewing_tenant_id. Super-admin only. Refreshing the page
    or calling /me will now reflect the new tenant. While set, the request
    middleware blocks every write outside the search whitelist."""
    if not user.is_super_admin:
        raise HTTPException(403, "Forbidden")
    try:
        tid = UUID(req.tenant_id)
    except (ValueError, TypeError) as e:
        raise HTTPException(400, "Invalid tenant_id") from e
    tenant = db.get(Tenant, tid)
    if tenant is None:
        raise HTTPException(404, "Tenant not found")

    # Switching to your own home tenant is the same as exiting switch mode.
    home_id = getattr(user, "_home_tenant_id", user.tenant_id)
    if str(tid) == str(home_id):
        request.session.pop("viewing_tenant_id", None)
    else:
        request.session["viewing_tenant_id"] = str(tid)

    # Re-resolve current_user against the new session value so the response
    # reflects the just-applied switch.
    fresh_user = db.query(User).filter(User.id == user.id).first()
    fresh_user._home_tenant_id = home_id  # type: ignore[attr-defined]
    fresh_user._in_switch_mode = (str(tid) != str(home_id))  # type: ignore[attr-defined]
    if fresh_user._in_switch_mode:
        fresh_user.tenant_id = tid  # type: ignore[assignment]
    return _user_to_response(fresh_user, db, request=request)


@router.post("/exit-switch", response_model=MeResponse)
def exit_switch(
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> MeResponse:
    """Clear the session viewing_tenant_id — return to the user's home tenant."""
    request.session.pop("viewing_tenant_id", None)
    # Reset the in-memory flag too so the response reflects the exit.
    user._in_switch_mode = False  # type: ignore[attr-defined]
    user.tenant_id = getattr(user, "_home_tenant_id", user.tenant_id)  # type: ignore[assignment]
    return _user_to_response(user, db, request=request)
