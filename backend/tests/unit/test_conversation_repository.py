"""ConversationRepository contract checks.

MongoDB persistence is not implemented yet, so this only verifies the
abstract interface shape — no database of any kind is touched here.
"""

import inspect

import pytest

from app.repositories import ConversationRepository


def test_conversation_repository_is_abstract() -> None:
    assert inspect.isabstract(ConversationRepository)


def test_conversation_repository_cannot_be_instantiated() -> None:
    with pytest.raises(TypeError):
        ConversationRepository()  # type: ignore[abstract]


def test_conversation_repository_exposes_expected_methods() -> None:
    expected = {
        "create_for_simulation",
        "get_by_simulation_id",
        "append_event",
        "delete_by_simulation_id",
        "get_latest_events",
    }
    assert expected <= ConversationRepository.__abstractmethods__


def test_conversation_repository_methods_are_coroutines() -> None:
    for name in ConversationRepository.__abstractmethods__:
        method = getattr(ConversationRepository, name)
        assert inspect.iscoroutinefunction(method)
