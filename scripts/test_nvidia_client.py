"""Isolated NVIDIA Nemotron connectivity test.

Run from the project root:
    python scripts/test_nvidia_client.py

Exits 0 on success, 1 on failure.
Does not expose the API key in output.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Allow imports from project root regardless of working directory
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv()

from core.nvidia_client import health_check, generate_nemotron_response  # noqa: E402


def main() -> int:
    print("=" * 60)
    print("PitchFight AI — NVIDIA Nemotron connectivity test")
    print("=" * 60)

    # 1. Health check (no key in output)
    print("\n[1] Health check")
    status = health_check()
    print(f"  provider    : {status['provider']}")
    print(f"  configured  : {status['configured']}")
    print(f"  base_url    : {status['base_url']}")
    print(f"  model       : {status['model']}")
    print(f"  key present : {status['api_key_present']}")
    print(f"  message     : {status['message']}")

    if not status["configured"]:
        print("\n[FAIL] NVIDIA_API_KEY is not set.")
        print("  Add it to your .env file and re-run this script.")
        return 1

    # 2. Test prompt
    print("\n[2] Sending test prompt to Nemotron...")
    messages = [
        {
            "role": "system",
            "content": (
                "You are a skeptical hackathon judge. "
                "Ask exactly one sharp question. Do not give advice."
            ),
        },
        {
            "role": "user",
            "content": (
                "Startup: EventRadar AI.\n"
                "Problem: Students miss hackathons and tech events because "
                "discovery is scattered.\n"
                "Solution: AI-powered event discovery that ranks opportunities "
                "by skills, goals, location, and deadline urgency.\n\n"
                "Return exactly one question under 40 words."
            ),
        },
    ]

    try:
        response = generate_nemotron_response(
            messages,
            mode="opponent",
            temperature=0.7,
            timeout=30,
        )
        print("\n[3] Model response:")
        print("-" * 40)
        print(response)
        print("-" * 40)
        print("\n[PASS] NVIDIA Nemotron responded successfully.")
        print("Phase 2 model connectivity: OK")
        return 0

    except RuntimeError as exc:
        print(f"\n[FAIL] {exc}")
        print("Check your NVIDIA_API_KEY and NVIDIA_BASE_URL in .env")
        return 1


if __name__ == "__main__":
    sys.exit(main())
