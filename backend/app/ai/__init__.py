"""AI orchestration package.

Prompts (prompt_builder.py), provider-neutral model abstraction
(model_client.py, model_router.py, providers/), and orchestration
(orchestrator.py) that coordinates them into typed PitchFight results.

V2 application code must not import from legacy/.
"""

from app.ai.orchestrator import AIOrchestrator, AIOutputParseError

__all__ = ["AIOrchestrator", "AIOutputParseError"]
