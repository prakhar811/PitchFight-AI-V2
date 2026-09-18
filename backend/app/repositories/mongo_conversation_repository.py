"""Concrete ConversationRepository backed by MongoDB.

    SimulationService (future)
            v
    ConversationRepository (contract)
            v
    MongoConversationRepository (this module)
            v
    MongoDB — collection `simulation_conversations`
"""

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pymongo import ReturnDocument
from pymongo.asynchronous.collection import AsyncCollection
from pymongo.errors import DuplicateKeyError

from app.repositories.base import clamp_limit
from app.repositories.conversation_repository import (
    ConversationDocument,
    ConversationEvent,
    ConversationNotFoundError,
    ConversationRepository,
)

SCHEMA_VERSION = 1


def _bson_safe(value: Any) -> Any:
    """Normalize a value for BSON storage.

    UUID -> str, Enum -> its .value, recursing through dicts/lists.
    Everything else (str/int/float/bool/None/datetime) is already
    BSON-native and passes through unchanged.
    """
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {key: _bson_safe(val) for key, val in value.items()}
    if isinstance(value, (list, tuple)):
        return [_bson_safe(item) for item in value]
    return value


def _to_conversation_document(raw: dict[str, Any]) -> ConversationDocument:
    return ConversationDocument(
        simulation_id=raw["simulation_id"],
        schema_version=raw["schema_version"],
        events=raw.get("events", []),
        created_at=raw["created_at"],
        updated_at=raw["updated_at"],
    )


class MongoConversationRepository(ConversationRepository):
    def __init__(self, collection: AsyncCollection) -> None:
        self._collection = collection

    async def create_for_simulation(self, simulation_id: uuid.UUID) -> ConversationDocument:
        sim_id = str(simulation_id)
        now = datetime.now(timezone.utc)
        try:
            await self._collection.update_one(
                {"simulation_id": sim_id},
                {
                    "$setOnInsert": {
                        "simulation_id": sim_id,
                        "schema_version": SCHEMA_VERSION,
                        "events": [],
                        "created_at": now,
                        "updated_at": now,
                    }
                },
                upsert=True,
            )
        except DuplicateKeyError:
            # Another concurrent call created it first — idempotent either way.
            pass

        document = await self._collection.find_one({"simulation_id": sim_id})
        if document is None:
            raise RuntimeError(f"Conversation for simulation_id={sim_id} vanished after upsert")
        return _to_conversation_document(document)

    async def get_by_simulation_id(
        self, simulation_id: uuid.UUID
    ) -> ConversationDocument | None:
        document = await self._collection.find_one({"simulation_id": str(simulation_id)})
        if document is None:
            return None
        return _to_conversation_document(document)

    async def append_event(
        self, simulation_id: uuid.UUID, event: ConversationEvent
    ) -> ConversationEvent:
        sim_id = str(simulation_id)
        now = datetime.now(timezone.utc)

        # event_id/sequence/created_at are always persistence-assigned —
        # see the contract note in conversation_repository.py.
        stored_event = _bson_safe(dict(event))
        stored_event.pop("sequence", None)
        stored_event.pop("event_id", None)
        stored_event.pop("created_at", None)
        stored_event["event_id"] = str(uuid.uuid4())
        stored_event["created_at"] = now

        # Atomic aggregation-pipeline update: `sequence` is computed
        # server-side from the array's current length at the moment this
        # single-document write applies, so concurrent appends can never
        # race each other into assigning the same sequence — MongoDB
        # serializes writes to one document. One round trip: the same
        # operation both writes and returns the persisted event.
        result_doc = await self._collection.find_one_and_update(
            {"simulation_id": sim_id},
            [
                {
                    "$set": {
                        "events": {
                            "$concatArrays": [
                                "$events",
                                [
                                    {
                                        "$mergeObjects": [
                                            stored_event,
                                            {"sequence": {"$add": [{"$size": "$events"}, 1]}},
                                        ]
                                    }
                                ],
                            ]
                        },
                        "updated_at": now,
                    }
                }
            ],
            projection={"events": {"$slice": -1}, "_id": 0},
            return_document=ReturnDocument.AFTER,
        )

        if result_doc is None:
            raise ConversationNotFoundError(
                f"No conversation document exists for simulation_id={sim_id}"
            )
        return result_doc["events"][0]

    async def delete_by_simulation_id(self, simulation_id: uuid.UUID) -> None:
        await self._collection.delete_one({"simulation_id": str(simulation_id)})

    async def get_latest_events(
        self, simulation_id: uuid.UUID, limit: int = 20
    ) -> list[ConversationEvent]:
        document = await self._collection.find_one(
            {"simulation_id": str(simulation_id)},
            projection={"events": {"$slice": -clamp_limit(limit)}, "_id": 0},
        )
        if document is None:
            return []
        return document.get("events", [])
