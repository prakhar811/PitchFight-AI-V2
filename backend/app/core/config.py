"""Application settings.

Exposes generic app configuration, PostgreSQL connection settings, JWT
authentication settings, MongoDB connection settings, and Redis live-state
settings. Inference settings will be added in later tasks.
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

    # JWT authentication — secret must come from the environment, never a
    # hardcoded default.
    JWT_SECRET_KEY: str
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60

    # MongoDB — durable conversation event history.
    MONGO_URL: str
    MONGO_DB: str

    # Redis — temporary live-state/cache layer only, never sole source of truth.
    REDIS_URL: str
    REDIS_SESSION_TTL_SECONDS: int = 86400
    REDIS_JUDGE_CONFIG_TTL_SECONDS: int = 10800
    REDIS_VOICE_TTL_SECONDS: int = 1200


settings = Settings()
