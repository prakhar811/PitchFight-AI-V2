"""Placeholder local text model for Phase 2 integration."""

from __future__ import annotations

from typing import Any


class LocalTextModel:
    """Stub for the future local MiniCPM-family model runtime."""

    def __init__(self) -> None:
        self.loaded = False

    def health_check(self) -> dict[str, str]:
        return {
            "status": "not_loaded",
            "message": "Local model will be added in Phase 2",
        }

    def generate(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 300,
    ) -> str:
        _ = (messages, temperature, max_tokens)
        return (
            "[Phase 1 placeholder] The local text model is not loaded yet. "
            "Mock battle responses are served by the API layer."
        )
