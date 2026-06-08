"""Stub transcription client — faster-whisper fallback planned for Phase 7."""

from __future__ import annotations

from typing import Any


def health_check() -> dict[str, Any]:
    return {
        "status": "not_configured",
        "provider": "local",
        "message": "faster-whisper fallback planned for Phase 7",
    }
