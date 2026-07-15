"""Klaser identity SDK — the thin HTTP client that replaces this backend's
local auth code with calls to the shared identity service.

Design
------

Every product backend authenticates the same way:

1. Browser sends a request to this backend with the `klaser_session`
   cookie attached (scoped to `.klaser.co.il`, so both this backend's
   subdomain and the identity subdomain see it).
2. This SDK's `current_user` dependency forwards the raw cookie to
   `GET https://auth.klaser.co.il/api/introspect`.
3. Identity decodes the session, looks up the user + tenant + active
   subscriptions, and returns them.
4. The SDK parses the response into an `IdentityUser` and returns it to
   the route handler.

Shape compatibility
-------------------

`IdentityUser` deliberately mirrors the field names of the old ORM
`User` model — `id: UUID`, `tenant_id: UUID`, `email`, `display_name`,
`role`, `is_super_admin` — so route handlers that used to type-hint
`user: User = Depends(current_user)` only need to swap the import and
the type name. New fields (`tenant_name`, `entitlements`,
`viewing_other_tenant`) live on top of that base shape.

Super-admin read-only enforcement
---------------------------------

When a super-admin is viewing another tenant, mutating requests are
blocked unless they match a small whitelist (search, tenant-switch,
logout). The old backend enforced this in an ASGI middleware that read
`request.session` directly. Post-cutover, this backend has no session
middleware, so we fold the check into `current_user`.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Callable
from uuid import UUID

import httpx
import structlog
from fastapi import HTTPException, Request

from app.config import settings

log = structlog.get_logger()


# Paths a super-admin in switch-mode may still POST to. Everything else
# (uploads, deletes, classifications, approvals, lexicon edits…) is
# blocked while viewing another tenant.
_SWITCH_MODE_POST_WHITELIST = {
    "/api/search",
    "/api/search/stream",
    "/api/auth/logout",  # also lives on identity, but harmless if hit here
}


def _is_allowed_in_switch_mode(method: str, path: str) -> bool:
    if method in ("GET", "HEAD", "OPTIONS"):
        return True
    if method != "POST":
        # No PUT/PATCH/DELETE allowed in switch mode.
        return False
    if path in _SWITCH_MODE_POST_WHITELIST:
        return True
    if path.startswith("/api/search/") and (
        path.endswith("/feedback") or path.endswith("/failure-mode")
    ):
        return True
    return False


@dataclass
class IdentityUser:
    """Shape returned by identity's `/api/introspect`. Field names
    intentionally match the old ORM `User` model so most call sites
    don't change beyond the import."""

    id: UUID
    email: str
    display_name: str | None
    role: str
    is_super_admin: bool
    tenant_id: UUID
    tenant_name: str | None
    entitlements: list[str] = field(default_factory=list)
    viewing_other_tenant: bool = False

    @classmethod
    def _from_response(cls, data: dict) -> "IdentityUser":
        return cls(
            id=UUID(data["user_id"]),
            email=data["email"],
            display_name=data.get("display_name"),
            role=data["role"],
            is_super_admin=bool(data.get("is_super_admin", False)),
            tenant_id=UUID(data["tenant_id"]),
            tenant_name=data.get("tenant_name"),
            entitlements=list(data.get("entitlements") or []),
            viewing_other_tenant=bool(data.get("viewing_other_tenant", False)),
        )


_CACHE_ATTR = "_klaser_identity_user"
_CACHE_MISS_ATTR = "_klaser_identity_miss"


def _identity_url() -> str:
    """Resolve at call time, not import time — env may be overridden per
    environment. Fallback matches production."""
    url = (getattr(settings, "identity_url", "") or "").strip()
    return url.rstrip("/") or "https://auth.klaser.co.il"


