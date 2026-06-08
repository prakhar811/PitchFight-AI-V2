"""Central model routing layer for PitchFight AI.

Routes task requests to the correct model client based on model_mode.
All model calls are backend-only. Frontend never calls this layer directly.

Supported mode keys:
  premium_nvidia   — NVIDIA Nemotron 3 Nano Omni 30B-A3B (default)
  openbmb_omni     — MiniCPM-o 4.5 (Phase 9)
  tiny_minicpm     — MiniCPM5-1B (Phase 9)
  vision_deck      — MiniCPM-V 4.6 (Phase 10)
  whisper_fallback — faster-whisper transcription (Phase 7)
"""

from __future__ import annotations

import logging
import os
from typing import Any

from dotenv import load_dotenv

from core import nvidia_client
from core import minicpm_client
from core import vision_client
from core import transcription_client

load_dotenv()

logger = logging.getLogger(__name__)

SUPPORTED_MODES = {
    "premium_nvidia",
    "openbmb_omni",
    "tiny_minicpm",
    "vision_deck",
    "whisper_fallback",
}

_FALLBACK_OPPONENT_MESSAGE = (
    "Your answer lacked specificity. "
    "What concrete proof — a metric, a test result, or a user quote — "
    "can you give me right now to back that claim?"
)

_FALLBACK_SCORECARD: dict[str, Any] = {
    "overall": 0,
    "scores": {},
    "best_answer": "Model scoring unavailable.",
    "weakest_answer": "",
    "improved_answer": "",
    "improved_pitch": "",
    "top_3_questions": [],
    "_fallback": True,
}


def get_default_model_mode() -> str:
    """Return the configured default model mode."""
    mode = os.getenv("DEFAULT_MODEL_MODE", "premium_nvidia").strip()
    return mode if mode in SUPPORTED_MODES else "premium_nvidia"


def get_model_health() -> dict[str, Any]:
    """Return health status for all model clients (no keys exposed)."""
    return {
        "default_mode": get_default_model_mode(),
        "supported_modes": sorted(SUPPORTED_MODES),
        "providers": {
            "nvidia": nvidia_client.health_check(),
            "minicpm": minicpm_client.health_check(),
            "vision": vision_client.health_check(),
            "transcription": transcription_client.health_check(),
        },
    }


def _resolve_mode(model_mode: str | None) -> str:
    """Validate and return a mode key, falling back to default if invalid."""
    if model_mode and model_mode in SUPPORTED_MODES:
        return model_mode
    default = get_default_model_mode()
    if model_mode and model_mode not in SUPPORTED_MODES:
        logger.warning(
            "Unknown model_mode '%s', falling back to '%s'", model_mode, default
        )
    return default


def generate_opponent_response(
    messages: list[dict[str, str]],
    model_mode: str | None = None,
    persona: str | None = None,
    attack_tag: str | None = None,
) -> dict[str, Any]:
    """Route an opponent-turn request to the correct model client.

    Returns a result dict:
      ok       — bool, True on success
      model_mode — the mode key used
      provider — which provider was called
      content  — the model's text response
      error    — None on success, error description on failure
    """
    mode = _resolve_mode(model_mode)

    if mode == "premium_nvidia":
        return _call_nvidia_opponent(messages, mode)

    if mode in ("openbmb_omni", "tiny_minicpm"):
        return _placeholder_result(
            mode,
            "openbmb",
            f"OpenBMB mode '{mode}' is planned for Phase 9.",
        )

    if mode == "vision_deck":
        return _placeholder_result(
            mode,
            "openbmb",
            "Vision/deck mode is planned for Phase 10.",
        )

    if mode == "whisper_fallback":
        return _placeholder_result(
            mode,
            "local",
            "Whisper fallback is planned for Phase 7.",
        )

    return _placeholder_result(mode, "unknown", f"Unsupported mode: {mode}")


def generate_scorecard_response(
    messages: list[dict[str, str]],
    model_mode: str | None = None,
) -> dict[str, Any]:
    """Route a scorecard-generation request to the correct model client."""
    mode = _resolve_mode(model_mode)

    if mode == "premium_nvidia":
        return _call_nvidia_scorecard(messages, mode)

    return _placeholder_result(
        mode,
        "mock",
        f"Scorecard via '{mode}' is not yet implemented. Using mock scorecard.",
    )


def generate_coaching_response(
    messages: list[dict[str, str]],
    model_mode: str | None = None,
) -> dict[str, Any]:
    """Route a coaching-JSON request to Nemotron (mode=scorecard_coaching).

    Nemotron generates only: improved_answer, improved_pitch, top_3_questions.
    Thinking is OFF for this mode — direct JSON output is faster and more reliable.
    """
    mode = _resolve_mode(model_mode)

    if mode == "premium_nvidia":
        try:
            content = nvidia_client.generate_nemotron_response(
                messages, mode="scorecard_coaching"
            )
            return {
                "ok": True,
                "model_mode": mode,
                "provider": "nvidia",
                "content": content,
                "error": None,
            }
        except RuntimeError as exc:
            logger.warning("NVIDIA coaching call failed: %s", exc)
            return {
                "ok": False,
                "model_mode": mode,
                "provider": "nvidia",
                "content": "",
                "error": str(exc),
            }

    return _placeholder_result(mode, "mock", f"Coaching via '{mode}' not implemented.")


