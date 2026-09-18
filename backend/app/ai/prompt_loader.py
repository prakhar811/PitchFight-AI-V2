"""Prompt resource loader.

Reads versioned Markdown prompt files from app/ai/prompts/. Infrastructure
only — no persona/difficulty/task resolution logic lives here, that's
prompt_builder.py's job. A safe in-process cache (functools.cache) is
enough: these are static files read at process lifetime, not per-request
state, so no Redis caching is needed here.
"""

from functools import cache
from pathlib import Path

_PROMPTS_DIR = Path(__file__).parent / "prompts"


class PromptResourceNotFoundError(Exception):
    """A requested prompt resource file doesn't exist on disk."""


@cache
def load_prompt_resource(relative_path: str) -> str:
    """Load one prompt file, e.g. "shared/base_judge.md" or
    "personas/skeptical_vc_v1.md", relative to app/ai/prompts/."""
    path = _PROMPTS_DIR / relative_path
    try:
        return path.read_text(encoding="utf-8").strip()
    except FileNotFoundError as exc:
        raise PromptResourceNotFoundError(f"Prompt resource not found: {relative_path}") from exc
