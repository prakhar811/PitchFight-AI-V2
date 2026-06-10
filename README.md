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

PitchFight AI is a voice-and-text sparring arena for student founders. Practice a startup pitch, get grilled by realistic AI judges, negotiate a deal round, and walk away with a scorecard that shows what landed and what to fix next.

Built for the Hugging Face **Build Small Hackathon** (Backyard AI track) — deployed as a **Gradio Space** with a custom HTML/CSS/JS frontend.

## What It Does

| Mode | Description |
|------|-------------|
| **Pitch battle** | Multi-round Q&A against persona-driven AI judges (skeptical VC, technical judge, hackathon judge, and more) |
| **Voice pitch** | Record your opening pitch; Nemotron Omni transcribes and extracts structured startup fields |
| **Voice turns** | Answer judge questions by voice during the battle |
| **Deal battle** | Post-pitch negotiation phase with anchor points, concessions, and deal-specific scoring |
| **Scorecard** | Claim-based scoring across six dimensions plus coaching, improved answers, and prep points |
| **Retry weakest** | Re-answer your weakest question and compare against the original |

## Architecture

```
Browser (custom frontend)
    │  fetch → /api/*
    ▼
Gradio Server (app.py)
    │  model_router → nvidia_client
    ▼
NVIDIA Nemotron API  (integrate.api.nvidia.com)
```

- **Gradio Server** hosts the app on Hugging Face Spaces (`sdk: gradio`, `app_file: app.py`).
- **Custom frontend** lives in `frontend/` and talks only to `/api/*` routes — never to model providers directly.
- **All AI inference is API-backed.** Nemotron runs on NVIDIA's servers; this Space does not load local model weights or require a GPU.
- **Local CPU work** covers session management, rule-based scoring fallbacks, JSON parsing, and optional `ffmpeg` audio format conversion before API calls.
- **MongoDB** is optional (`MONGODB_ENABLED=false` by default). Sessions work in memory when persistence is off.

Gradio also registers internal runtime routes (`/gradio_api/*`, `/queue`, `/upload`, etc.) automatically. Those are framework plumbing for Spaces — the product API is under `/api/...`.

## Hugging Face Spaces Deployment

### 1. Create the Space

- **SDK:** Gradio
- **Hardware:** CPU basic is sufficient (inference is remote via NVIDIA API)
- **App file:** `app.py` (set automatically by the README frontmatter above)

Push this repository to the Space repo. Hugging Face reads the YAML frontmatter at the top of `README.md` to configure the Space.

### 2. Set Space Secrets

In **Settings → Repository secrets**, add:

| Secret | Required | Purpose |
|--------|----------|---------|
| `NVIDIA_API_KEY` | **Yes** | Nemotron judge, scoring, and voice calls |
| `NVIDIA_BASE_URL` | No | Defaults to `https://integrate.api.nvidia.com/v1` |
| `NVIDIA_OMNI_MODEL` | No | Defaults to `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning` |
| `DEFAULT_MODEL_MODE` | No | Defaults to `premium_nvidia` |
| `MAX_ROUNDS` | No | Battle round limit (default `6`) |
| `ENABLE_VOICE_MODE` | No | Set `false` to disable voice endpoints |
| `ENABLE_DEAL_BATTLE` | No | Set `false` to disable deal phase |
| `MONGODB_URI` | No | Only if `MONGODB_ENABLED=true` |
| `MONGODB_ENABLED` | No | Set `true` to persist sessions to MongoDB |

Never commit real API keys. The frontend never reads secrets — only the Python backend does.

### 3. System packages

`packages.txt` installs `ffmpeg` on the Space for browser audio (WebM) conversion before sending to Nemotron Omni. No extra Space configuration is needed beyond pushing that file.

### 4. Verify deployment

After the Space builds:

1. Open the Space URL — you should see the PitchFight battle arena.
2. Hit `/health` — expect `{"status":"ok","app":"PitchFight AI",...}`.
3. Hit `/api/model-health` — confirm the NVIDIA provider reports configured (keys are not exposed).
4. Run a full battle: load sample → start session → chat rounds → end battle → view scorecard.

If voice fails on certain browsers, ensure `ffmpeg` built successfully (check Space build logs) and `NVIDIA_API_KEY` is set.

