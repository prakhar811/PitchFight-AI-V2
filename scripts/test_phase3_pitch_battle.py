"""Phase 3 end-to-end test: live pitch battle via the running server.

Usage:
  python scripts/test_phase3_pitch_battle.py

Requires the server to already be running. Set PITCHFIGHT_BASE_URL to override
the default base URL (http://127.0.0.1:7861).
"""

from __future__ import annotations

import json
import os
import sys

import requests

BASE_URL = os.getenv("PITCHFIGHT_BASE_URL", "http://127.0.0.1:7861").rstrip("/")

SAMPLE_STARTUP = {
    "name": "EventRadar AI",
    "problem": "Students miss relevant hackathons, workshops, and networking events.",
    "solution": "AI-powered event discovery that ranks events by fit for each student profile.",
    "why_ai": "Personalized ranking requires understanding student goals and event signals together.",
    "stage": "Prototype",
    "team": "2 founders",
    "traction": "50 beta signups, no revenue yet",
}

USER_ANSWER = (
    "It is a pretty big market because students attend events often."
)


def post(path: str, body: dict) -> dict:
    url = f"{BASE_URL}{path}"
    resp = requests.post(url, json=body, timeout=60)
    resp.raise_for_status()
    return resp.json()


def check(label: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {label}")
    else:
        print(f"  FAIL  {label}" + (f" — {detail}" if detail else ""))
        sys.exit(1)


def main() -> None:
    print(f"\nPhase 3 Pitch Battle Test\nBase URL: {BASE_URL}\n")

    # --- Step 1: start-session ---
    print("Step 1: POST /api/start-session")
    try:
        data = post("/api/start-session", {
            "mode": "pitch_battle",
            "startup": SAMPLE_STARTUP,
            "persona": "hackathon_judge",
            "difficulty": "high",
            "input_mode": "text",
            "model_mode": "premium_nvidia",
        })
    except Exception as exc:
        print(f"  FAIL  Request failed: {exc}")
        sys.exit(1)

    print(f"  session_id : {data.get('session_id', '—')}")
    print(f"  model_ok   : {data.get('model_ok')}")
    print(f"  provider   : {data.get('provider')}")
    print(f"  model_mode : {data.get('model_mode')}")
    print(f"  attack_tag : {data.get('attack_tag')}")
    print(f"  round      : {data.get('round')}")
    print(f"  ai_message :\n    {data.get('ai_message', '')}\n")

    session_id = data.get("session_id")
    check("session_id present", bool(session_id), "got empty session_id")
    check("ai_message non-empty", bool(data.get("ai_message")), "ai_message is empty")
    check("round is 1", data.get("round") == 1, f"got {data.get('round')}")
    check("attack_tag present", bool(data.get("attack_tag")))

    if data.get("model_ok"):
        check("provider is nvidia", data.get("provider") == "nvidia")
    else:
        print("  NOTE  Model returned mock fallback (NVIDIA may be down or key missing)")
        if data.get("model_error"):
            print(f"  model_error: {data['model_error']}")

    # --- Step 2: chat-round ---
    print("\nStep 2: POST /api/chat-round")
    try:
        data2 = post("/api/chat-round", {
            "session_id": session_id,
            "user_message": USER_ANSWER,
        })
    except Exception as exc:
        print(f"  FAIL  Request failed: {exc}")
        sys.exit(1)

    print(f"  model_ok   : {data2.get('model_ok')}")
    print(f"  provider   : {data2.get('provider')}")
    print(f"  model_mode : {data2.get('model_mode')}")
    print(f"  attack_tag : {data2.get('attack_tag')}")
    print(f"  round      : {data2.get('round')}")
    print(f"  ai_message :\n    {data2.get('ai_message', '')}\n")

    check("session_id echoed", data2.get("session_id") == session_id)
    check("ai_message non-empty", bool(data2.get("ai_message")), "ai_message is empty")
    check("round is 2", data2.get("round") == 2, f"got {data2.get('round')}")

    if data2.get("model_ok"):
        check("provider is nvidia", data2.get("provider") == "nvidia")
    else:
        print("  NOTE  chat-round returned mock fallback")
        if data2.get("model_error"):
            print(f"  model_error: {data2['model_error']}")

    print("\nAll checks passed. Phase 3 integration is working.\n")
    sys.exit(0)


if __name__ == "__main__":
    main()
