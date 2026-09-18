"""MongoConversationRepository integration tests against real MongoDB.

Runs against the isolated `pitchfight_test` database (see the
mongo_conversations_collection fixture in conftest.py) so these tests never
touch real dev conversation data. Each test cleans up its own document by a
unique simulation_id; the fixture also drops the whole test database once
at session end as a safety net.
"""

import asyncio
import uuid
from datetime import datetime, timezone

import pytest
from pymongo.asynchronous.collection import AsyncCollection
from pymongo.errors import DuplicateKeyError

from app.repositories import ConversationNotFoundError, MongoConversationRepository


@pytest.fixture
def repo(mongo_conversations_collection: AsyncCollection) -> MongoConversationRepository:
    return MongoConversationRepository(mongo_conversations_collection)


def _new_sim_id() -> uuid.UUID:
    return uuid.uuid4()


# ---------------------------------------------------------------------------
# create_for_simulation
# ---------------------------------------------------------------------------


async def test_create_for_simulation_stores_expected_fields(
    repo: MongoConversationRepository, mongo_conversations_collection: AsyncCollection
) -> None:
    sim_id = _new_sim_id()
    try:
        document = await repo.create_for_simulation(sim_id)
        assert document["simulation_id"] == str(sim_id)
        assert document["schema_version"] == 1
        assert document["events"] == []
        assert document["created_at"] is not None
        assert document["updated_at"] is not None
    finally:
        await mongo_conversations_collection.delete_one({"simulation_id": str(sim_id)})


async def test_create_for_simulation_is_idempotent(
    repo: MongoConversationRepository, mongo_conversations_collection: AsyncCollection
) -> None:
    sim_id = _new_sim_id()
    try:
        first = await repo.create_for_simulation(sim_id)
        second = await repo.create_for_simulation(sim_id)
        assert first["created_at"] == second["created_at"]

        count = await mongo_conversations_collection.count_documents(
            {"simulation_id": str(sim_id)}
        )
        assert count == 1
    finally:
        await mongo_conversations_collection.delete_one({"simulation_id": str(sim_id)})


async def test_unique_index_prevents_duplicate_documents(
    mongo_conversations_collection: AsyncCollection,
) -> None:
    sim_id = _new_sim_id()
    now = datetime.now(timezone.utc)
    doc = {
        "simulation_id": str(sim_id),
        "schema_version": 1,
        "events": [],
        "created_at": now,
        "updated_at": now,
    }
    try:
        await mongo_conversations_collection.insert_one(doc)
        with pytest.raises(DuplicateKeyError):
            await mongo_conversations_collection.insert_one(doc)
    finally:
        await mongo_conversations_collection.delete_one({"simulation_id": str(sim_id)})


# ---------------------------------------------------------------------------
# get_by_simulation_id
# ---------------------------------------------------------------------------


async def test_get_by_simulation_id_returns_existing(
    repo: MongoConversationRepository, mongo_conversations_collection: AsyncCollection
) -> None:
    sim_id = _new_sim_id()
    try:
        await repo.create_for_simulation(sim_id)
        document = await repo.get_by_simulation_id(sim_id)
        assert document is not None
        assert document["simulation_id"] == str(sim_id)
    finally:
        await mongo_conversations_collection.delete_one({"simulation_id": str(sim_id)})


async def test_get_by_simulation_id_returns_none_for_missing(
    repo: MongoConversationRepository,
) -> None:
    assert await repo.get_by_simulation_id(_new_sim_id()) is None


# ---------------------------------------------------------------------------
# append_event
# ---------------------------------------------------------------------------


async def test_append_event_assigns_sequence_starting_at_one(
    repo: MongoConversationRepository, mongo_conversations_collection: AsyncCollection
) -> None:
    sim_id = _new_sim_id()
    try:
        await repo.create_for_simulation(sim_id)
        persisted = await repo.append_event(
            sim_id, {"phase": "PITCH_BATTLE", "event_type": "JUDGE_QUESTION", "content": "Q1"}
        )
        assert persisted["sequence"] == 1
        assert persisted["event_id"]
        assert persisted["created_at"] is not None
        assert persisted["content"] == "Q1"
    finally:
        await mongo_conversations_collection.delete_one({"simulation_id": str(sim_id)})


async def test_append_event_sequence_increments_and_preserves_order(
    repo: MongoConversationRepository, mongo_conversations_collection: AsyncCollection
) -> None:
    sim_id = _new_sim_id()
    try:
        await repo.create_for_simulation(sim_id)
        first = await repo.append_event(sim_id, {"content": "first"})
        second = await repo.append_event(sim_id, {"content": "second"})

        assert first["sequence"] == 1
        assert second["sequence"] == 2
        assert first["event_id"] != second["event_id"]

        document = await repo.get_by_simulation_id(sim_id)
        assert document is not None
        assert [e["content"] for e in document["events"]] == ["first", "second"]
        assert [e["sequence"] for e in document["events"]] == [1, 2]
    finally:
        await mongo_conversations_collection.delete_one({"simulation_id": str(sim_id)})


