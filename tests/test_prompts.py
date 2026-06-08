"""Tests for persona prompt builder."""

import unittest

from core.persona_builder import build_persona_prompt
from core.samples import get_sample_startup


class TestPrompts(unittest.TestCase):
    def test_persona_prompt_not_empty(self):
        startup = get_sample_startup()
        prompt = build_persona_prompt("hackathon_judge", startup, difficulty="high")
        self.assertTrue(prompt.strip())

    def test_persona_prompt_includes_startup_name(self):
        startup = get_sample_startup()
        prompt = build_persona_prompt("technical_judge", startup)
        self.assertIn("EventRadar AI", prompt)

    def test_all_personas_build(self):
        startup = get_sample_startup()
        for persona in ("skeptical_vc", "technical_judge", "hackathon_judge"):
            prompt = build_persona_prompt(persona, startup)
            self.assertIn("Ask one sharp question", prompt)


if __name__ == "__main__":
    unittest.main()
