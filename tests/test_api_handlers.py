"""Tests for shared API handlers."""

import unittest

from core.api_handlers import (
    handle_chat_round,
    handle_end_battle,
    handle_load_sample,
    handle_reset_session,
    handle_start_session,
    handle_voice_pitch_placeholder,
)


class TestApiHandlers(unittest.TestCase):
    def test_load_sample(self):
        result = handle_load_sample()
        self.assertIn("startup", result)
        self.assertEqual(result["startup"]["name"], "EventRadar AI")

    def test_full_battle_flow(self):
        start = handle_start_session(
            {
                "persona": "hackathon_judge",
                "difficulty": "high",
                "input_mode": "text",
                "startup": handle_load_sample()["startup"],
            }
        )
        session_id = start["session_id"]
        self.assertEqual(start["round"], 1)

        chat = handle_chat_round(
            {"session_id": session_id, "user_message": "We rank events with AI."}
        )
        self.assertEqual(chat["session_id"], session_id)
        self.assertEqual(chat["round"], 2)

        scorecard = handle_end_battle({"session_id": session_id})
        self.assertIn("overall", scorecard)
        self.assertIn("scores", scorecard)

        reset = handle_reset_session({"session_id": session_id})
        self.assertEqual(reset["status"], "reset")

    def test_voice_placeholder(self):
        result = handle_voice_pitch_placeholder()
        self.assertEqual(result["status"], "not_implemented")


if __name__ == "__main__":
    unittest.main()
