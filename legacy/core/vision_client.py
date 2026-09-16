"""Stub vision client — MiniCPM-V 4.6 deck critique planned for Phase 10."""

from __future__ import annotations

from typing import Any


def health_check() -> dict[str, Any]:
    return {
        "status": "not_configured",
        "provider": "openbmb",
        "message": "Vision/deck critique planned for Phase 10",
    }
