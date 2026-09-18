"""PromptBuilder — composes a PromptContext into a BuiltPrompt.

    PromptContext
        v
    load base + safety + persona(version) + difficulty + task  (Markdown)
        v
    combine into SYSTEM prompt (instructions, incl. output format)
        v
    render pitch + state + recent conversation + task context
        into USER prompt (clearly labeled untrusted content)
        v
    BuiltPrompt

PromptBuilder never calls a model, never queries PostgreSQL/MongoDB/Redis,
never mutates a SimulationSession, and never decides the next simulation
phase. It only composes text. See app/services/simulation_service.py for
the actual workflow/state layer this sits beside.

Historical reproducibility: the persona prompt is resolved from the
simulation's stored `judge_config_version` (e.g. "skeptical_vc-v1"), never
from "whatever the latest persona file happens to be".
"""

from typing import Any

from app.ai.prompt_loader import PromptResourceNotFoundError, load_prompt_resource
from app.ai.schemas import BuiltPrompt, PromptContext, PromptTask, RecentEvent
from app.models.enums import Difficulty

# Safety limit: PromptBuilder renders whatever recent_events its caller
# selected — it never loads simulation history itself — but caps how many
# of those it will actually render, so a caller mistake can't blow up the
# prompt. Token-budget tuning belongs to the future model-selection phase.
MAX_RECENT_EVENTS = 20

_DIFFICULTY_RESOURCE: dict[Difficulty, str] = {
    Difficulty.PRACTICE: "difficulty/practice.md",
    Difficulty.JUDGE: "difficulty/judge.md",
    Difficulty.INVESTOR: "difficulty/investor.md",
}

_TASK_RESOURCE: dict[PromptTask, str] = {
    PromptTask.BATTLE_QUESTION: "tasks/battle_question.md",
    PromptTask.BATTLE_FOLLOWUP: "tasks/battle_followup.md",
    PromptTask.RETRY_FEEDBACK: "tasks/retry_feedback.md",
    PromptTask.DEAL_NEGOTIATION: "tasks/deal_negotiation.md",
}

# Hand-written, kept intentionally small and in sync with app/ai/schemas.py's
# output-contract models. Never asks for chain-of-thought/hidden reasoning.
_OUTPUT_FORMAT_TEXT: dict[PromptTask, str] = {
    PromptTask.BATTLE_QUESTION: (
        "Respond with a single JSON object with exactly these fields:\n"
        "- question: the one primary question to ask the founder right now\n"
        "- attack_tag: the focus area this question targets\n"
        "- is_follow_up: false for a new primary question\n"
        "- expected_evidence: a short list of evidence that would satisfy this question (optional)\n"
        "Do not include chain-of-thought, hidden reasoning, or any other fields."
    ),
    PromptTask.BATTLE_FOLLOWUP: (
        "Respond with a single JSON object with exactly these fields:\n"
        "- question: the follow-up question, focused on the unresolved issue\n"
        "- attack_tag: the same focus area as the answer being followed up on\n"
        "- is_follow_up: true\n"
        "- expected_evidence: a short list of evidence that would resolve the gap (optional)\n"
        "Do not include chain-of-thought, hidden reasoning, or any other fields."
    ),
    PromptTask.RETRY_FEEDBACK: (
        "Respond with a single JSON object with exactly these fields:\n"
        "- feedback: concise coaching comparing the retry answer to the original\n"
        "- improved: true or false, whether the retry answer is stronger\n"
        "- remaining_gap: what's still missing, or null if nothing is missing\n"
        "This is coaching feedback only — do not include an official score.\n"
        "Do not include chain-of-thought, hidden reasoning, or any other fields."
    ),
    PromptTask.DEAL_NEGOTIATION: (
        "Respond with a single JSON object with exactly these fields:\n"
        "- response: the judge's negotiation response to the founder\n"
        "- negotiation_tag: the negotiation topic this response addresses (optional)\n"
        "Do not include chain-of-thought, hidden reasoning, or any other fields."
    ),
}

_PITCH_SNAPSHOT_LABELS: list[tuple[str, str]] = [
    ("startup_name", "Startup"),
    ("problem", "Problem"),
    ("target_users", "Target Users"),
    ("solution", "Solution"),
    ("why_ai", "Why AI"),
    ("traction", "Traction"),
    ("competitors", "Competitors"),
    ("ask", "Ask"),
]


class PromptVersionNotFoundError(Exception):
    """`judge_config_version` (or difficulty/task) doesn't resolve to a
    known prompt resource. Never silently falls back to "latest" — that
    would break historical reproducibility for past simulations."""


