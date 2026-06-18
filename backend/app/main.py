"""FastAPI application entry point."""
import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware

from app.config import settings
from app.routes import auth, documents, eval as eval_routes, health, ingest, reviewer, search

log = structlog.get_logger()

app = FastAPI(
    title="Elrom Platform",
    description="Kibbutz bylaws & decisions search — backend",
    version="0.1.0",
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

app.include_router(health.router, prefix="/api", tags=["health"])
app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(ingest.router, prefix="/api/ingest", tags=["ingest"])
app.include_router(search.router, prefix="/api/search", tags=["search"])
app.include_router(reviewer.router, prefix="/api/reviewer", tags=["reviewer"])
app.include_router(documents.router, prefix="/api/documents", tags=["documents"])
app.include_router(eval_routes.router, prefix="/api/eval", tags=["eval"])


@app.on_event("startup")
async def startup() -> None:
    log.info("app.startup", env=settings.app_env, embedding_provider=settings.embedding_provider)
