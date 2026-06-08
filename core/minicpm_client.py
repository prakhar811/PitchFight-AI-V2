"""Stub MiniCPM client — OpenBMB integration planned for Phase 9."""

from __future__ import annotations

from typing import Any


def health_check() -> dict[str, Any]:
    return {
        "status": "not_configured",
        "provider": "openbmb",
        "message": "MiniCPM integration planned for Phase 9",
    }
