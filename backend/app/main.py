"""FastAPI application entry point.

Post-identity-cutover: this backend no longer manages sessions itself.
Auth flows (Google OAuth, register, login, forgot/reset) all live in the
`klaser-identity` service. Every request here carries the shared
`klaser_session` cookie (scoped to `.klaser.co.il`); the SDK in
`app.services.identity` forwards it to identity's `/api/introspect` on
each request and gets back the caller's user + tenant + entitlements.

Super-admin switch-mode read-only enforcement moved from an ASGI
middleware into the SDK's `current_user` dep — see
`app.services.identity._is_allowed_in_switch_mode`.
"""
import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import settings
from app.routes import (
    admin,
    analytics,
    contact,
    conversations,
    documents,
    eval as eval_routes,
    health,
    ingest,
    reviewer,
    search,
    support,
)

log = structlog.get_logger()


app = FastAPI(
    title="Klaser · Takanon",
    description="Kibbutz bylaws & decisions search — Takanon backend",
    version="0.4.0",
)

# Registered BEFORE CORSMiddleware so it ends up *inside* it: Starlette's
# own 500 handler sits outside the user middleware stack, so an unhandled
# exception returns a response with no Access-Control-Allow-Origin and the
# browser reports every server error as an opaque "Failed to fetch".
@app.middleware("http")
async def unhandled_errors_as_json(request: Request, call_next):
    try:
        return await call_next(request)
    except Exception as exc:
        log.exception("unhandled_error", path=request.url.path, method=request.method)
        return JSONResponse(
            status_code=500,
            content={"detail": f"{type(exc).__name__}: {str(exc)[:500]}"},
        )


_origins = [o.strip() for o in settings.frontend_url.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(health.router, prefix="/api", tags=["health"])
app.include_router(ingest.router, prefix="/api/ingest", tags=["ingest"])
app.include_router(search.router, prefix="/api/search", tags=["search"])
app.include_router(conversations.router, prefix="/api/conversations", tags=["conversations"])
app.include_router(reviewer.router, prefix="/api/reviewer", tags=["reviewer"])
app.include_router(documents.router, prefix="/api/documents", tags=["documents"])
app.include_router(eval_routes.router, prefix="/api/eval", tags=["eval"])
app.include_router(admin.router, prefix="/api/admin", tags=["admin"])
app.include_router(analytics.router, prefix="/api/admin/analytics", tags=["analytics"])
app.include_router(contact.router, prefix="/api", tags=["contact"])
app.include_router(support.router, prefix="/api/support", tags=["support"])


@app.on_event("startup")
async def startup() -> None:
    log.info(
        "app.startup",
        env=settings.app_env,
        embedding_provider=settings.embedding_provider,
        identity_url=settings.identity_url,
    )
