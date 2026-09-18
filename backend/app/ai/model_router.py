"""ModelRouter — resolves a logical alias to a registered ModelClient.

    alias (e.g. "default", "fake")
        v
    ModelRouter.get_client(alias)
        v
    ModelClient

Routing only. ModelRouter does NOT build prompts, call PromptBuilder,
inspect MongoDB/Redis, mutate a SimulationSession, score answers, retry a
failed call, or fall back to another provider on failure — those are
future AIOrchestrator/SimulationService responsibilities, deliberately not
here.

Registration is explicit — no scanning of app/ai/providers/ to auto-discover
clients.
"""

from app.ai.model_client import ModelClient
from app.ai.model_errors import ModelConfigurationError


class ModelRouter:
    def __init__(self, *, default_alias: str | None = None) -> None:
        self._clients: dict[str, ModelClient] = {}
        self._default_alias = default_alias

    def register(self, alias: str, client: ModelClient, *, replace: bool = False) -> None:
        """Register `client` under `alias`. Re-registering an existing
        alias fails unless `replace=True` is passed intentionally."""
        if alias in self._clients and not replace:
            raise ModelConfigurationError(
                f"Model alias {alias!r} is already registered; pass replace=True "
                "to intentionally replace it"
            )
        self._clients[alias] = client

    def get_client(self, alias: str | None = None) -> ModelClient:
        """Resolve `alias` to its registered ModelClient. Omit `alias` to
        use this router's configured default_alias instead."""
        resolved_alias = alias if alias is not None else self._default_alias
        if resolved_alias is None:
            raise ModelConfigurationError(
                "No alias given and no default_alias configured on this ModelRouter"
            )
        try:
            return self._clients[resolved_alias]
        except KeyError as exc:
            raise ModelConfigurationError(f"Unknown model alias: {resolved_alias!r}") from exc

    @property
    def default_alias(self) -> str | None:
        return self._default_alias

    @property
    def registered_aliases(self) -> frozenset[str]:
        return frozenset(self._clients)
