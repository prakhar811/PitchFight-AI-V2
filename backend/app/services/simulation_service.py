"""SimulationService — coordinates PostgreSQL + MongoDB + Redis for one
complete PitchFight simulation lifecycle.

    start
      -> persist (SQL + Mongo + Redis, with compensation on failure)
    event
      -> persist (Mongo first, then best-effort Redis sync)
    checkpoint / phase transition
      -> persist (SQL commit, then best-effort Redis sync)
    recovery
      -> rebuild Redis from SQL + Mongo on a cache miss
    terminate
      -> persist SQL, delete Redis, keep Mongo

No AI, no scoring, no HTTP. This is workflow + cross-database state
coordination only. Routes are not part of this phase.
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    DealStatus,
    Difficulty,
    Pitch,
    SimulationPhase,
    SimulationSession,
    SimulationStatus,
)
from app.repositories.base import UNSET, Unset
from app.repositories.conversation_repository import (
    ConversationEvent,
    ConversationRepository,
)
from app.repositories.judge_persona_repository import JudgePersonaRepository
from app.repositories.pitch_repository import PitchRepository
from app.repositories.redis_session_state_repository import RedisSessionStateRepository
from app.repositories.session_repository import SimulationSessionRepository

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Domain exceptions — no FastAPI/HTTP dependency. Routes (future phase)
# translate these into HTTP responses.
# ---------------------------------------------------------------------------


class SimulationNotFoundError(Exception):
    """Missing simulation, or it exists but isn't owned by the caller —
    deliberately the same error either way so ownership is never leaked."""


class PitchNotFoundError(Exception):
    """Missing pitch, or it exists but isn't owned by the caller."""


class JudgePersonaNotFoundError(Exception):
    """Judge persona doesn't exist, or exists but is inactive."""


class InvalidSimulationTransitionError(Exception):
    """Requested phase transition isn't allowed from the current phase."""


class SimulationTerminalError(Exception):
    """Operation isn't allowed because the simulation is no longer ACTIVE."""


class SimulationPersistenceError(Exception):
    """A cross-database write failed in a way that required aborting/
    compensating the operation. Wraps the underlying cause."""


# ---------------------------------------------------------------------------
# Locked phase transition graph (see module docstring in models/enums.py
# for the phase list itself). COMPLETED has no outgoing transitions.
# ---------------------------------------------------------------------------

_ALLOWED_TRANSITIONS: dict[SimulationPhase, frozenset[SimulationPhase]] = {
    SimulationPhase.PITCH_BATTLE: frozenset({SimulationPhase.PITCH_SCORING}),
    SimulationPhase.PITCH_SCORING: frozenset(
        {SimulationPhase.RETRY, SimulationPhase.DEAL, SimulationPhase.COMPLETED}
    ),
    SimulationPhase.RETRY: frozenset({SimulationPhase.DEAL, SimulationPhase.COMPLETED}),
    SimulationPhase.DEAL: frozenset({SimulationPhase.DEAL_SCORING}),
    SimulationPhase.DEAL_SCORING: frozenset({SimulationPhase.COMPLETED}),
    SimulationPhase.COMPLETED: frozenset(),
}

# The only event-metadata.state_patch keys allowed to update Redis dynamic
# state. Durable fields (simulation_id, status, current_phase, round
# counts) always come from PostgreSQL and can never be overwritten this way.
_ALLOWED_STATE_PATCH_KEYS = frozenset(
    {"active_attack_tag", "attack_attempts", "completed_attack_tags", "last_answer_quality"}
)

_PITCH_SNAPSHOT_FIELDS = (
    "startup_name",
    "problem",
    "target_users",
    "solution",
    "why_ai",
    "traction",
    "competitors",
    "ask",
)


def _build_pitch_snapshot(pitch: Pitch) -> dict[str, Any]:
    return {field: getattr(pitch, field) for field in _PITCH_SNAPSHOT_FIELDS}


def _current_judge_config_version(persona_type: str) -> str:
    """Centralized judge_config_version convention.

    No versioned config resource exists yet (app/resources/personas.json
    has no version field), so this simple `{persona_type}-v1` convention is
    the single source of truth until a future config/prompt system
    replaces it with richer version resolution.
    """
    return f"{persona_type}-v1"


def _initial_live_state(session_row: SimulationSession) -> dict[str, Any]:
    return {
        "simulation_id": str(session_row.id),
        "current_phase": session_row.current_phase,
        "battle_round": session_row.battle_round_count,
        "deal_round": session_row.deal_round_count,
        "active_attack_tag": None,
        "attack_attempts": {},
        "completed_attack_tags": [],
        "last_answer_quality": None,
        "last_event_sequence": 0,
        "updated_at": datetime.now(timezone.utc),
    }


