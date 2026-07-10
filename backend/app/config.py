"""App configuration loaded from environment variables."""
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file="../.env", env_file_encoding="utf-8", extra="ignore")

    # Database
    database_url: str = "postgresql+psycopg://elrom:elrom@localhost:5433/elrom"

    @field_validator("database_url", mode="before")
    @classmethod
    def _normalize_db_url(cls, v: str) -> str:
        """Render exposes Postgres as postgresql:// — convert to the psycopg3 driver scheme."""
        if isinstance(v, str) and v.startswith("postgresql://"):
            return v.replace("postgresql://", "postgresql+psycopg://", 1)
        if isinstance(v, str) and v.startswith("postgres://"):
            return v.replace("postgres://", "postgresql+psycopg://", 1)
        return v

    # LLM
    anthropic_api_key: str = ""
    claude_answer_model: str = "claude-sonnet-4-6"
    claude_extract_model: str = "claude-haiku-4-5-20251001"

    # Embeddings
    embedding_provider: str = "cohere"  # "cohere" | "openai"
    cohere_api_key: str = ""
    cohere_embed_model: str = "embed-multilingual-v3.0"
    openai_api_key: str = ""
    openai_embed_model: str = "text-embedding-3-large"

    # Auth
    session_secret: str = "dev-secret-change-me"
    google_client_id: str = ""

    # Mail — Resend. Until the sender domain (klaser.co.il) verifies in the
    # Resend dashboard, use the shared onboarding sandbox address. Once
    # verified, flip MAIL_FROM_EMAIL to noreply@klaser.co.il.
    resend_api_key: str = ""
    mail_from_email: str = "onboarding@resend.dev"
    mail_from_name: str = "Klaser"
    magic_link_from_email: str = "noreply@elrom.tv"  # legacy — kept for compat
    # Public URL of the app — used to build clickable links in transactional
    # emails ("כניסה למערכת", "פתח בתור הבאגים"). Overridden in Render.
    # Public URL used in transactional email CTAs. Points at www because the
    # apex A record isn't saved at My Names yet; flip back to the apex once
    # the DNS row is committed at the registrar.
    klaser_app_url: str = "https://www.klaser.co.il"

    # App
    app_env: str = "development"
    log_level: str = "INFO"
    frontend_url: str = "http://localhost:5173"

    # OCR — Azure Document Intelligence (for scanned PDFs)
    azure_di_endpoint: str = ""
    azure_di_key: str = ""

    # Persistent file storage for original uploads (PDFs etc.). Served back
    # to the frontend via GET /api/documents/{id}/file so citations can open
    # the source document in-browser. On Render, this is a mounted disk
    # (see render.yaml). Locally, defaults to ./storage under backend/.
    storage_dir: str = "./storage"


settings = Settings()