## Run Locally

```bash
python -m venv venv

# Windows PowerShell
.\venv\Scripts\Activate.ps1

# macOS / Linux
# source venv/bin/activate

pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` and set at minimum:

```env
NVIDIA_API_KEY=your_key_here
```

Optional: install `ffmpeg` locally for reliable voice audio conversion (same role as on the Space).

```bash
python app.py
```

Open `http://127.0.0.1:7860` (or the port set via `PITCHFIGHT_PORT`).

Without `NVIDIA_API_KEY`, model calls fail and the app falls back to mock or local scoring where implemented.

## API Endpoints

Product routes (used by the frontend):

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/health` | App health check |
| `GET` | `/api/model-health` | Provider status (no keys exposed) |
| `POST` | `/api/load-sample` | Load a sample startup |
| `POST` | `/api/start-session` | Start a pitch battle session |
| `POST` | `/api/chat-round` | Send a user answer; receive judge reply |
| `POST` | `/api/end-battle` | End battle and generate scorecard |
| `POST` | `/api/retry-weakest-question/start` | Begin retry on weakest answer |
| `POST` | `/api/retry-weakest-question/submit` | Submit retry answer |
| `POST` | `/api/reset-session` | Clear session state |
| `POST` | `/api/voice-pitch` | Transcribe opening voice pitch |
| `POST` | `/api/voice-turn` | Transcribe a battle voice answer |
| `POST` | `/api/start-deal-phase` | Enter deal negotiation |
| `POST` | `/api/deal-round` | Send a deal negotiation turn |
| `POST` | `/api/end-deal` | End deal and generate deal scorecard |
| `POST` | `/api/deck-critique` | Deck critique placeholder |

## Project Structure

```
app.py                  Gradio Server entrypoint + REST routes
core/
  api_handlers.py       Shared handler logic (REST + Gradio)
  model_router.py       Routes tasks to NVIDIA Nemotron
  nvidia_client.py      Backend-only NVIDIA API client
  battle_flow.py        Pitch battle turn logic
  scoring_engine.py     Claim-based scorecard generation
  voice_handler.py      Voice transcription via Nemotron Omni
  deal_flow.py          Deal negotiation turns
  deal_scoring_engine.py Deal scorecard generation
  session_manager.py    In-memory session state
  session_repository.py Optional MongoDB persistence
frontend/
  index.html            Battle arena UI
  script.js             Session + battle client
  voice.js              Microphone capture + voice API calls
  styles.css            UI styling
config/
  personas.json         Judge personas
  attack_tags.json      Question attack patterns
  pitch_rubric.json     Scoring rubric
  sample_startups.json  Demo startups
packages.txt            HF Space system deps (ffmpeg)
requirements.txt        Python dependencies
.env.example            Local env template (copy to .env)
```

## Model & Hackathon Compliance

| Rule | How PitchFight complies |
|------|-------------------------|
| ≤32B parameters | Primary model: **NVIDIA Nemotron 3 Nano Omni 30B-A3B** |
| Gradio + HF Spaces | `gradio.Server` in `app.py`, Space metadata in this README |
| Demo-first | Full battle → scorecard flow runnable in the Space |
| No frontend API keys | All inference backend-only via `NVIDIA_API_KEY` in Secrets |

Inference runs on NVIDIA's hosted API — not on Space hardware — so a CPU Space is enough for production demos.

## Environment Variables

Copy `.env.example` to `.env` for local development. On Hugging Face, set the same keys as **Space Secrets**.

```env
APP_ENV=development
MAX_ROUNDS=6
DEFAULT_MODEL_MODE=premium_nvidia

NVIDIA_API_KEY=
NVIDIA_BASE_URL=https://integrate.api.nvidia.com/v1
NVIDIA_OMNI_MODEL=nvidia/nemotron-3-nano-omni-30b-a3b-reasoning

ENABLE_VOICE_MODE=true
ENABLE_DEAL_BATTLE=true
ENABLE_DECK_CRITIQUE=true

MONGODB_ENABLED=false
MONGODB_URI=
MONGODB_DB_NAME=pitchfight_db
```

## License

See repository license file if present. API usage is subject to NVIDIA's terms for the Nemotron integrate API.
