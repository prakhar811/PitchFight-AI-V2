"""Tests for JSON parsing utilities."""

import json
import unittest

from core.json_utils import extract_json_block, fallback_scorecard, safe_json_parse


class TestJsonParser(unittest.TestCase):
    def test_safe_json_parse_raw_object(self):
        payload = {"overall": 70, "scores": {}}
        result = safe_json_parse(json.dumps(payload))
        self.assertEqual(result["overall"], 70)

    def test_safe_json_parse_fenced_block(self):
        text = 'Here is the score:\n```json\n{"overall": 55}\n```'
        result = safe_json_parse(text)
        self.assertEqual(result["overall"], 55)

    def test_safe_json_parse_invalid_returns_default(self):
        result = safe_json_parse("not json at all", default={"ok": False})
        self.assertEqual(result, {"ok": False})

    def test_extract_json_block_from_text(self):
        text = 'Analysis complete {"round": 2, "tag": "Moat"} thanks.'
        block = extract_json_block(text)
        self.assertIsNotNone(block)
        self.assertEqual(json.loads(block)["tag"], "Moat")

    def test_fallback_scorecard_shape(self):
        card = fallback_scorecard()
        self.assertIn("overall", card)
        self.assertIn("scores", card)
        self.assertIn("top_3_questions", card)


if __name__ == "__main__":
    unittest.main()
