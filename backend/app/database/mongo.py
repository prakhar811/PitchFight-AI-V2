"""MongoDB connection layer: async client lifecycle, database/collection
access, and index initialization.

Infrastructure only — no ConversationRepository business logic here. Uses
PyMongo's native async API (pymongo>=4.9 ships AsyncMongoClient), so no
separate Motor dependency is needed.
"""

from pymongo import AsyncMongoClient
from pymongo.asynchronous.collection import AsyncCollection
from pymongo.asynchronous.database import AsyncDatabase

from app.core.config import settings

CONVERSATIONS_COLLECTION = "simulation_conversations"

_client: AsyncMongoClient | None = None


def get_mongo_client() -> AsyncMongoClient:
    """Lazily create the process-wide async Mongo client.

    tz_aware=True so datetimes read back from Mongo are timezone-aware UTC
    (PyMongo's default is naive datetimes, which would silently break
    comparisons against `datetime.now(timezone.utc)` elsewhere).
    """
    global _client
    if _client is None:
        _client = AsyncMongoClient(settings.MONGO_URL, tz_aware=True)
    return _client


def get_database() -> AsyncDatabase:
    return get_mongo_client()[settings.MONGO_DB]


def get_conversations_collection() -> AsyncCollection:
    return get_database()[CONVERSATIONS_COLLECTION]


async def ping() -> None:
    """Startup connectivity check."""
    await get_mongo_client().admin.command("ping")


async def ensure_indexes() -> None:
    """Idempotent index setup — safe to call on every application startup."""
    await get_conversations_collection().create_index(
        "simulation_id", unique=True, name="uq_simulation_conversations_simulation_id"
    )


async def close_mongo_client() -> None:
    global _client
    if _client is not None:
        await _client.close()
        _client = None
