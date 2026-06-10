"""Backend-only NVIDIA Nemotron API client.

All calls are backend-only. API key is never passed to the frontend.
Key is read from NVIDIA_API_KEY environment variable only.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI, APIConnectionError, APIStatusError, APITimeoutError

load_dotenv()

logger = logging.getLogger(__name__)

_DEFAULT_BASE_URL = "https://integrate.api.nvidia.com/v1"
_DEFAULT_MODEL = "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning"


class OmniAudioError(RuntimeError):
    """Structured Omni audio failure — metadata safe for API responses."""

    def __init__(self, message: str, **meta: Any) -> None:
        super().__init__(message)
        self.meta = meta

    def to_error_dict(self) -> dict[str, Any]:
        return {
            "error": "Omni audio call failed",
            "detail": str(self),
            **self.meta,
        }


# Per-mode settings for nemotron-3-nano-omni-30b-a3b-reasoning.
#
# enable_thinking: True  → reasoning model uses internal chain-of-thought
#                  False → thinking disabled; output is direct (faster, cheaper)
# reasoning_budget: token budget for internal reasoning (clamped to max_tokens)
#
# Modes in main path:
#   opponent                  — live judge questions during battle (thinking on)
#   scorecard_coaching        — coaching JSON only (thinking off — faster, more reliable JSON)
#   scorecard_coaching_repair — JSON repair for coaching output (thinking off)
#   rewrite                   — rewrite utility (thinking on, lighter budget)
#   legacy_full_scorecard     — diagnostic / legacy path only; not main path (thinking off)
_TASK_DEFAULTS: dict[str, dict[str, Any]] = {
    "opponent": {
        "enable_thinking": True,
        "reasoning_budget": 512,
        "max_tokens": 900,
        "temperature": 0.65,
        "top_p": 0.95,
    },
    "scorecard_scoring": {
        "enable_thinking": False,
        "reasoning_budget": 0,
        "max_tokens": 1700,
        "temperature": 0.1,
        "top_p": 0.95,
    },
    "scorecard_scoring_repair": {
        "enable_thinking": False,
        "reasoning_budget": 0,
        "max_tokens": 1400,
        "temperature": 0.0,
        "top_p": 0.95,
    },
    "scorecard_full": {
        "enable_thinking": False,
        "reasoning_budget": 0,
        "max_tokens": 2500,
        "temperature": 0.1,
        "top_p": 0.95,
    },
    "scorecard_full_repair": {
        "enable_thinking": False,
        "reasoning_budget": 0,
        "max_tokens": 2200,
        "temperature": 0.0,
        "top_p": 0.95,
    },
    "scorecard_coaching": {
        "enable_thinking": False,
        "reasoning_budget": 0,
        "max_tokens": 2400,
        "temperature": 0.2,
        "top_p": 0.95,
    },
    "scorecard_coaching_repair": {
        "enable_thinking": False,
        "reasoning_budget": 0,
        "max_tokens": 1600,
        "temperature": 0.0,
        "top_p": 0.95,
    },
    "rewrite": {
        "enable_thinking": True,
        "reasoning_budget": 256,
        "max_tokens": 900,
        "temperature": 0.45,
        "top_p": 0.95,
    },
    "legacy_full_scorecard": {
        "enable_thinking": False,
        "reasoning_budget": 0,
        "max_tokens": 3000,
        "temperature": 0.1,
        "top_p": 0.95,
    },
    "voice_extraction": {
        "enable_thinking": False,
        "reasoning_budget": 0,
        "max_tokens": 1800,
        "temperature": 0.1,
        "top_p": 0.95,
    },
    "voice_extraction_repair": {
        "enable_thinking": False,
        "reasoning_budget": 0,
        "max_tokens": 1200,
        "temperature": 0.0,
        "top_p": 0.95,
    },
    "voice_turn": {
        "enable_thinking": False,
        "reasoning_budget": 0,
        "max_tokens": 700,
        "temperature": 0.0,
        "top_p": 0.95,
    },
    "voice_turn_repair": {
        "enable_thinking": False,
        "reasoning_budget": 0,
        "max_tokens": 600,
        "temperature": 0.0,
        "top_p": 0.95,
    },
    "retry_comparison": {
        "enable_thinking": False,
        "reasoning_budget": 0,
        "max_tokens": 1000,
        "temperature": 0.15,
        "top_p": 0.95,
    },
    "retry_comparison_repair": {
        "enable_thinking": False,
        "reasoning_budget": 0,
        "max_tokens": 800,
        "temperature": 0.0,
        "top_p": 0.95,
    },
    "deal_verdict": {
        "enable_thinking": False,
        "reasoning_budget": 0,
        "max_tokens": 1000,
        "temperature": 0.2,
        "top_p": 0.95,
    },
    "deal_verdict_repair": {
        "enable_thinking": False,
        "reasoning_budget": 0,
        "max_tokens": 800,
        "temperature": 0.0,
        "top_p": 0.95,
    },
    "deal_round": {
        "enable_thinking": True,
        "reasoning_budget": 512,
        "max_tokens": 900,
        "temperature": 0.65,
        "top_p": 0.95,
    },
    # Deal phase: semantic dimension scoring (JSON, split call 1 — scores only)
    "deal_scorecard_scoring": {
        "enable_thinking": False,
        "reasoning_budget": 0,
        "max_tokens": 1700,
        "temperature": 0.1,
        "top_p": 0.95,
    },
    "deal_scorecard_scoring_repair": {
        "enable_thinking": False,
        "reasoning_budget": 0,
        "max_tokens": 1300,
        "temperature": 0.0,
        "top_p": 0.95,
    },
    # Deal phase: coaching text (JSON, split call 2 — coaching only)
    "deal_scorecard_coaching": {
        "enable_thinking": False,
        "reasoning_budget": 0,
        "max_tokens": 2200,
        "temperature": 0.2,
        "top_p": 0.95,
    },
    "deal_scorecard_repair": {
        "enable_thinking": False,
        "reasoning_budget": 0,
        "max_tokens": 1200,
        "temperature": 0.0,
        "top_p": 0.95,
    },
}

_VALID_AUDIO_FORMATS = frozenset({"webm", "wav", "mp3", "m4a", "ogg"})

_AUDIO_MIME: dict[str, str] = {
    "webm": "audio/webm",
    "wav": "audio/wav",
    "mp3": "audio/mpeg",
    "m4a": "audio/mp4",
    "ogg": "audio/ogg",
}

# Modes where the response must be JSON — apply safe extraction from reasoning_content if needed
_JSON_MODES: frozenset[str] = frozenset({
    "scorecard_scoring",
    "scorecard_scoring_repair",
    "scorecard_full",
    "scorecard_full_repair",
    "scorecard_coaching",
    "scorecard_coaching_repair",
    "legacy_full_scorecard",
    "voice_extraction",
    "voice_extraction_repair",
    "voice_turn",
    "voice_turn_repair",
    "retry_comparison",
    "retry_comparison_repair",
    "deal_verdict",
    "deal_verdict_repair",
    "deal_scorecard_scoring",
    "deal_scorecard_scoring_repair",
    "deal_scorecard_coaching",
    "deal_scorecard_repair",
})


def _extract_json_from_reasoning(reasoning: str) -> str | None:
    """Extract first complete JSON object block from reasoning_content."""
    start = reasoning.find("{")
    end = reasoning.rfind("}")
    if start != -1 and end != -1 and end > start:
        return reasoning[start : end + 1].strip()
    return None


def _get_config() -> tuple[str, str, str]:
    """Return (api_key, base_url, model). Raises RuntimeError if key is absent."""
    api_key = os.getenv("NVIDIA_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError(
            "NVIDIA_API_KEY is not set. "
            "Add it to your .env file locally or as a HF Space Secret in deployment. "
            "Never hardcode the key."
        )
    base_url = os.getenv("NVIDIA_BASE_URL", _DEFAULT_BASE_URL).strip() or _DEFAULT_BASE_URL
    model = os.getenv("NVIDIA_OMNI_MODEL", _DEFAULT_MODEL).strip() or _DEFAULT_MODEL
    return api_key, base_url, model


def is_configured() -> bool:
    """Return True if NVIDIA_API_KEY is present in the environment."""
    return bool(os.getenv("NVIDIA_API_KEY", "").strip())


def health_check() -> dict[str, Any]:
    """Return configuration status without exposing the API key."""
    configured = is_configured()
    base_url = os.getenv("NVIDIA_BASE_URL", _DEFAULT_BASE_URL)
    model = os.getenv("NVIDIA_OMNI_MODEL", _DEFAULT_MODEL)
    return {
        "provider": "nvidia",
        "configured": configured,
        "base_url": base_url,
        "model": model,
        "api_key_present": configured,
        "message": (
            "NVIDIA client ready" if configured
            else "NVIDIA_API_KEY missing — add to .env or HF Space Secrets"
        ),
    }


def _resolve_mode_params(
    mode: str,
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> tuple[float, int, float, bool, int]:
    """Return (temp, tokens, top_p, enable_thinking, reasoning_budget) for a mode."""
    defaults = _TASK_DEFAULTS.get(mode, _TASK_DEFAULTS["opponent"])
    temp = temperature if temperature is not None else defaults["temperature"]
    tokens = max_tokens if max_tokens is not None else defaults["max_tokens"]
    top_p: float = defaults.get("top_p", 0.95)
    enable_thinking: bool = defaults.get("enable_thinking", True)
    reasoning_budget: int = defaults.get("reasoning_budget", 0)
    if mode in _JSON_MODES:
        enable_thinking = False
        reasoning_budget = 0
    reasoning_budget = min(reasoning_budget, tokens)
    return temp, tokens, top_p, enable_thinking, reasoning_budget


def _complete_chat(
    client: OpenAI,
    model: str,
    messages: list[dict],
    mode: str,
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> str:
    """Shared chat completion with mode-specific token/thinking settings."""
    temp, tokens, top_p, enable_thinking, reasoning_budget = _resolve_mode_params(
        mode, temperature, max_tokens
    )
    completion = client.chat.completions.create(
        model=model,
        messages=messages,  # type: ignore[arg-type]
        temperature=temp,
        max_tokens=tokens,
        top_p=top_p,
        extra_body={
            "chat_template_kwargs": {"enable_thinking": enable_thinking},
            "reasoning_budget": reasoning_budget,
        },
    )
    temp_d, tokens_d, _tp, thinking_d, _rb = _resolve_mode_params(mode, temperature, max_tokens)
    msg = completion.choices[0].message
    content = (msg.content or "").strip()
    reasoning = (getattr(msg, "reasoning_content", None) or "").strip()

    # Diagnostics (no secrets, no full prompt/audio): help spot truncation vs empty content.
    logger.debug(
        "Nemotron mode=%s max_tokens=%s thinking=%s content_len=%d reasoning_present=%s",
        mode, tokens_d, thinking_d, len(content), bool(reasoning),
    )

    if not content:
        if mode in _JSON_MODES and reasoning:
            extracted = _extract_json_from_reasoning(reasoning)
            if extracted:
                logger.info(
                    "Nemotron content empty; extracted JSON block from reasoning_content (mode=%s)",
                    mode,
                )
                content = extracted
            else:
                logger.warning(
                    "Nemotron content empty; checked reasoning_content fallback (mode=%s, no JSON found)",
                    mode,
                )
        elif reasoning:
            logger.warning(
                "Nemotron content empty; checked reasoning_content fallback (mode=%s)",
                mode,
            )
            content = reasoning

    if not content:
        raise RuntimeError(
            "NVIDIA model returned an empty response. "
            "The reasoning model may need a larger max_tokens budget."
        )
    return content


def call_omni_audio_json(
    prompt: str,
    audio_base64: str,
    audio_format: str,
    mode: str = "voice_extraction",
    timeout: int = 60,
    source_format: str | None = None,
    decoded_bytes: int | None = None,
) -> str:
    """Call Nemotron Omni with audio + text prompt; return response text (JSON expected).

    Raises:
        ValueError: invalid audio input
        OmniAudioError: API rejected audio or call failed
    """
    if not audio_base64 or not str(audio_base64).strip():
        raise ValueError("audio_base64 is required and must be non-empty")
    fmt = str(audio_format or "").strip().lower().lstrip(".")
    if fmt not in _VALID_AUDIO_FORMATS:
        raise ValueError(
            f"audio_format must be one of: {', '.join(sorted(_VALID_AUDIO_FORMATS))}"
        )

    api_key, base_url, model = _get_config()
    mime = _AUDIO_MIME[fmt]
    audio_url = f"data:{mime};base64,{audio_base64.strip()}"

    logger.info(
        "nvidia_client: omni audio call mode=%s format=%s source_format=%s bytes=%s mime=%s",
        mode,
        fmt,
        source_format or fmt,
        decoded_bytes if decoded_bytes is not None else "unknown",
        mime,
    )

    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "audio_url", "audio_url": {"url": audio_url}},
            ],
        }
    ]

    client = OpenAI(api_key=api_key, base_url=base_url, timeout=timeout)
    try:
        return _complete_chat(client, model, messages, mode)
    except APIStatusError as exc:
        detail = exc.message or str(exc)
        logger.warning(
            "NVIDIA Omni audio status error %s: %s (format=%s bytes=%s)",
            exc.status_code,
            detail,
            fmt,
            decoded_bytes,
        )
        raise OmniAudioError(
            detail,
            audio_format_sent=fmt,
            source_format=source_format or fmt,
            decoded_bytes=decoded_bytes,
            mode=mode,
            suggestion=(
                "Audio was normalized to WAV when possible. "
                "Verify NVIDIA audio payload schema or install ffmpeg for conversion."
            ),
        ) from exc
    except (APITimeoutError, APIConnectionError) as exc:
        logger.warning("NVIDIA Omni audio connection error: %s", type(exc).__name__)
        raise OmniAudioError(
            f"Connection error: {type(exc).__name__}",
            audio_format_sent=fmt,
            source_format=source_format or fmt,
            decoded_bytes=decoded_bytes,
            mode=mode,
            suggestion="Retry the voice request or check NVIDIA API connectivity.",
        ) from exc
    except RuntimeError:
        raise
    except Exception as exc:
        logger.warning("NVIDIA Omni audio unexpected error: %s", type(exc).__name__)
        raise OmniAudioError(
            type(exc).__name__,
            audio_format_sent=fmt,
            source_format=source_format or fmt,
            decoded_bytes=decoded_bytes,
            mode=mode,
            suggestion="Verify NVIDIA audio payload schema or audio conversion.",
        ) from exc


def generate_nemotron_response(
    messages: list[dict[str, str]],
    mode: str = "opponent",
    temperature: float | None = None,
    max_tokens: int | None = None,
    timeout: int = 30,
) -> str:
    """Call NVIDIA Nemotron and return the response text.

    Args:
        messages: OpenAI-format message list [{"role": ..., "content": ...}, ...]
        mode: task type key — "opponent", "scorecard_coaching", "rewrite", etc.
        temperature: overrides mode default if provided
        max_tokens: overrides mode default if provided
        timeout: request timeout in seconds

    Returns:
        Response text string from the model.

    Raises:
        RuntimeError: on missing key or any API failure (clean message, no key leak).
    """
    api_key, base_url, model = _get_config()
    client = OpenAI(api_key=api_key, base_url=base_url, timeout=timeout)

    # One retry on transient server/rate errors only — never retry 4xx (e.g. bad audio 400).
    for attempt in range(2):
        try:
            return _complete_chat(client, model, messages, mode, temperature, max_tokens)

        except APITimeoutError:
            logger.warning("NVIDIA API timed out after %ds (mode=%s)", timeout, mode)
            raise RuntimeError(
                f"NVIDIA Nemotron request timed out after {timeout}s. "
                "Check your connection or increase timeout."
            )
        except APIConnectionError as exc:
            if attempt == 0:
                logger.warning("NVIDIA connection error (mode=%s) — retrying once", mode)
                time.sleep(0.8)
                continue
            logger.warning("NVIDIA API connection error: %s", exc)
            raise RuntimeError(
                "Could not connect to NVIDIA API. "
                "Verify NVIDIA_BASE_URL and your network connection."
            )
        except APIStatusError as exc:
            transient = exc.status_code in (429, 500, 502, 503)
            if transient and attempt == 0:
                logger.warning(
                    "NVIDIA transient HTTP %s (mode=%s) — retrying once", exc.status_code, mode
                )
                time.sleep(0.8)
                continue
            logger.warning(
                "NVIDIA API status error %s (mode=%s): %s", exc.status_code, mode, exc.message
            )
            raise RuntimeError(
                f"NVIDIA API returned HTTP {exc.status_code}. "
                "Check your NVIDIA_API_KEY and model ID."
            )
        except Exception as exc:
            logger.warning("NVIDIA API unexpected error (mode=%s): %s", mode, type(exc).__name__)
            raise RuntimeError(
                f"NVIDIA model call failed ({type(exc).__name__}). See server logs."
            )

    # Unreachable (loop either returns or raises) — defensive.
    raise RuntimeError("NVIDIA model call failed after retry.")
