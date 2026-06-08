"""Backend-only NVIDIA Nemotron API client.

All calls are backend-only. API key is never passed to the frontend.
Key is read from NVIDIA_API_KEY environment variable only.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI, APIConnectionError, APIStatusError, APITimeoutError

load_dotenv()

logger = logging.getLogger(__name__)

_DEFAULT_BASE_URL = "https://integrate.api.nvidia.com/v1"
_DEFAULT_MODEL = "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning"

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
    "scorecard_coaching": {
        "enable_thinking": False,
        "reasoning_budget": 0,
        "max_tokens": 1600,
        "temperature": 0.2,
        "top_p": 0.95,
    },
    "scorecard_coaching_repair": {
        "enable_thinking": False,
        "reasoning_budget": 0,
        "max_tokens": 1200,
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
}

# Modes where the response must be JSON — apply safe extraction from reasoning_content if needed
_JSON_MODES: frozenset[str] = frozenset({
    "scorecard_coaching",
    "scorecard_coaching_repair",
    "legacy_full_scorecard",
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

    defaults = _TASK_DEFAULTS.get(mode, _TASK_DEFAULTS["opponent"])
    temp = temperature if temperature is not None else defaults["temperature"]
    tokens = max_tokens if max_tokens is not None else defaults["max_tokens"]
    top_p: float = defaults.get("top_p", 0.95)
    enable_thinking: bool = defaults.get("enable_thinking", True)
    # reasoning_budget must not exceed max_tokens
    reasoning_budget: int = min(defaults.get("reasoning_budget", 0), tokens)

    client = OpenAI(
        api_key=api_key,
        base_url=base_url,
        timeout=timeout,
    )

    try:
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
        msg = completion.choices[0].message
        content = (msg.content or "").strip()
        reasoning = (getattr(msg, "reasoning_content", None) or "").strip()

        if not content:
            if mode in _JSON_MODES and reasoning:
                # For JSON modes: try to salvage a JSON block from reasoning_content
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
                # Non-JSON mode (e.g. opponent): use reasoning trace as last resort
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

    except APITimeoutError:
        logger.warning("NVIDIA API timed out after %ds (mode=%s)", timeout, mode)
        raise RuntimeError(
            f"NVIDIA Nemotron request timed out after {timeout}s. "
            "Check your connection or increase timeout."
        )
    except APIConnectionError as exc:
        logger.warning("NVIDIA API connection error: %s", exc)
        raise RuntimeError(
            "Could not connect to NVIDIA API. "
            "Verify NVIDIA_BASE_URL and your network connection."
        )
    except APIStatusError as exc:
        logger.warning("NVIDIA API status error %s: %s", exc.status_code, exc.message)
        raise RuntimeError(
            f"NVIDIA API returned HTTP {exc.status_code}. "
            "Check your NVIDIA_API_KEY and model ID."
        )
    except Exception as exc:
        logger.warning("NVIDIA API unexpected error: %s", type(exc).__name__)
        raise RuntimeError(
            f"NVIDIA model call failed ({type(exc).__name__}). See server logs."
        )
