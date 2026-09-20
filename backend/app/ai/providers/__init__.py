"""Model provider adapters — each wraps one provider behind ModelClient.

fake.py — deterministic in-process client for tests/offline development.
vllm.py — real Modal-hosted vLLM/Nemotron endpoint (Phase 12A/12B).
"""

from app.ai.providers.fake import FakeModelClient
from app.ai.providers.vllm import VLLMModelClient

__all__ = ["FakeModelClient", "VLLMModelClient"]
