"""AI-layer typed structures.

- PromptBuilder's input (PromptContext) and output (BuiltPrompt).
- Small structured output contracts describing what a future ModelClient
  should eventually parse from a model response (not parsed yet).
- Provider-neutral model request/response types (ModelRequest,
  ModelResponse, ModelResponseFormat, TokenUsage) — the Phase 11 model
  abstraction layer's shared vocabulary. See app/ai/model_client.py.

No LLM calls happen here and no real model response is parsed here — these
are intent/contract types only.
"""

import enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import Difficulty


class PromptTask(str, enum.Enum):
    """Centralized set of supported prompt tasks — callers select one of
    these, never an arbitrary filesystem path."""

    BATTLE_QUESTION = "BATTLE_QUESTION"
    BATTLE_FOLLOWUP = "BATTLE_FOLLOWUP"
    RETRY_FEEDBACK = "RETRY_FEEDBACK"
    DEAL_NEGOTIATION = "DEAL_NEGOTIATION"


class RecentEvent(BaseModel):
    """One already-selected conversation event, as rendered into a prompt.

    Deliberately narrower than Mongo's ConversationEvent — only the fields
    useful as model context, never raw Mongo internals or arbitrary metadata.
    """

    role: str | None = None
    content: str | None = None
    round: int | None = None
    event_type: str | None = None


class PromptContext(BaseModel):
    """Everything PromptBuilder needs to compose one prompt.

    Supplied entirely by the caller (a future SimulationService/
    AIOrchestrator) — PromptBuilder never queries PostgreSQL, MongoDB, or
    Redis itself, and never decides the next simulation phase.
    """

    model_config = ConfigDict(frozen=True)

    judge_config_version: str
    difficulty: Difficulty
    task: PromptTask

    pitch_snapshot: dict[str, Any]

    current_phase: str
    battle_round: int = 0
    deal_round: int = 0
    active_attack_tag: str | None = None
    completed_attack_tags: list[str] = []

    recent_events: list[RecentEvent] = []

    # Small extra context specific to one task (e.g. the original answer
    # being retried, or the founder's latest deal offer). Free-form on
    # purpose — PromptBuilder renders it generically, it doesn't interpret it.
    task_context: dict[str, Any] | None = None


class BuiltPrompt(BaseModel):
    """PromptBuilder's output, ready for the future ModelClient phase.

    system_prompt: instructions (base rules, safety, persona, difficulty,
    task, output format) — never simulation-specific untrusted content.
    user_prompt: the pitch, current state, and recent conversation —
    clearly delimited as untrusted simulation content.
    """

    system_prompt: str
    user_prompt: str
    metadata: dict[str, Any]


# ---------------------------------------------------------------------------
# Structured output contracts — describe what a future ModelClient should
# eventually parse. Not used to parse anything in this phase. Deliberately
# small and task-specific rather than one shared shape for every task.
# ---------------------------------------------------------------------------


class BattleQuestionOutput(BaseModel):
    """Expected output shape for BATTLE_QUESTION / BATTLE_FOLLOWUP."""

    question: str
    attack_tag: str
    is_follow_up: bool = False
    expected_evidence: list[str] = []


class RetryFeedbackOutput(BaseModel):
    """Expected output shape for RETRY_FEEDBACK. Coaching only — no score."""

    feedback: str
    improved: bool
    remaining_gap: str | None = None


class DealNegotiationOutput(BaseModel):
    """Expected output shape for DEAL_NEGOTIATION."""

    response: str
    negotiation_tag: str | None = None


# ---------------------------------------------------------------------------
# AIOrchestrator (Phase 13) inputs — one typed request per supported task.
# Everything here is content/context only; which model alias handles the
# call is a separate, orthogonal concern (see AIOrchestrator's method
# signatures), not a field on these schemas.
# ---------------------------------------------------------------------------


class BaseGenerationRequest(BaseModel):
    """Fields shared by every AIOrchestrator task-generation request —
    mirrors PromptContext minus `task` (each orchestrator method already
    implies its own task) and minus `task_context` (task-specific
    subclasses below expose their own typed extra fields instead of a
    free-form dict)."""

    model_config = ConfigDict(frozen=True)

    judge_config_version: str
    difficulty: Difficulty

    pitch_snapshot: dict[str, Any]

    current_phase: str
    battle_round: int = 0
    deal_round: int = 0
    active_attack_tag: str | None = None
    completed_attack_tags: list[str] = []

    recent_events: list[RecentEvent] = []


class BattleQuestionRequest(BaseGenerationRequest):
    """No task-specific fields — a fresh primary question needs only the
    shared simulation context."""


class BattleFollowupRequest(BaseGenerationRequest):
    # The founder's most recent answer, being followed up on.
    prior_answer: str


class RetryFeedbackRequest(BaseGenerationRequest):
    original_answer: str
    retry_answer: str


class DealNegotiationRequest(BaseGenerationRequest):
    founder_offer: str | None = None


# ---------------------------------------------------------------------------
# Model abstraction layer — provider-neutral request/response vocabulary.
# No OpenAI message IDs, no Anthropic blocks, no Nemotron chat-template
# tokens, no Modal request types. A provider implementation adapts these,
# not the other way around.
# ---------------------------------------------------------------------------


class ModelResponseFormat(str, enum.Enum):
    """What shape of output the caller wants back. Not JSON-schema
    enforcement — just "plain text" vs "structured JSON". The provider
    implementation decides how best to request/enforce that later."""

    TEXT = "TEXT"
    JSON = "JSON"


class TokenUsage(BaseModel):
    """Token accounting for one generation call. Fields are None when a
    provider doesn't report them — never a fabricated count."""

    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None


class ModelRequest(BaseModel):
    """Provider-neutral generation request. One ModelClient consumes one
    of these and returns one ModelResponse."""

    model_config = ConfigDict(frozen=True)

    system_prompt: str
    user_prompt: str

    temperature: float | None = None
    max_tokens: int | None = None
    top_p: float | None = None

    # Advisory: how long the caller is willing to wait. A provider client
    # decides how to honor it (e.g. asyncio.wait_for) — this phase has no
    # network provider, so nothing enforces it yet.
    timeout_seconds: float | None = None

    response_format: ModelResponseFormat = ModelResponseFormat.TEXT

    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("temperature")
    @classmethod
    def _validate_temperature(cls, value: float | None) -> float | None:
        if value is not None and value < 0:
            raise ValueError("temperature must be >= 0")
        return value

    @field_validator("max_tokens")
    @classmethod
    def _validate_max_tokens(cls, value: int | None) -> int | None:
        if value is not None and value <= 0:
            raise ValueError("max_tokens must be > 0")
        return value

    @field_validator("top_p")
    @classmethod
    def _validate_top_p(cls, value: float | None) -> float | None:
        if value is not None and not (0 <= value <= 1):
            raise ValueError("top_p must be between 0 and 1")
        return value

    @field_validator("timeout_seconds")
    @classmethod
    def _validate_timeout_seconds(cls, value: float | None) -> float | None:
        if value is not None and value <= 0:
            raise ValueError("timeout_seconds must be > 0")
        return value


class ModelResponse(BaseModel):
    """Provider-neutral generation result. raw_metadata is an optional
    escape hatch for diagnostics — never the main way callers read output."""

    content: str

    provider: str
    model: str

    finish_reason: str | None = None
    usage: TokenUsage = Field(default_factory=TokenUsage)

    latency_ms: float | None = None
    request_id: str | None = None

    raw_metadata: dict[str, Any] = Field(default_factory=dict)
