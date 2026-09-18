"""ModelRouter tests: registration, alias resolution, defaults, and
deterministic duplicate-alias behavior. No network, no database."""

import pytest

from app.ai.model_errors import ModelConfigurationError
from app.ai.model_router import ModelRouter
from app.ai.providers import FakeModelClient


def test_register_and_get_known_alias_returns_exact_client() -> None:
    router = ModelRouter()
    client = FakeModelClient()
    router.register("fake", client)
    assert router.get_client("fake") is client


def test_unknown_alias_raises_model_configuration_error() -> None:
    router = ModelRouter()
    with pytest.raises(ModelConfigurationError):
        router.get_client("does-not-exist")


def test_default_alias_used_when_no_alias_given() -> None:
    router = ModelRouter(default_alias="fake")
    client = FakeModelClient()
    router.register("fake", client)
    assert router.get_client() is client


def test_no_default_alias_and_no_alias_given_raises() -> None:
    router = ModelRouter()
    router.register("fake", FakeModelClient())
    with pytest.raises(ModelConfigurationError):
        router.get_client()


def test_explicit_alias_overrides_default() -> None:
    router = ModelRouter(default_alias="fake")
    fake_client = FakeModelClient()
    other_client = FakeModelClient()
    router.register("fake", fake_client)
    router.register("other", other_client)
    assert router.get_client("other") is other_client


def test_duplicate_registration_without_replace_raises() -> None:
    router = ModelRouter()
    router.register("fake", FakeModelClient())
    with pytest.raises(ModelConfigurationError):
        router.register("fake", FakeModelClient())


def test_duplicate_registration_with_replace_true_replaces_deterministically() -> None:
    router = ModelRouter()
    first = FakeModelClient(response_content="first")
    second = FakeModelClient(response_content="second")
    router.register("fake", first)
    router.register("fake", second, replace=True)
    assert router.get_client("fake") is second


def test_registered_aliases_reflects_registry() -> None:
    router = ModelRouter()
    router.register("fake", FakeModelClient())
    router.register("other", FakeModelClient())
    assert router.registered_aliases == frozenset({"fake", "other"})


def test_default_alias_property() -> None:
    router = ModelRouter(default_alias="fake")
    assert router.default_alias == "fake"
