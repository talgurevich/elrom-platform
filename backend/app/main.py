"""FastAPI application entry point."""
import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.routes import health, ingest, reviewer, search

log = structlog.get_logger()

app = FastAPI(
    title="Elrom Platform",
    description="Kibbutz bylaws & decisions search — backend",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_url],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router, prefix="/api", tags=["health"])
app.include_router(ingest.router, prefix="/api/ingest", tags=["ingest"])
app.include_router(search.router, prefix="/api/search", tags=["search"])
app.include_router(reviewer.router, prefix="/api/reviewer", tags=["reviewer"])


@app.on_event("startup")
async def startup() -> None:
    log.info("app.startup", env=settings.app_env, embedding_provider=settings.embedding_provider)