def _introspect(request: Request) -> IdentityUser:
    """Call identity `/api/introspect`, forwarding the session cookie.

    Cached on `request.state` so multiple deps in one request tree cost
    at most one round-trip. A 401 from identity is cached as a marker so
    we don't retry inside the same request.
    """
    cached = getattr(request.state, _CACHE_ATTR, None)
    if cached is not None:
        return cached
    if getattr(request.state, _CACHE_MISS_ATTR, False):
        raise HTTPException(status_code=401, detail="Not authenticated")

    if not request.cookies:
        setattr(request.state, _CACHE_MISS_ATTR, True)
        raise HTTPException(status_code=401, detail="Not authenticated")

    url = f"{_identity_url()}/api/introspect"
    try:
        resp = httpx.get(url, cookies=dict(request.cookies), timeout=5.0)
    except httpx.RequestError as e:
        log.warning("identity.introspect_transport_error", error=str(e), url=url)
        # Identity being down is a 503, not a 401 — we don't want the
        # frontend to log the user out on the assumption their session
        # expired when the real issue is infrastructure.
        raise HTTPException(status_code=503, detail="Auth service unavailable") from e

    if resp.status_code == 401:
        setattr(request.state, _CACHE_MISS_ATTR, True)
        raise HTTPException(status_code=401, detail="Not authenticated")
    if resp.status_code >= 400:
        log.warning(
            "identity.introspect_error",
            status=resp.status_code,
            body=resp.text[:500],
        )
        raise HTTPException(status_code=503, detail="Auth service error")

    user = IdentityUser._from_response(resp.json())
    setattr(request.state, _CACHE_ATTR, user)
    return user


def current_user(request: Request) -> IdentityUser:
    """FastAPI dependency — the primary auth entry point.

    Also enforces super-admin read-only mode: if the user is a
    super-admin currently viewing another tenant, mutating requests that
    aren't whitelisted 403. This replaces the old
    `enforce_super_admin_read_only` ASGI middleware which relied on the
    now-gone session middleware.
    """
    user = _introspect(request)
    if user.viewing_other_tenant and not _is_allowed_in_switch_mode(
        request.method, request.url.path
    ):
        raise HTTPException(
            status_code=403,
            detail=(
                "מצב צפייה בלבד (super-admin viewing another tenant). "
                "פעולת כתיבה זו חסומה. לחזרה לארגון הבית — לחץ 'חזור'."
            ),
        )
    return user


def require_entitlement(product: str) -> Callable[[Request], IdentityUser]:
    """FastAPI dependency factory — gates a route on the caller's tenant
    holding an active subscription for ``product``. Composes with the
    read-only check in ``current_user``."""

    def _dep(request: Request) -> IdentityUser:
        user = current_user(request)  # also enforces read-only
        if product not in user.entitlements:
            raise HTTPException(
                status_code=403,
                detail=(
                    f"אין למשתמש הרשאה למוצר '{product}'. "
                    "פנה למנהל הארגון להוספת מנוי."
                ),
            )
        return user

    return _dep


# ─────────────────────────────────────────────────────────────────────────
# Service-token client — for background jobs / cron / admin scripts that
# don't have a browser session to forward.
# ─────────────────────────────────────────────────────────────────────────


