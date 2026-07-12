"""FastAPI application entry point."""
import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.sessions import SessionMiddleware

from app.config import settings
from app.routes import (
    admin,
    auth,
    contact,
    conversations,
    documents,
    eval as eval_routes,
    health,
    ingest,
    reviewer,
    search,
)

log = structlog.get_logger()


# Paths a super-admin in switch-mode may still POST to. Everything else
# (uploads, deletes, classifications, approvals, lexicon edits…) is blocked
# while viewing another tenant — see auth.current_user for the override logic.
_SWITCH_MODE_POST_WHITELIST = {
    "/api/search",
    "/api/search/stream",
    "/api/auth/logout",
    "/api/auth/switch-tenant",
    "/api/auth/exit-switch",
}


def _is_allowed_in_switch_mode(method: str, path: str) -> bool:
    """Decide whether a request is allowed while super-admin is viewing
    another tenant. Read methods are always fine; mutating methods need to
    match the whitelist (literal paths, or /api/search/<id>/feedback or
    /failure-mode for in-flow query feedback)."""
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

app = FastAPI(
    title="Elrom Platform",
    description="Kibbutz bylaws & decisions search — backend",
    version="0.3.0",
)

_origins = [o.strip() for o in settings.frontend_url.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Cross-site session cookie: frontend and backend live on different Render
# subdomains, so the cookie must be SameSite=None + Secure.
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.session_secret,
    session_cookie="elrom_session",
    same_site="none",
    https_only=settings.app_env != "development",
    max_age=60 * 60 * 24 * 30,  # 30 days
)

@app.middleware("http")
async def enforce_super_admin_read_only(request: Request, call_next):
    """If the caller is a super-admin in switch-mode (session has both
    is_super_admin=True and viewing_tenant_id set), block mutating requests
    that aren't in the read-only whitelist."""
    session = request.scope.get("session") or {}
    if session.get("is_super_admin") and session.get("viewing_tenant_id"):
        if not _is_allowed_in_switch_mode(request.method, request.url.path):
            return JSONResponse(
                status_code=403,
                content={
                    "detail": (
                        "מצב צפייה בלבד (super-admin viewing another tenant). "
                        "פעולת כתיבה זו חסומה. לחזרה לארגון הבית — לחץ 'חזור'."
                    )
                },
            )
    return await call_next(request)


app.include_router(health.router, prefix="/api", tags=["health"])
app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(ingest.router, prefix="/api/ingest", tags=["ingest"])
app.include_router(search.router, prefix="/api/search", tags=["search"])
app.include_router(conversations.router, prefix="/api/conversations", tags=["conversations"])
app.include_router(reviewer.router, prefix="/api/reviewer", tags=["reviewer"])
app.include_router(documents.router, prefix="/api/documents", tags=["documents"])
app.include_router(eval_routes.router, prefix="/api/eval", tags=["eval"])
app.include_router(admin.router, prefix="/api/admin", tags=["admin"])
app.include_router(contact.router, prefix="/api", tags=["contact"])


@app.on_event("startup")
async def startup() -> None:
    log.info("app.startup", env=settings.app_env, embedding_provider=settings.embedding_provider)
