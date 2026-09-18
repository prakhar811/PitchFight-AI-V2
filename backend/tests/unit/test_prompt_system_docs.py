"""Sanity check that the Prompt System guide exists and covers the basics.
Not an elaborate documentation test — just enough to catch a stale/missing doc.
"""

from pathlib import Path

_DOC_PATH = (
    Path(__file__).resolve().parents[3] / "docs" / "architecture" / "PROMPT_SYSTEM_GUIDE.md"
)


def test_prompt_system_guide_exists() -> None:
    assert _DOC_PATH.is_file()


def test_prompt_system_guide_mentions_all_personas_and_difficulties() -> None:
    text = _DOC_PATH.read_text(encoding="utf-8")
    for marker in (
        "Skeptical VC",
        "Technical Judge",
        "Hackathon Judge",
        "PRACTICE",
        "JUDGE",
        "INVESTOR",
    ):
        assert marker in text
