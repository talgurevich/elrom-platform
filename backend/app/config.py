"""App configuration loaded from environment variables."""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file="../.env", env_file_encoding="utf-8", extra="ignore")

    # Database
    database_url: str = "postgresql+psycopg://elrom:elrom@localhost:5433/elrom"

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
    resend_api_key: str = ""
    magic_link_from_email: str = "noreply@elrom.tv"

    # App
    app_env: str = "development"
    log_level: str = "INFO"
    frontend_url: str = "http://localhost:5173"


settings = Settings()