def generate_coaching_repair_response(
    raw_bad_content: str,
    model_mode: str | None = None,
) -> dict[str, Any]:
    """Repair a non-JSON coaching response into valid JSON (mode=scorecard_coaching_repair)."""
    mode = _resolve_mode(model_mode)

    if mode != "premium_nvidia":
        return _placeholder_result(mode, "mock", "Coaching repair only available for premium_nvidia.")

    repair_messages = [
        {
            "role": "system",
            "content": (
                "You are a JSON formatter. Convert the input text into the exact JSON schema below. "
                "Return ONLY valid JSON. First character must be { and last must be }. "
                "No markdown. No explanation. No preface.\n\n"
                "REQUIRED SCHEMA:\n"
                '{"improved_answer": "", "improved_pitch": "", "top_3_questions": ["", "", ""]}'
            ),
        },
        {
            "role": "user",
            "content": (
                "Convert this text into the JSON schema. Output JSON only:\n\n"
                + raw_bad_content[:4000]
            ),
        },
    ]

    try:
        content = nvidia_client.generate_nemotron_response(
            repair_messages, mode="scorecard_coaching_repair"
        )
        return {
            "ok": True,
            "model_mode": mode,
            "provider": "nvidia",
            "content": content,
            "error": None,
        }
    except RuntimeError as exc:
        logger.warning("NVIDIA coaching repair call failed: %s", exc)
        return {
            "ok": False,
            "model_mode": mode,
            "provider": "nvidia",
            "content": "",
            "error": str(exc),
        }


def generate_scorecard_repair_response(
    raw_bad_content: str,
    model_mode: str | None = None,
) -> dict[str, Any]:
    """Ask Nemotron to repair a non-JSON scorecard response into valid JSON.

    Called when the primary scorecard call returns content that cannot be parsed.
    Uses temperature=0.0 and mode='scorecard_repair' for a deterministic rewrite.

    Voice mode note:
        Input is model text output — no source-specific changes needed.
    """
    mode = _resolve_mode(model_mode)

    if mode != "premium_nvidia":
        return _placeholder_result(mode, "mock", "Repair only available for premium_nvidia.")

    repair_messages = [
        {
            "role": "system",
            "content": (
                "You are a JSON formatter. "
                "Convert the input text into the exact JSON schema shown below. "
                "Return ONLY valid JSON. The first character must be { and the last must be }. "
                "No markdown. No explanation. No preface. No chain-of-thought. "
                "Fill every field. Use 0 for missing scores. Use empty string for missing text.\n\n"
                "REQUIRED SCHEMA:\n"
                '{\n'
                '  "overall": 0,\n'
                '  "scores": {\n'
                '    "clarity":               {"score": 0, "reason": "", "quote": "", "signals_used": []},\n'
                '    "problem_understanding": {"score": 0, "reason": "", "quote": "", "signals_used": []},\n'
                '    "market_awareness":      {"score": 0, "reason": "", "quote": "", "signals_used": []},\n'
                '    "differentiation":       {"score": 0, "reason": "", "quote": "", "signals_used": []},\n'
                '    "business_model":        {"score": 0, "reason": "", "quote": "", "signals_used": []},\n'
                '    "objection_handling":    {"score": 0, "reason": "", "quote": "", "signals_used": []}\n'
                '  },\n'
                '  "best_answer": "",\n'
                '  "weakest_answer": "",\n'
                '  "why_weak": "",\n'
                '  "improved_answer": "",\n'
                '  "improved_pitch": "",\n'
                '  "top_3_questions": ["", "", ""]\n'
                "}"
            ),
        },
        {
            "role": "user",
            "content": (
                "Convert this text into the JSON schema. "
                "Extract scores and reasoning from the text below. "
                "Output JSON only:\n\n"
                + raw_bad_content[:6000]
            ),
        },
    ]

    try:
        content = nvidia_client.generate_nemotron_response(
            repair_messages,
            mode="scorecard_repair",
        )
        return {
            "ok": True,
            "model_mode": mode,
            "provider": "nvidia",
            "content": content,
            "error": None,
        }
    except RuntimeError as exc:
        logger.warning("NVIDIA scorecard repair call failed: %s", exc)
        return {
            "ok": False,
            "model_mode": mode,
            "provider": "nvidia",
            "content": "",
            "error": str(exc),
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _call_nvidia_opponent(messages: list[dict], mode: str) -> dict[str, Any]:
    try:
        content = nvidia_client.generate_nemotron_response(messages, mode="opponent")
        return {
            "ok": True,
            "model_mode": mode,
            "provider": "nvidia",
            "content": content,
            "error": None,
        }
    except RuntimeError as exc:
        logger.warning("NVIDIA opponent call failed: %s", exc)
        return {
            "ok": False,
            "model_mode": mode,
            "provider": "nvidia",
            "content": _FALLBACK_OPPONENT_MESSAGE,
            "error": str(exc),
        }


def _call_nvidia_scorecard(messages: list[dict], mode: str) -> dict[str, Any]:
    try:
        content = nvidia_client.generate_nemotron_response(messages, mode="scorecard")
        return {
            "ok": True,
            "model_mode": mode,
            "provider": "nvidia",
            "content": content,
            "error": None,
        }
    except RuntimeError as exc:
        logger.warning("NVIDIA scorecard call failed: %s", exc)
        return {
            "ok": False,
            "model_mode": mode,
            "provider": "nvidia",
            "content": "",
            "error": str(exc),
            "fallback_scorecard": _FALLBACK_SCORECARD,
        }


def _placeholder_result(mode: str, provider: str, message: str) -> dict[str, Any]:
    return {
        "ok": False,
        "model_mode": mode,
        "provider": provider,
        "content": _FALLBACK_OPPONENT_MESSAGE,
        "error": message,
    }
