"""Model provider adapters — each wraps one provider behind ModelClient.

fake.py — deterministic in-process client for tests/offline development.

Real providers (NVIDIA/Nemotron via vLLM/Modal, etc.) are Phase 12 work.
Nothing here makes a network call.
"""

from app.ai.providers.fake import FakeModelClient

__all__ = ["FakeModelClient"]