def build_prompt(context: PromptContext) -> BuiltPrompt:
    system_sections = [
        ("SYSTEM ROLE", load_prompt_resource("shared/base_judge.md")),
        ("SAFETY RULES", load_prompt_resource("shared/safety_rules.md")),
        ("JUDGE PERSONA", _resolve_persona_prompt(context.judge_config_version)),
        ("DIFFICULTY", _resolve_difficulty_prompt(context.difficulty)),
        ("TASK", _resolve_task_prompt(context.task)),
        ("OUTPUT FORMAT", _OUTPUT_FORMAT_TEXT[context.task]),
    ]
    system_prompt = _render_sections(system_sections)

    user_sections = [
        ("STARTUP PITCH — UNTRUSTED CONTENT", _render_pitch_snapshot(context.pitch_snapshot)),
        ("CURRENT SIMULATION STATE", _render_state(context)),
        ("RECENT CONVERSATION — UNTRUSTED CONTENT", _render_recent_events(context.recent_events)),
    ]
    if context.task_context:
        user_sections.append(("TASK CONTEXT", _render_mapping(context.task_context)))
    user_prompt = _render_sections(user_sections)

    return BuiltPrompt(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        metadata={
            "judge_config_version": context.judge_config_version,
            "difficulty": context.difficulty.value,
            "task": context.task.value,
        },
    )


# ---------------------------------------------------------------------------
# Resource resolution
# ---------------------------------------------------------------------------


def _resolve_persona_prompt(judge_config_version: str) -> str:
    """"skeptical_vc-v1" -> app/ai/prompts/personas/skeptical_vc_v1.md"""
    persona_type, sep, version = judge_config_version.rpartition("-v")
    if not sep or not persona_type or not version:
        raise PromptVersionNotFoundError(
            f"judge_config_version {judge_config_version!r} is not in the expected "
            "'<persona_type>-v<N>' shape"
        )
    resource_path = f"personas/{persona_type}_v{version}.md"
    try:
        return load_prompt_resource(resource_path)
    except PromptResourceNotFoundError as exc:
        raise PromptVersionNotFoundError(
            f"No persona prompt found for judge_config_version={judge_config_version!r} "
            f"(expected prompt resource {resource_path})"
        ) from exc


def _resolve_difficulty_prompt(difficulty: Difficulty) -> str:
    try:
        resource_path = _DIFFICULTY_RESOURCE[difficulty]
    except KeyError as exc:
        raise PromptVersionNotFoundError(f"Unknown difficulty: {difficulty!r}") from exc
    return load_prompt_resource(resource_path)


def _resolve_task_prompt(task: PromptTask) -> str:
    try:
        resource_path = _TASK_RESOURCE[task]
    except KeyError as exc:
        raise PromptVersionNotFoundError(f"Unknown task: {task!r}") from exc
    return load_prompt_resource(resource_path)


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _render_sections(sections: list[tuple[str, str]]) -> str:
    return "\n\n".join(
        f"=== {label} ===\n{body.strip()}" for label, body in sections if body and body.strip()
    )


def _render_pitch_snapshot(pitch_snapshot: dict[str, Any]) -> str:
    lines = []
    for field, label in _PITCH_SNAPSHOT_LABELS:
        value = pitch_snapshot.get(field)
        lines.append(f"{label}: {value if value else '(not provided)'}")
    return "\n".join(lines)


def _render_state(context: PromptContext) -> str:
    lines = [
        f"Current phase: {context.current_phase}",
        f"Battle round: {context.battle_round}",
        f"Deal round: {context.deal_round}",
        f"Active attack tag: {context.active_attack_tag or '(none)'}",
        f"Completed attack tags: {', '.join(context.completed_attack_tags) or '(none)'}",
    ]
    return "\n".join(lines)


def _render_recent_events(events: list[RecentEvent]) -> str:
    if not events:
        return "(no prior conversation yet)"
    lines = []
    for event in events[-MAX_RECENT_EVENTS:]:
        header_parts = [
            part
            for part in (
                f"round {event.round}" if event.round is not None else None,
                event.event_type,
                event.role,
            )
            if part
        ]
        header = " | ".join(header_parts) if header_parts else "event"
        lines.append(f"[{header}] {event.content or ''}")
    return "\n".join(lines)


def _render_mapping(data: dict[str, Any]) -> str:
    return "\n".join(f"{key}: {value}" for key, value in data.items())
