"""Application settings.

Exposes generic app configuration, PostgreSQL connection settings, JWT
authentication settings, MongoDB connection settings, Redis live-state
settings, and model-abstraction settings (default alias, plus the
Modal-hosted vLLM/Nemotron endpoint config for the real provider).
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

    # Model abstraction — which registered ModelRouter alias to use by
    # default. "fake" requires no external provider/credentials at all.
    MODEL_DEFAULT_ALIAS: str = "fake"

    # Real provider (Phase 12B) — the Modal-hosted vLLM/Nemotron endpoint
    # validated standalone in Phase 12A. All optional: importing Settings
    # (and running the test suite) never requires real credentials to
    # exist; a "nemotron" client just can't be constructed until they do.
    MODEL_NEMOTRON_BASE_URL: str | None = None
    MODEL_NEMOTRON_NAME: str = "pitchfight-nemotron"
    MODAL_KEY: str | None = None
    MODAL_SECRET: str | None = None
    MODEL_REQUEST_TIMEOUT: float = 30.0


settings = Settings()
