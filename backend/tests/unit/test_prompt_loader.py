"""Prompt resource loader tests. No database, no LLM — just file loading."""

import pytest

from app.ai.prompt_loader import PromptResourceNotFoundError, load_prompt_resource

PERSONA_FILES = [
    "personas/skeptical_vc_v1.md",
    "personas/technical_judge_v1.md",
    "personas/hackathon_judge_v1.md",
]

DIFFICULTY_FILES = [
    "difficulty/practice.md",
    "difficulty/judge.md",
    "difficulty/investor.md",
]

TASK_FILES = [
    "tasks/battle_question.md",
    "tasks/battle_followup.md",
    "tasks/retry_feedback.md",
    "tasks/deal_negotiation.md",
]

SHARED_FILES = [
    "shared/base_judge.md",
    "shared/safety_rules.md",
]


@pytest.mark.parametrize("relative_path", PERSONA_FILES)
def test_persona_v1_files_load(relative_path: str) -> None:
    text = load_prompt_resource(relative_path)
    assert text
    assert len(text) > 20


@pytest.mark.parametrize("relative_path", DIFFICULTY_FILES)
def test_difficulty_files_load(relative_path: str) -> None:
    text = load_prompt_resource(relative_path)
    assert text
    assert len(text) > 20


@pytest.mark.parametrize("relative_path", TASK_FILES)
def test_task_files_load(relative_path: str) -> None:
    text = load_prompt_resource(relative_path)
    assert text
    assert len(text) > 20


@pytest.mark.parametrize("relative_path", SHARED_FILES)
def test_shared_files_load(relative_path: str) -> None:
    text = load_prompt_resource(relative_path)
    assert text
    assert len(text) > 20


def test_missing_resource_raises_clear_error() -> None:
    with pytest.raises(PromptResourceNotFoundError):
        load_prompt_resource("personas/does_not_exist_v1.md")


def test_loaded_resource_is_cached_and_stable() -> None:
    first = load_prompt_resource("shared/base_judge.md")
    second = load_prompt_resource("shared/base_judge.md")
    assert first == second
