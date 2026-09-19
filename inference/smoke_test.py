"""Standalone smoke test for the deployed PitchFight Nemotron vLLM server.

Tests the server independently of PitchFight's backend/PromptBuilder:
    1. GET  /v1/models             — served model is present
    2. POST /v1/chat/completions   — basic generation works
    3. POST /v1/chat/completions   — simple JSON-only output (natural
       instruction-following, not constrained/guided decoding — this is
       how Phase 10's PromptBuilder currently asks for structured output)
    4. POST /v1/chat/completions x3 — one tiny prompt per locked persona,
       just to sanity-check basic persona-following behavior (NOT using
       the real PromptBuilder/prompt system yet)

Usage:
    python inference/smoke_test.py <base_url>

    e.g. python inference/smoke_test.py https://your-workspace--pitchfight-nemotron-inference-server.modal.run

Authentication: this server requires Modal proxy authentication (the
deployment does not set unauthenticated=True). Generate a Proxy Auth
Token for this app's environment from the Modal dashboard, then export:

    MODAL_KEY=wk-...
    MODAL_SECRET=ws-...

Never print these values. This script never does.
"""

import json
import os
import sys

from openai import OpenAI

from config import SERVED_MODEL_NAME

PERSONA_PROMPTS = [
    (
        "Skeptical VC",
        "You are a skeptical venture capitalist evaluating a startup pitch. "
        "Ask one sharp, concise question about the business model or market.",
    ),
    (
        "Technical Judge",
        "You are a technical judge evaluating a startup's engineering choices. "
        "Ask one sharp, concise question about their technical architecture.",
    ),
    (
        "Hackathon Judge",
        "You are a hackathon judge evaluating a project. Ask one sharp, "
        "concise question about novelty or what was actually built.",
    ),
]

MOCK_PITCH = (
    "Our startup uses AI to match college students with hackathons and "
    "events based on their skills, goals, and location."
)

# Nemotron 3.5 has "thinking" (reasoning) enabled by default, which consumes
# our small max_tokens budget on the reasoning channel before any final
# content is produced — confirmed manually. Disable it via vLLM's
# chat_template_kwargs passthrough for every normal Phase 12A request.
DISABLE_THINKING_EXTRA_BODY = {"chat_template_kwargs": {"enable_thinking": False}}


def _auth_headers() -> dict[str, str]:
    key = os.environ.get("MODAL_KEY")
    secret = os.environ.get("MODAL_SECRET")
    if not key or not secret:
        print(
            "WARNING: MODAL_KEY/MODAL_SECRET not set — requests will fail with "
            "401 unless this deployment is unauthenticated.",
            file=sys.stderr,
        )
        return {}
    return {"Modal-Key": key, "Modal-Secret": secret}


def test_models_endpoint(client: OpenAI) -> bool:
    print("1. GET /v1/models")
    models = client.models.list()
    model_ids = [m.id for m in models.data]
    print(f"   served models: {model_ids}")
    if SERVED_MODEL_NAME not in model_ids:
        print(f"   FAIL: expected served model {SERVED_MODEL_NAME!r} not found")
        return False
    print("   OK")
    return True


def test_chat_completion(client: OpenAI) -> bool:
    print("2. POST /v1/chat/completions (basic)")
    response = client.chat.completions.create(
        model=SERVED_MODEL_NAME,
        messages=[
            {"role": "system", "content": "You are a concise startup pitch evaluator."},
            {
                "role": "user",
                "content": (
                    "A startup says it uses AI to help restaurants predict food waste. "
                    "Ask one concise skeptical question."
                ),
            },
        ],
        max_tokens=100,
        extra_body=DISABLE_THINKING_EXTRA_BODY,
    )
    content = response.choices[0].message.content or ""
    print(f"   finish_reason={response.choices[0].finish_reason}")
    print(f"   content={content!r}")
    if not content.strip():
        print("   FAIL: empty generated content")
        return False
    print("   OK")
    return True


def test_json_output(client: OpenAI) -> bool:
    print("3. POST /v1/chat/completions (JSON-only output)")
    response = client.chat.completions.create(
        model=SERVED_MODEL_NAME,
        messages=[
            {
                "role": "system",
                "content": (
                    "Respond with ONLY a single valid JSON object with exactly these "
                    'fields: "question" (string), "attack_tag" (string), '
                    '"is_follow_up" (boolean). No other text, no markdown fences.'
                ),
            },
            {
                "role": "user",
                "content": f"Startup pitch: {MOCK_PITCH}",
            },
        ],
        max_tokens=150,
        extra_body=DISABLE_THINKING_EXTRA_BODY,
    )
    content = (response.choices[0].message.content or "").strip()
    print(f"   raw content={content!r}")
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as exc:
        print(f"   RESULT: not parseable JSON ({exc}) — recorded, not treated as a hard failure")
        return False
    expected_keys = {"question", "attack_tag", "is_follow_up"}
    if not expected_keys.issubset(parsed.keys()):
        print(f"   RESULT: parsed JSON but missing expected keys: {parsed.keys()}")
        return False
    print("   OK: valid JSON with expected keys")
    return True


def test_persona_prompts(client: OpenAI) -> None:
    print("4. Persona sanity checks (not the real PromptBuilder — just basic behavior)")
    for name, system_prompt in PERSONA_PROMPTS:
        response = client.chat.completions.create(
            model=SERVED_MODEL_NAME,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Startup pitch: {MOCK_PITCH}"},
            ],
            max_tokens=100,
            extra_body=DISABLE_THINKING_EXTRA_BODY,
        )
        content = (response.choices[0].message.content or "").strip()
        print(f"   [{name}] {content!r}")


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: python inference/smoke_test.py <base_url>", file=sys.stderr)
        return 2
    base_url = sys.argv[1].rstrip("/")

    client = OpenAI(base_url=f"{base_url}/v1", api_key="not-needed", default_headers=_auth_headers())

    results = {
        "models": test_models_endpoint(client),
        "chat_completion": test_chat_completion(client),
        "json_output": test_json_output(client),
    }
    test_persona_prompts(client)

    print("\n--- Summary ---")
    for name, passed in results.items():
        print(f"{name}: {'PASS' if passed else 'FAIL'}")

    required = ("models", "chat_completion")
    if all(results[name] for name in required):
        print("\nSmoke test passed (required checks).")
        if not results["json_output"]:
            print("Note: JSON output check did not pass — recorded for PHASE_12A_RESULTS.md.")
        return 0

    print("\nSmoke test FAILED.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
