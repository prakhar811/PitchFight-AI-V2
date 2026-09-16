"""PitchFight AI V2 FastAPI application entrypoint."""

from fastapi import FastAPI

from app.api.v1.router import api_router
from app.core.config import settings

app = FastAPI(title=settings.APP_NAME)

app.include_router(api_router, prefix=settings.API_V1_PREFIX)
