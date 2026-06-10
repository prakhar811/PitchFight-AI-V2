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

Built for the Hugging Face **Build Small Hackathon** (Backyard AI track). Runs as a **Gradio Space** with a custom frontend.

## Features

- Multi-round pitch battles against different judge personas
- Voice pitch and voice answers (Nemotron Omni)
- Deal negotiation round after the pitch
- Scorecard with coaching and retry on your weakest answer

## How It Works

```
Browser (custom frontend)
    │  fetch → /api/*
    ▼
Gradio Server (app.py)
    │  model_router → nvidia_client
    ▼
NVIDIA Nemotron API  (integrate.api.nvidia.com)
```

## Deploy on Hugging Face

1. Push this repo to a Gradio Space (the YAML frontmatter above configures it automatically).
2. Add **`NVIDIA_API_KEY`** under **Settings → Repository secrets**.
3. Build should pick up `packages.txt` (`ffmpeg`) for voice support.

Optional secrets: `MAX_ROUNDS`, `ENABLE_VOICE_MODE`, `ENABLE_DEAL_BATTLE`, `MONGODB_URI` (only if you enable MongoDB).

Never put API keys in the frontend or in git.

## Run Locally

```bash
python -m venv venv
.\venv\Scripts\Activate.ps1          # Windows
pip install -r requirements.txt
cp .env.example .env                 # add NVIDIA_API_KEY
python app.py
```

Open `http://127.0.0.1:7860`. Install `ffmpeg` locally if you use voice mode.

## Stack

| Piece | Detail |
|-------|--------|
| Host | Gradio Server (`app.py`) on Hugging Face Spaces |
| Model | NVIDIA Nemotron 3 Nano Omni 30B-A3B (backend API) |
| UI | Custom HTML/CSS/JS — not default Gradio widgets |
