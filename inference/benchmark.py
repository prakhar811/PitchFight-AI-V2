"""Standalone WARM-latency benchmark for the deployed PitchFight Nemotron
vLLM server. No PitchFight backend, no databases — just HTTP requests.

Runs one warmup request (excluded from stats — this is where any residual
JIT/compile cost would show up), then N timed requests with a fixed prompt.

Usage:
    python inference/benchmark.py <base_url> [num_requests]

    e.g. python inference/benchmark.py https://your-workspace--pitchfight-nemotron-inference-server.modal.run 5

Authentication: see inference/README.md — export MODAL_KEY and
MODAL_SECRET (a Modal Proxy Auth Token). Never print these values.

IMPORTANT: this measures WARM request latency only — the server must
already be running. Cold-start (container boot + model load, potentially
several minutes on first request) is a separate, one-time cost and is
NOT part of these numbers. See inference/README.md.
"""

import os
import sys
import time
from typing import Any

from openai import OpenAI

from config import SERVED_MODEL_NAME

SYSTEM_PROMPT = "You are a concise startup pitch evaluator."
USER_PROMPT = (
    "A startup says it uses AI to help restaurants predict food waste. "
    "Ask one concise skeptical question."
)
MAX_TOKENS = 100

# Nemotron 3.5 has "thinking" (reasoning) enabled by default, which consumes
# our small max_tokens budget on the reasoning channel before any final
# content is produced — confirmed manually. Disable it via vLLM's
# chat_template_kwargs passthrough for every request (warmup + measured).
DISABLE_THINKING_EXTRA_BODY = {"chat_template_kwargs": {"enable_thinking": False}}


def _auth_headers() -> dict[str, str]:
    key = os.environ.get("MODAL_KEY")
    secret = os.environ.get("MODAL_SECRET")
    if not key or not secret:
        print("WARNING: MODAL_KEY/MODAL_SECRET not set — requests may fail with 401.", file=sys.stderr)
        return {}
    return {"Modal-Key": key, "Modal-Secret": secret}


def _one_request(client: OpenAI) -> dict[str, Any]:
    start = time.perf_counter()
    response = client.chat.completions.create(
        model=SERVED_MODEL_NAME,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": USER_PROMPT},
        ],
        max_tokens=MAX_TOKENS,
        extra_body=DISABLE_THINKING_EXTRA_BODY,
    )
    latency_s = time.perf_counter() - start

    content = response.choices[0].message.content or ""
    usage = response.usage
    return {
        "latency_s": latency_s,
        "output_len_chars": len(content),
        "input_tokens": getattr(usage, "prompt_tokens", None) if usage else None,
        "output_tokens": getattr(usage, "completion_tokens", None) if usage else None,
        "finish_reason": response.choices[0].finish_reason,
    }


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: python inference/benchmark.py <base_url> [num_requests]", file=sys.stderr)
        return 2
    base_url = sys.argv[1].rstrip("/")
    num_requests = int(sys.argv[2]) if len(sys.argv) > 2 else 5

    client = OpenAI(base_url=f"{base_url}/v1", api_key="not-needed", default_headers=_auth_headers())

    print("Warmup request (excluded from stats)...")
    warmup = _one_request(client)
    print(f"  warmup latency: {warmup['latency_s']:.2f}s\n")

    results: list[dict[str, Any]] = []
    for i in range(1, num_requests + 1):
        try:
            result = _one_request(client)
        except Exception as exc:  # report every failure, keep the run going
            print(f"request {i}: ERROR {exc!r}")
            continue
        results.append(result)
        print(
            f"request {i}: status=OK latency={result['latency_s']:.2f}s "
            f"output_len_chars={result['output_len_chars']} "
            f"input_tokens={result['input_tokens']} output_tokens={result['output_tokens']} "
            f"finish_reason={result['finish_reason']}"
        )

    if not results:
        print("\nNo successful requests — nothing to summarize.")
        return 1

    latencies = [r["latency_s"] for r in results]
    print("\n--- Summary (warm latency; excludes cold start & warmup) ---")
    print(f"requests: {len(results)}/{num_requests} succeeded")
    print(f"avg latency: {sum(latencies) / len(latencies):.2f}s")
    print(f"min latency: {min(latencies):.2f}s")
    print(f"max latency: {max(latencies):.2f}s")

    output_tokens = [r["output_tokens"] for r in results if r["output_tokens"] is not None]
    if output_tokens:
        total_output_tokens = sum(output_tokens)
        total_latency = sum(r["latency_s"] for r in results if r["output_tokens"] is not None)
        if total_latency > 0:
            print(f"approx output tokens/sec (aggregate): {total_output_tokens / total_latency:.1f}")
    else:
        print("output token counts were not returned by the server — skipping tokens/sec calculation")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