class IdentityServiceClient:
    """Thin wrapper over identity's `/api/service/*` endpoints. Uses the
    per-product service token from settings; instantiate once at module
    scope."""

    def __init__(self, base_url: str | None = None, token: str | None = None):
        self.base_url = (base_url or _identity_url()).rstrip("/")
        self.token = (token or getattr(settings, "identity_service_token", "") or "").strip()

    def _headers(self) -> dict[str, str]:
        if not self.token:
            raise RuntimeError(
                "IDENTITY_SERVICE_TOKEN not configured — service-token endpoints "
                "are unusable until the env var is set."
            )
        return {"Authorization": f"Bearer {self.token}"}

    # ─── Users ─────────────────────────────────────────────────────

    def list_users(self, *, tenant_id: str | None = None) -> list[dict]:
        params = {"tenant_id": tenant_id} if tenant_id else None
        r = httpx.get(
            f"{self.base_url}/api/service/users",
            headers=self._headers(),
            params=params,
            timeout=5.0,
        )
        r.raise_for_status()
        return r.json()

    def get_user(self, user_id: str) -> dict:
        r = httpx.get(
            f"{self.base_url}/api/service/users/{user_id}",
            headers=self._headers(),
            timeout=5.0,
        )
        r.raise_for_status()
        return r.json()

    def invite_user(
        self,
        *,
        email: str,
        tenant_id: str,
        role: str,
        display_name: str | None = None,
        invited_by: str | None = None,
        is_super_admin: bool = False,
    ) -> dict:
        r = httpx.post(
            f"{self.base_url}/api/service/users",
            headers=self._headers(),
            json={
                "email": email,
                "tenant_id": tenant_id,
                "role": role,
                "display_name": display_name,
                "invited_by": invited_by,
                "is_super_admin": is_super_admin,
            },
            timeout=10.0,
        )
        r.raise_for_status()
        return r.json()

    def update_user(
        self,
        user_id: str,
        *,
        role: str | None = None,
        display_name: str | None = None,
        tenant_id: str | None = None,
        is_super_admin: bool | None = None,
    ) -> dict:
        """PATCH — fields left as None are not touched on the server.
        Pass `display_name=""` to explicitly clear."""
        payload: dict = {}
        if role is not None:
            payload["role"] = role
        if display_name is not None:
            payload["display_name"] = display_name
        if tenant_id is not None:
            payload["tenant_id"] = tenant_id
        if is_super_admin is not None:
            payload["is_super_admin"] = is_super_admin
        r = httpx.patch(
            f"{self.base_url}/api/service/users/{user_id}",
            headers=self._headers(),
            json=payload,
            timeout=5.0,
        )
        r.raise_for_status()
        return r.json()

    def delete_user(self, user_id: str) -> None:
        r = httpx.delete(
            f"{self.base_url}/api/service/users/{user_id}",
            headers=self._headers(),
            timeout=5.0,
        )
        r.raise_for_status()

    def resend_invite(self, user_id: str) -> dict:
        r = httpx.post(
            f"{self.base_url}/api/service/users/{user_id}/resend-invite",
            headers=self._headers(),
            timeout=10.0,
        )
        r.raise_for_status()
        return r.json()

    # ─── Tenants ───────────────────────────────────────────────────

    def list_tenants(self) -> list[dict]:
        r = httpx.get(
            f"{self.base_url}/api/service/tenants",
            headers=self._headers(),
            timeout=5.0,
        )
        r.raise_for_status()
        return r.json()

    def get_tenant(self, tenant_id: str) -> dict:
        r = httpx.get(
            f"{self.base_url}/api/service/tenants/{tenant_id}",
            headers=self._headers(),
            timeout=5.0,
        )
        r.raise_for_status()
        return r.json()

    def update_tenant_system_context(
        self, tenant_id: str, system_context: str | None
    ) -> dict:
        """Set (or clear, if None) the tenant's system_context. Fully
        replaces — no partial semantics."""
        r = httpx.patch(
            f"{self.base_url}/api/service/tenants/{tenant_id}/system-context",
            headers=self._headers(),
            json={"system_context": system_context},
            timeout=5.0,
        )
        r.raise_for_status()
        return r.json()

    def create_tenant(
        self,
        *,
        name: str,
        segment: str,
        seed_default_subscription: bool = True,
    ) -> dict:
        r = httpx.post(
            f"{self.base_url}/api/service/tenants",
            headers=self._headers(),
            json={
                "name": name,
                "segment": segment,
                "seed_default_subscription": seed_default_subscription,
            },
            timeout=5.0,
        )
        r.raise_for_status()
        return r.json()

    def list_subscriptions(self, tenant_id: str) -> list[dict]:
        r = httpx.get(
            f"{self.base_url}/api/service/tenants/{tenant_id}/subscriptions",
            headers=self._headers(),
            timeout=5.0,
        )
        r.raise_for_status()
        return r.json()


identity_service = IdentityServiceClient()


# ─────────────────────────────────────────────────────────────────────────
# Tenant cache — the LLM answer-path needs tenant.name + system_context
# on every query. Hitting identity per query would be wasteful and slow.
# Small TTL cache lives per-worker in memory; a super-admin editing the
# system context sees the change on the next TTL boundary (or after an
# explicit invalidate).
# ─────────────────────────────────────────────────────────────────────────


_TENANT_CACHE_TTL_SECONDS = 300  # 5 minutes
_tenant_cache: dict[str, tuple[float, dict]] = {}
_tenant_cache_lock = threading.Lock()


def get_tenant_cached(tenant_id: str | UUID) -> dict | None:
    """Cached wrapper over identity_service.get_tenant. Returns the raw
    dict (id, name, segment, system_context) or None if identity 404s /
    the call fails — callers should degrade gracefully rather than 500.
    """
    key = str(tenant_id)
    now = time.time()
    with _tenant_cache_lock:
        cached = _tenant_cache.get(key)
        if cached is not None:
            ts, data = cached
            if now - ts < _TENANT_CACHE_TTL_SECONDS:
                return data
    try:
        data = identity_service.get_tenant(key)
    except Exception as e:  # noqa: BLE001 — never break the answer path
        log.warning("identity.get_tenant_cached_failed", tenant_id=key, error=str(e))
        return None
    with _tenant_cache_lock:
        _tenant_cache[key] = (now, data)
    return data


def invalidate_tenant_cache(tenant_id: str | UUID) -> None:
    """Called from admin panel writes so the next query sees the change
    without waiting for the TTL."""
    with _tenant_cache_lock:
        _tenant_cache.pop(str(tenant_id), None)
