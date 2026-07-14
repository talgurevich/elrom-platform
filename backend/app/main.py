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
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.routes import (
    admin,
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


app = FastAPI(
    title="Klaser · Takanon",
    description="Kibbutz bylaws & decisions search — Takanon backend",
    version="0.4.0",
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
app.include_router(contact.router, prefix="/api", tags=["contact"])


@app.on_event("startup")
async def startup() -> None:
    log.info(
        "app.startup",
        env=settings.app_env,
        embedding_provider=settings.embedding_provider,
        identity_url=settings.identity_url,
    )
