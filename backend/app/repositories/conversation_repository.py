"""ConversationRepository contract.

The concrete implementation is MongoConversationRepository
(app/repositories/mongo_conversation_repository.py). This module stays the
stable abstract interface so future SimulationService / AIOrchestrator code
depends on a contract, not PyMongo directly.

Locked shape: one document per simulation, collection
`simulation_conversations`, containing an append-only list of events.

Contract note (Phase 7): `event_id`, `sequence`, and `created_at` on
ConversationEvent are persistence-assigned, not caller-assigned — see
append_event(). This isn't a structural change (all ConversationEvent
fields were already optional via total=False); it's a behavioral
clarification so sequence correctness never depends on caller discipline.
"""

import uuid
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, TypedDict


class ConversationEvent(TypedDict, total=False):
    """One event inside a simulation's conversation document.

    `metadata` is intentionally open-ended — persona-specific fields are
    never hardcoded into the repository contract.

    When passed into append_event(), `event_id`/`sequence`/`created_at`
    are ignored if present — the repository always assigns its own to
    guarantee a correct, atomic, monotonic sequence. They're populated
    fields on anything read back (get_by_simulation_id, get_latest_events,
    or the event returned by append_event itself).
    """

    event_id: str
    sequence: int
    phase: str
    event_type: str
    role: str
    content: str
    round: int
    input_mode: str
    created_at: datetime
    metadata: dict[str, Any]


class ConversationDocument(TypedDict):
    """The single Mongo document shape for one simulation's conversation."""

    simulation_id: str
    schema_version: int
    events: list[ConversationEvent]
    created_at: datetime
    updated_at: datetime


class ConversationNotFoundError(Exception):
    """Raised when an operation needs an existing conversation document and
    none exists for the given simulation_id (e.g. append_event)."""


class ConversationRepository(ABC):
    """Async contract for per-simulation conversation persistence."""

    @abstractmethod
    async def create_for_simulation(self, simulation_id: uuid.UUID) -> ConversationDocument:
        """Create the empty conversation document for a new simulation.

        Idempotent: calling this again for the same simulation_id returns
        the existing document rather than creating a duplicate.
        """

    @abstractmethod
    async def get_by_simulation_id(
        self, simulation_id: uuid.UUID
    ) -> ConversationDocument | None:
        """Fetch the conversation document, or None if it doesn't exist."""

    @abstractmethod
    async def append_event(
        self, simulation_id: uuid.UUID, event: ConversationEvent
    ) -> ConversationEvent:
        """Append one event and return it as persisted (with its assigned
        event_id, sequence, and created_at).

        Raises ConversationNotFoundError if no conversation document exists
        for simulation_id — an event is never silently dropped.
        """

    @abstractmethod
    async def delete_by_simulation_id(self, simulation_id: uuid.UUID) -> None:
        """Delete the conversation document for a simulation, if it exists."""

    @abstractmethod
    async def get_latest_events(
        self, simulation_id: uuid.UUID, limit: int = 20
    ) -> list[ConversationEvent]:
        """Fetch the most recent `limit` events, in chronological order.

        Returns an empty list if the simulation has no conversation
        document or no events yet.
        """
