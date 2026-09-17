"""ConversationRepository contract.

Mongo implementation will be added during the MongoDB Persistence phase.

This module defines only the abstract async interface so that future
SimulationService / AIOrchestrator code can depend on a stable contract
instead of calling PyMongo directly. Nothing here connects to MongoDB or
persists anything.

Locked shape: one document per simulation, collection
`simulation_conversations`, containing an append-only list of events.
"""

import uuid
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, TypedDict


class ConversationEvent(TypedDict, total=False):
    """One event inside a simulation's conversation document.

    `metadata` is intentionally open-ended — persona-specific fields are
    never hardcoded into the repository contract.
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


class ConversationRepository(ABC):
    """Async contract for per-simulation conversation persistence."""

    @abstractmethod
    async def create_for_simulation(self, simulation_id: uuid.UUID) -> ConversationDocument:
        """Create the empty conversation document for a new simulation."""

    @abstractmethod
    async def get_by_simulation_id(
        self, simulation_id: uuid.UUID
    ) -> ConversationDocument | None:
        """Fetch the conversation document, or None if it doesn't exist."""

    @abstractmethod
    async def append_event(self, simulation_id: uuid.UUID, event: ConversationEvent) -> None:
        """Append one event to the simulation's conversation document."""

    @abstractmethod
    async def delete_by_simulation_id(self, simulation_id: uuid.UUID) -> None:
        """Delete the conversation document for a simulation."""

    @abstractmethod
    async def get_latest_events(
        self, simulation_id: uuid.UUID, limit: int = 20
    ) -> list[ConversationEvent]:
        """Fetch the most recent `limit` events for a simulation."""
