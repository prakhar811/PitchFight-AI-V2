"""PitchFight AI V2 FastAPI application entrypoint."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.v1.router import api_router
from app.core.config import settings
from app.database.mongo import close_mongo_client, ensure_indexes
from app.database.mongo import ping as ping_mongo
from app.database.redis import close_redis_client
from app.database.redis import ping as ping_redis


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None, None]:
    await ping_mongo()
    await ensure_indexes()
    await ping_redis()
    yield
    # Reverse of startup order.
    await close_redis_client()
    await close_mongo_client()


app = FastAPI(title=settings.APP_NAME, lifespan=lifespan)

app.include_router(api_router, prefix=settings.API_V1_PREFIX)
