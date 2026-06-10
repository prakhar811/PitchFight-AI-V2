"""PitchFight AI — Gradio Server app with custom frontend."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import Body
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from gradio import Server

from core.api_handlers import (
    handle_chat_round,
    handle_deck_critique_placeholder,
    handle_end_battle,
    handle_end_deal,
    handle_deal_round,
    handle_load_sample,
    handle_reset_session,
    handle_retry_weakest_start,
    handle_retry_weakest_submit,
    handle_start_deal_phase,
    handle_start_session,
    handle_voice_pitch,
    handle_voice_turn,
)
from core import model_router

APP_VERSION = "0.1.0"
PITCHFIGHT_PORT = int(os.getenv("PITCHFIGHT_PORT", "7860"))
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


@app.post("/api/retry-weakest-question/start")
def api_retry_weakest_start(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    return handle_retry_weakest_start(payload)


@app.post("/api/retry-weakest-question/submit")
def api_retry_weakest_submit(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    return handle_retry_weakest_submit(payload)


@app.post("/api/reset-session")
def api_reset_session(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    return handle_reset_session(payload)


@app.post("/api/voice-pitch")
def api_voice_pitch(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    return handle_voice_pitch(payload)


@app.post("/api/voice-turn")
def api_voice_turn(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    return handle_voice_turn(payload)


@app.post("/api/start-deal-phase")
def api_start_deal_phase(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    return handle_start_deal_phase(payload)


@app.post("/api/deal-round")
def api_deal_round(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    return handle_deal_round(payload)


@app.post("/api/end-deal")
def api_end_deal(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    return handle_end_deal(payload)


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
    url = f"http://127.0.0.1:{PITCHFIGHT_PORT}"
    print(f"Starting PitchFight AI on {url}")
    try:
        app.launch(show_error=True, server_port=PITCHFIGHT_PORT)
    except OSError as exc:
        if "empty port" in str(exc).lower() or str(PITCHFIGHT_PORT) in str(exc):
            print(
                f"\nERROR: Port {PITCHFIGHT_PORT} is already in use by another process.\n"
                f"Stop the old server (Ctrl+C in its terminal), or free the port:\n"
                f"  netstat -ano | findstr \":{PITCHFIGHT_PORT}\"\n"
                f"  taskkill /PID <pid> /F\n"
                f"Then run: python app.py\n"
            )
        raise SystemExit(1) from exc
