"""Data access repositories.

Database access only — no HTTP, no Pydantic, no scoring, no auth, no AI
calls. Services (not yet implemented) own transaction boundaries; these
repositories flush/refresh but do not commit.
"""

from app.repositories.conversation_repository import (
    ConversationDocument,
    ConversationEvent,
    ConversationNotFoundError,
    ConversationRepository,
)
from app.repositories.judge_config_cache import JudgeConfigCache
from app.repositories.mongo_conversation_repository import MongoConversationRepository
from app.repositories.pitch_repository import PitchRepository
from app.repositories.redis_session_state_repository import RedisSessionStateRepository
from app.repositories.score_repository import ScoreRepository
from app.repositories.session_repository import SimulationSessionRepository
from app.repositories.user_repository import UserRepository
from app.repositories.voice_state_cache import VoiceStateCache

__all__ = [
    "UserRepository",
    "PitchRepository",
    "SimulationSessionRepository",
    "ScoreRepository",
    "ConversationRepository",
    "ConversationEvent",
    "ConversationDocument",
    "ConversationNotFoundError",
    "MongoConversationRepository",
    "RedisSessionStateRepository",
    "JudgeConfigCache",
    "VoiceStateCache",
]