class SimulationService:
    def __init__(
        self,
        session: AsyncSession,
        conversations: ConversationRepository,
        redis_state: RedisSessionStateRepository,
    ) -> None:
        self.session = session
        self.pitches = PitchRepository(session)
        self.judge_personas = JudgePersonaRepository(session)
        self.sessions = SimulationSessionRepository(session)
        self.conversations = conversations
        self.redis_state = redis_state

    # -- start ---------------------------------------------------------

    async def start_simulation(
        self,
        *,
        user_id: uuid.UUID,
        pitch_id: uuid.UUID,
        judge_persona_id: uuid.UUID,
        difficulty: Difficulty,
    ) -> SimulationSession:
        pitch = await self.pitches.get_by_id_for_user(pitch_id, user_id)
        if pitch is None:
            raise PitchNotFoundError(pitch_id)

        judge_persona = await self.judge_personas.get_active_by_id(judge_persona_id)
        if judge_persona is None:
            raise JudgePersonaNotFoundError(judge_persona_id)

        pitch_snapshot = _build_pitch_snapshot(pitch)
        judge_config_version = _current_judge_config_version(judge_persona.persona_type)

        mongo_created = False
        redis_created = False
        simulation_id: uuid.UUID | None = None
        try:
            session_row = await self.sessions.create(
                user_id=user_id,
                pitch_id=pitch.id,
                judge_persona_id=judge_persona.id,
                pitch_snapshot=pitch_snapshot,
                judge_config_version=judge_config_version,
                difficulty=difficulty,
            )
            simulation_id = session_row.id

            await self.conversations.create_for_simulation(simulation_id)
            mongo_created = True

            await self.redis_state.set_state(simulation_id, _initial_live_state(session_row))
            redis_created = True

            await self.session.commit()
        except Exception as exc:
            await self.session.rollback()
            if simulation_id is not None:
                if mongo_created:
                    await self._safe_delete_mongo(simulation_id)
                if redis_created:
                    await self._safe_delete_redis(simulation_id)
            raise SimulationPersistenceError(
                f"Failed to start simulation for pitch_id={pitch_id}"
            ) from exc

        return session_row

    # -- reads -----------------------------------------------------------

    async def get_simulation(
        self, simulation_id: uuid.UUID, user_id: uuid.UUID
    ) -> SimulationSession:
        session_row = await self.sessions.get_by_id_for_user(simulation_id, user_id)
        if session_row is None:
            raise SimulationNotFoundError(simulation_id)
        return session_row

    async def get_live_state(
        self, simulation_id: uuid.UUID, user_id: uuid.UUID
    ) -> dict[str, Any] | None:
        """Redis-first read with restart-safe recovery on a cache miss.

        A terminal session (COMPLETED/FAILED/ABANDONED) with no cached
        state is NOT revived into a fresh active state — it simply has no
        live state anymore, which this reports as None.
        """
        session_row = await self.get_simulation(simulation_id, user_id)

        state = await self.redis_state.get_state(simulation_id)
        if state is not None:
            return state

        if session_row.status != SimulationStatus.ACTIVE:
            return None

        reconstructed = await self._reconstruct_live_state(session_row)
        await self.redis_state.set_state(simulation_id, reconstructed)
        return reconstructed

    async def _reconstruct_live_state(self, session_row: SimulationSession) -> dict[str, Any]:
        """Redis cache-miss recovery: PostgreSQL durable checkpoint fields
        + a Mongo event replay of state_patch metadata, in sequence order.
        PostgreSQL is overlaid last so it always wins for durable fields."""
        state = _initial_live_state(session_row)

        document = await self.conversations.get_by_simulation_id(session_row.id)
        if document is not None:
            for event in sorted(document["events"], key=lambda e: e.get("sequence", 0)):
                patch = (event.get("metadata") or {}).get("state_patch") or {}
                for key in _ALLOWED_STATE_PATCH_KEYS:
                    if key in patch:
                        state[key] = patch[key]
                state["last_event_sequence"] = event.get("sequence", state["last_event_sequence"])

        # Durable fields always come from PostgreSQL, never from a replayed patch.
        state["simulation_id"] = str(session_row.id)
        state["current_phase"] = session_row.current_phase
        state["battle_round"] = session_row.battle_round_count
        state["deal_round"] = session_row.deal_round_count
        state["updated_at"] = datetime.now(timezone.utc)
        return state

    # -- events ------------------------------------------------------------

    async def record_event(
        self,
        simulation_id: uuid.UUID,
        user_id: uuid.UUID,
        *,
        event_type: str,
        role: str | None = None,
        content: str | None = None,
        round: int | None = None,
        input_mode: str | None = None,
        metadata: dict[str, Any] | None = None,
        state_patch: dict[str, Any] | None = None,
    ) -> ConversationEvent:
        session_row = await self.get_simulation(simulation_id, user_id)
        self._ensure_active(session_row)

        if metadata is not None and not isinstance(metadata, dict):
            raise ValueError("metadata must be a dict")
        if state_patch is not None:
            if not isinstance(state_patch, dict):
                raise ValueError("state_patch must be a dict")
            invalid_keys = set(state_patch) - _ALLOWED_STATE_PATCH_KEYS
            if invalid_keys:
                raise ValueError(f"Invalid state_patch keys: {sorted(invalid_keys)}")

        event_metadata = dict(metadata or {})
        if state_patch:
            event_metadata["state_patch"] = state_patch

        event: ConversationEvent = {
            "phase": session_row.current_phase.value,
            "event_type": event_type,
        }
        if role is not None:
            event["role"] = role
        if content is not None:
            event["content"] = content
        if round is not None:
            event["round"] = round
        if input_mode is not None:
            event["input_mode"] = input_mode
        if event_metadata:
            event["metadata"] = event_metadata

        # Mongo first: it's the permanent record. If the later Redis sync
        # fails, the event is still safe and Redis can be reconstructed.
        persisted = await self.conversations.append_event(simulation_id, event)

        redis_updates: dict[str, Any] = {"last_event_sequence": persisted["sequence"]}
        if state_patch:
            redis_updates.update(state_patch)
        try:
            await self.redis_state.update_state(simulation_id, redis_updates)
        except Exception:
            logger.warning(
                "Failed to sync Redis after recording event for simulation_id=%s "
                "(event is safely persisted in Mongo; Redis will self-heal on next "
                "get_live_state())",
                simulation_id,
                exc_info=True,
            )

        return persisted

    # -- checkpoints / transitions ------------------------------------------

    async def update_runtime_checkpoint(
        self,
        simulation_id: uuid.UUID,
        user_id: uuid.UUID,
        *,
        battle_round_count: int | Unset = UNSET,
        deal_round_count: int | Unset = UNSET,
        deal_status: DealStatus | Unset = UNSET,
        deal_type: str | None | Unset = UNSET,
    ) -> SimulationSession:
        session_row = await self.get_simulation(simulation_id, user_id)
        self._ensure_active(session_row)

        if battle_round_count is not UNSET:
            self._ensure_round_count_valid(
                "battle_round_count", battle_round_count, session_row.battle_round_count
            )
        if deal_round_count is not UNSET:
            self._ensure_round_count_valid(
                "deal_round_count", deal_round_count, session_row.deal_round_count
            )

        updated = await self.sessions.update_checkpoint(
            session_row,
            battle_round_count=battle_round_count,
            deal_round_count=deal_round_count,
            deal_status=deal_status,
            deal_type=deal_type,
        )
        await self.session.commit()

        redis_updates: dict[str, Any] = {}
        if battle_round_count is not UNSET:
            redis_updates["battle_round"] = battle_round_count
        if deal_round_count is not UNSET:
            redis_updates["deal_round"] = deal_round_count
        if redis_updates:
            await self._best_effort_redis_update(simulation_id, redis_updates)

        return updated

    @staticmethod
    def _ensure_round_count_valid(field_name: str, new_value: int, current_value: int) -> None:
        if new_value < 0:
            raise ValueError(f"{field_name} cannot be negative")
        if new_value < current_value:
            raise ValueError(f"{field_name} cannot decrease (from {current_value} to {new_value})")

    async def transition_phase(
        self, simulation_id: uuid.UUID, user_id: uuid.UUID, target_phase: SimulationPhase
    ) -> SimulationSession:
        session_row = await self.get_simulation(simulation_id, user_id)
        self._ensure_active(session_row)
        self._ensure_transition_allowed(session_row.current_phase, target_phase)

        if (
            target_phase == SimulationPhase.DEAL
            and session_row.deal_status == DealStatus.NOT_AVAILABLE
        ):
            raise InvalidSimulationTransitionError(
                f"Cannot enter DEAL phase for simulation {simulation_id}: "
                "deal_status is NOT_AVAILABLE"
            )

        updated = await self.sessions.update_checkpoint(session_row, current_phase=target_phase)
        await self.session.commit()

        await self._best_effort_redis_update(simulation_id, {"current_phase": target_phase})
        return updated

    @staticmethod
    def _ensure_transition_allowed(current: SimulationPhase, target: SimulationPhase) -> None:
        if target not in _ALLOWED_TRANSITIONS.get(current, frozenset()):
            raise InvalidSimulationTransitionError(
                f"Cannot transition from {current.value} to {target.value}"
            )

    @staticmethod
    def _ensure_active(session_row: SimulationSession) -> None:
        if session_row.status != SimulationStatus.ACTIVE:
            raise SimulationTerminalError(
                f"Simulation {session_row.id} is {session_row.status.value}, not ACTIVE"
            )

    # -- termination ---------------------------------------------------------

    async def mark_completed(
        self, simulation_id: uuid.UUID, user_id: uuid.UUID
    ) -> SimulationSession:
        """Finalizes the lifecycle once a future scoring flow says the
        simulation is done. Does not create Scorecards itself."""
        session_row = await self.get_simulation(simulation_id, user_id)
        self._ensure_active(session_row)
        self._ensure_transition_allowed(session_row.current_phase, SimulationPhase.COMPLETED)

        updated = await self.sessions.update_checkpoint(
            session_row,
            status=SimulationStatus.COMPLETED,
            current_phase=SimulationPhase.COMPLETED,
            completed_at=datetime.now(timezone.utc),
        )
        await self.session.commit()
        await self._safe_delete_redis(simulation_id)
        return updated

    async def mark_abandoned(
        self, simulation_id: uuid.UUID, user_id: uuid.UUID
    ) -> SimulationSession:
        session_row = await self.get_simulation(simulation_id, user_id)
        self._ensure_active(session_row)

        updated = await self.sessions.update_checkpoint(
            session_row, status=SimulationStatus.ABANDONED
        )
        await self.session.commit()
        await self._safe_delete_redis(simulation_id)
        return updated

    async def mark_failed(
        self, simulation_id: uuid.UUID, user_id: uuid.UUID, *, failure_reason: str
    ) -> SimulationSession:
        session_row = await self.get_simulation(simulation_id, user_id)
        self._ensure_active(session_row)

        # Bound length; callers pass a safe summary, never a raw stack trace.
        safe_reason = failure_reason.strip()[:1000]

        updated = await self.sessions.update_checkpoint(
            session_row, status=SimulationStatus.FAILED, failure_reason=safe_reason
        )
        await self.session.commit()
        await self._safe_delete_redis(simulation_id)
        return updated

    # -- deletion --------------------------------------------------------

    async def delete_simulation(self, simulation_id: uuid.UUID, user_id: uuid.UUID) -> None:
        """Locked order: Mongo -> Redis (best-effort) -> SQL.

        Mongo durable history must be gone before SQL deletion proceeds; if
        it fails, we stop rather than delete the SQL row out from under
        history that might still exist. Redis is best-effort — it's
        non-authoritative and TTL-bound anyway. PostgreSQL cascades
        Scorecards; the Pitch and User rows are untouched.
        """
        session_row = await self.get_simulation(simulation_id, user_id)

        try:
            await self.conversations.delete_by_simulation_id(simulation_id)
        except Exception as exc:
            raise SimulationPersistenceError(
                f"Failed to delete Mongo conversation for simulation_id={simulation_id}; "
                "aborting before SQL deletion"
            ) from exc

        await self._safe_delete_redis(simulation_id)

        await self.sessions.delete(session_row)
        await self.session.commit()

    # -- best-effort cache cleanup helpers ---------------------------------

    async def _best_effort_redis_update(
        self, simulation_id: uuid.UUID, updates: dict[str, Any]
    ) -> None:
        try:
            await self.redis_state.update_state(simulation_id, updates)
        except Exception:
            logger.warning(
                "Failed to sync Redis live state for simulation_id=%s after a committed "
                "SQL change; SQL remains authoritative and get_live_state() will recover it",
                simulation_id,
                exc_info=True,
            )

    async def _safe_delete_mongo(self, simulation_id: uuid.UUID) -> None:
        try:
            await self.conversations.delete_by_simulation_id(simulation_id)
        except Exception:
            logger.warning(
                "Failed to clean up Mongo conversation for simulation_id=%s during "
                "start_simulation compensation",
                simulation_id,
                exc_info=True,
            )

    async def _safe_delete_redis(self, simulation_id: uuid.UUID) -> None:
        try:
            await self.redis_state.delete_state(simulation_id)
        except Exception:
            logger.warning(
                "Failed to clean up Redis live state for simulation_id=%s",
                simulation_id,
                exc_info=True,
            )
