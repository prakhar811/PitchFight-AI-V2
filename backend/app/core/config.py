"""Application settings.

This phase exposes generic app configuration plus PostgreSQL connection
settings. Auth and inference settings will be added in later tasks.
"""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/app/core/config.py -> repo root is three levels up from backend/.
_REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    """Safe generic application configuration."""

    model_config = SettingsConfigDict(
        env_file=_REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    APP_NAME: str = "PitchFight AI"
    APP_ENV: str = "development"
    API_V1_PREFIX: str = "/api/v1"

    # PostgreSQL — asyncpg driver, no sync fallback configured.
    DATABASE_URL: str


settings = Settings()
