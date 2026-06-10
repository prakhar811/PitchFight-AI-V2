---
title: PitchFight AI
emoji: ⚔️
colorFrom: red
colorTo: yellow
sdk: gradio
app_file: app.py
pinned: true
---

# PitchFight AI

**Your first tough pitch should not be in front of a real judge.**

A voice-and-text AI sparring arena for student founders — built for the Hugging Face **Build Small Hackathon** (Backyard AI track).

## One-Line Pitch

PitchFight AI is a voice-and-text AI sparring arena where student founders practice tough startup pitches, get grilled by realistic AI judges under 32B parameters, and receive a scorecard that shows exactly how to answer better.

## Strategic Direction

This build prioritizes **demo strength**, **model quality**, and **sponsor-model alignment** — not the Off-the-Grid badge.

| Priority | Detail |
|---|---|
| **Hackathon rules** | ≤32B models, Gradio, HF Spaces, demo-first |
| **Primary premium model** | NVIDIA Nemotron 3 Nano Omni 30B-A3B (backend-only API) |
| **Frontend API** | `fetch()` → `/api/...` only — never model provider APIs |
| **OpenBMB modes** | MiniCPM-o, MiniCPM5-1B, MiniCPM-V 4.6 |
| **Voice fallback** | faster-whisper local transcription |
| **UI** | Custom HTML/CSS/JS via Gradio Server (not default Gradio) |
| **Secrets** | API keys in HF Space Secrets / backend `.env` only |

> **Off-the-Grid is not targeted** in this build. Sponsor APIs are used intentionally for the highest-quality demo.

## Target Badges / Prizes

Backyard AI · Best Demo · Best Agent · Off-Brand · NVIDIA Nemotron Quest · OpenBMB Awards · Sharing is Caring · Field Notes · Tiny Titan (Tiny Mode)

## Current Status

**Phase 1 complete** — Gradio Server skeleton + custom frontend + mock battle/scorecard APIs.

See [`docs/PHASE_WISE_PLAN.md`](docs/PHASE_WISE_PLAN.md) for the full 14-phase roadmap.

## Run Locally

```bash
python -m venv venv
# Windows: .\venv\Scripts\Activate.ps1
pip install -r requirements.txt
cp .env.example .env   # add API keys for Phase 2+
python app.py
```

Open the URL printed in your terminal (typically `http://127.0.0.1:7860`).

Phase 1 runs with **mock responses** — no API keys required. Real model routing begins in **Phase 2**.

## Backend API

PitchFight AI exposes **clean custom project APIs under `/api/...`**. Gradio internal routes (`/gradio_api/*`, `/queue`, `/upload`, etc.) may appear in OpenAPI/Swagger — those are **framework runtime routes**, not product endpoints.

See **[`docs/BACKEND_API.md`](docs/BACKEND_API.md)** for the full API reference.

## Project Structure

- `app.py` — Gradio Server entrypoint + `/api/*` REST routes
- `core/api_handlers.py` — shared handler logic (REST + Gradio)
- `core/` — session, persona, scoring, model clients (Phases 2+)
- `config/` — personas, attack tags, rubric, samples
- `frontend/` — custom battle arena UI (`fetch` → `/api/*`)
- `docs/` — phase plan, models, prompts, demo notes, backend API

## Documentation

- [Phase-Wise Plan](docs/PHASE_WISE_PLAN.md)
- [Model Strategy](docs/MODELS_FINAL.md)
- [Nemotron Omni Audio Architecture](docs/NEMOTRON_OMNI_AUDIO.md)
- [Full Documentation](docs/DOCUMENTATION.md)
- [Demo Notes](docs/DEMO_NOTES.md)
