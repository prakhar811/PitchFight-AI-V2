"""PitchFight AI — Gradio Server app with custom frontend."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import Body
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from gradio import Server

from core.api_handlers import (
    handle_chat_round,
    handle_deck_critique_placeholder,
    handle_deal_session_placeholder,
    handle_end_battle,
    handle_load_sample,
    handle_reset_session,
    handle_start_session,
    handle_voice_pitch_placeholder,
)
from core import model_router

APP_VERSION = "0.1.0"
FRONTEND_DIR = Path(__file__).parent / "frontend"

app = Server()


# ---------------------------------------------------------------------------
# PitchFight REST API (product endpoints — use these from the custom frontend)
# ---------------------------------------------------------------------------


@app.get("/health")
async def health() -> dict[str, str]:
    """Health check for app status."""
    return {"status": "ok", "app": "PitchFight AI", "version": APP_VERSION}


@app.get("/api/model-health")
async def api_model_health() -> dict[str, Any]:
    """Model provider configuration status. Keys are never exposed."""
    return model_router.get_model_health()


@app.post("/api/load-sample")
def api_load_sample() -> dict[str, Any]:
    return handle_load_sample()


@app.post("/api/start-session")
def api_start_session(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    return handle_start_session(payload)


@app.post("/api/chat-round")
def api_chat_round(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    return handle_chat_round(payload)


@app.post("/api/end-battle")
def api_end_battle(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    return handle_end_battle(payload)


@app.post("/api/reset-session")
def api_reset_session(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    return handle_reset_session(payload)


@app.post("/api/voice-pitch")
def api_voice_pitch(payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, str]:
    return handle_voice_pitch_placeholder(payload)


@app.post("/api/start-deal-session")
def api_start_deal_session(payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, str]:
    return handle_deal_session_placeholder(payload)


@app.post("/api/deck-critique")
def api_deck_critique(payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, str]:
    return handle_deck_critique_placeholder(payload)


# ---------------------------------------------------------------------------
# Gradio @app.api compatibility (same handlers — for gradio_client / queue)
# ---------------------------------------------------------------------------


@app.api(name="load_sample")
def gradio_load_sample() -> dict[str, Any]:
    return handle_load_sample()


@app.api(name="start_session")
def gradio_start_session(payload: dict[str, Any]) -> dict[str, Any]:
    return handle_start_session(payload)


@app.api(name="chat_round")
def gradio_chat_round(payload: dict[str, Any]) -> dict[str, Any]:
    return handle_chat_round(payload)


@app.api(name="end_battle")
def gradio_end_battle(payload: dict[str, Any]) -> dict[str, Any]:
    return handle_end_battle(payload)


@app.api(name="reset_session")
def gradio_reset_session(payload: dict[str, Any]) -> dict[str, Any]:
    return handle_reset_session(payload)


# ---------------------------------------------------------------------------
# Frontend
# ---------------------------------------------------------------------------


@app.get("/", response_class=HTMLResponse)
async def homepage() -> HTMLResponse:
    """Serve the custom PitchFight frontend."""
    index_path = FRONTEND_DIR / "index.html"
    return HTMLResponse(index_path.read_text(encoding="utf-8"))


app.mount("/frontend", StaticFiles(directory=str(FRONTEND_DIR)), name="frontend")


if __name__ == "__main__":
    app.launch(show_error=True)