async def test_append_event_updates_document_updated_at(
    repo: MongoConversationRepository, mongo_conversations_collection: AsyncCollection
) -> None:
    sim_id = _new_sim_id()
    try:
        created = await repo.create_for_simulation(sim_id)
        await repo.append_event(sim_id, {"content": "x"})
        document = await repo.get_by_simulation_id(sim_id)
        assert document is not None
        assert document["updated_at"] >= created["updated_at"]
    finally:
        await mongo_conversations_collection.delete_one({"simulation_id": str(sim_id)})


async def test_append_event_round_trips_flexible_metadata(
    repo: MongoConversationRepository, mongo_conversations_collection: AsyncCollection
) -> None:
    sim_id = _new_sim_id()
    try:
        await repo.create_for_simulation(sim_id)
        persisted = await repo.append_event(
            sim_id,
            {
                "content": "with metadata",
                "metadata": {"attack_tag": "market_size_challenge", "answer_quality": 0.8},
            },
        )
        assert persisted["metadata"] == {
            "attack_tag": "market_size_challenge",
            "answer_quality": 0.8,
        }
    finally:
        await mongo_conversations_collection.delete_one({"simulation_id": str(sim_id)})


async def test_append_event_ignores_caller_supplied_sequence_and_event_id(
    repo: MongoConversationRepository, mongo_conversations_collection: AsyncCollection
) -> None:
    sim_id = _new_sim_id()
    try:
        await repo.create_for_simulation(sim_id)
        persisted = await repo.append_event(
            sim_id, {"content": "x", "sequence": 999, "event_id": "caller-supplied-id"}
        )
        assert persisted["sequence"] == 1
        assert persisted["event_id"] != "caller-supplied-id"
    finally:
        await mongo_conversations_collection.delete_one({"simulation_id": str(sim_id)})


async def test_append_event_to_missing_simulation_raises(
    repo: MongoConversationRepository,
) -> None:
    with pytest.raises(ConversationNotFoundError):
        await repo.append_event(_new_sim_id(), {"content": "orphan"})


# ---------------------------------------------------------------------------
# get_latest_events
# ---------------------------------------------------------------------------


async def test_get_latest_events_returns_chronological_tail(
    repo: MongoConversationRepository, mongo_conversations_collection: AsyncCollection
) -> None:
    sim_id = _new_sim_id()
    try:
        await repo.create_for_simulation(sim_id)
        for i in range(5):
            await repo.append_event(sim_id, {"content": f"event-{i}"})

        latest = await repo.get_latest_events(sim_id, limit=3)
        assert [e["sequence"] for e in latest] == [3, 4, 5]
        assert [e["content"] for e in latest] == ["event-2", "event-3", "event-4"]
    finally:
        await mongo_conversations_collection.delete_one({"simulation_id": str(sim_id)})


async def test_get_latest_events_missing_simulation_returns_empty_list(
    repo: MongoConversationRepository,
) -> None:
    assert await repo.get_latest_events(_new_sim_id()) == []


# ---------------------------------------------------------------------------
# delete_by_simulation_id
# ---------------------------------------------------------------------------


async def test_delete_by_simulation_id_removes_document(
    repo: MongoConversationRepository,
) -> None:
    sim_id = _new_sim_id()
    await repo.create_for_simulation(sim_id)
    await repo.delete_by_simulation_id(sim_id)
    assert await repo.get_by_simulation_id(sim_id) is None


async def test_delete_by_simulation_id_missing_simulation_is_a_no_op(
    repo: MongoConversationRepository,
) -> None:
    await repo.delete_by_simulation_id(_new_sim_id())  # must not raise


# ---------------------------------------------------------------------------
# Concurrency: atomic sequence assignment under real concurrent appends
# ---------------------------------------------------------------------------


async def test_concurrent_appends_produce_unique_monotonic_sequences(
    repo: MongoConversationRepository, mongo_conversations_collection: AsyncCollection
) -> None:
    sim_id = _new_sim_id()
    try:
        await repo.create_for_simulation(sim_id)

        results = await asyncio.gather(
            *(repo.append_event(sim_id, {"content": f"concurrent-{i}"}) for i in range(20))
        )

        sequences = sorted(r["sequence"] for r in results)
        assert sequences == list(range(1, 21))

        event_ids = {r["event_id"] for r in results}
        assert len(event_ids) == 20

        document = await repo.get_by_simulation_id(sim_id)
        assert document is not None
        assert len(document["events"]) == 20
        assert sorted(e["sequence"] for e in document["events"]) == list(range(1, 21))
    finally:
        await mongo_conversations_collection.delete_one({"simulation_id": str(sim_id)})
