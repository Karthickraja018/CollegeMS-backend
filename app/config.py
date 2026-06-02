from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # App
    app_env: str = "development"
    app_secret_key: str = "change-me"

    # Database
    database_url: str = "postgresql+asyncpg://postgres:password@localhost:5432/collegems"

    # JWT
    jwt_secret_key: str = "change-me-jwt"
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 60
    jwt_refresh_token_expire_days: int = 7

    # AI Provider
    llm_provider: str = "nvidia"
    nvidia_api_key: str = ""
    nvidia_model: str = "meta/llama-3.1-70b-instruct"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-1.5-pro"
    openai_api_key: str = ""
    anthropic_api_key: str = "" #   
    groq_api_key: str = ""
    groq_model: str = "llama-3.3-70b-versatile"

    # CORS
    frontend_url: str = "http://localhost:3000"

    # Reports
    reports_dir: str = "./reports"

    # ── Agent Intelligence Layer ───────────────────────────────────────
    # EMBEDDING_PROVIDER: gemini | groq | openai | nvidia
    embedding_provider: str = "gemini"
    # Override model name; leave blank to use provider default
    embedding_model: str = ""
    # Groq-specific embedding model
    groq_embedding_model: str = "nomic-embed-text"
    # Top-K results to retrieve per search type
    intelligence_top_k: int = 10
    # Minimum cosine similarity score for retrieval
    intelligence_score_threshold: float = 0.60
    # Context cache TTL in seconds
    intelligence_cache_ttl: int = 300


@lru_cache
def get_settings() -> Settings:
    return Settings()
