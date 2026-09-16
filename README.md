# PitchFight AI V2

Your first tough pitch should not be in front of a real judge.

PitchFight AI is an AI founder pressure arena: student builders practice startup pitches, survive judge-style questions, enter a deal round, and leave with a scorecard that shows what to fix.

This repository is the **V2 rebuild**. This phase is structure and scaffolding only. Product features, databases, authentication, and inference are not implemented yet.

The original V1 project remains in a separate repository. A copy of that implementation lives under `legacy/` as migration reference. **V2 code must not import from `legacy/`.**

## Current status

The API boots and serves a health check:

```bash
uvicorn app.main:app --app-dir backend
```

```text
GET /api/v1/health
```

```json
{
  "status": "ok",
  "service": "pitchfight-api"
}
```

Python version: **3.11** (see `.python-version`).

## Architecture

V2 is a **modular monolith**:

```text
Route → Service → Repository / AI Orchestrator → Database / Model Server
```

Those layers are scaffolded as packages. Business logic is not implemented in this phase.

## Repository layout

```text
.
├── backend/          FastAPI application (V2)
├── frontend/         Existing V1 custom UI (unchanged in this phase)
├── inference/        Future Modal / vLLM model serving
├── infra/            Future Docker Compose (PostgreSQL, MongoDB, Redis)
├── docs/             Architecture notes and V1 field notes
├── legacy/           V1 implementation, migration reference only
└── scripts/
```

## Local setup (scaffold)

```bash
python -m venv .venv
# Windows
.\.venv\Scripts\Activate.ps1
pip install -r backend/requirements-dev.txt
copy .env.example .env
```

Run the API:

```bash
uvicorn app.main:app --app-dir backend --reload
```

Run the health test:

```bash
cd backend
pytest tests/test_health.py
```

## Frontend

The current frontend is the V1 HTML/CSS/JS UI. It is intentionally unchanged. React migration is scheduled later in the V2 rebuild.

## What is not in this phase

- PostgreSQL / MongoDB / Redis connections
- JWT authentication
- Simulation and scoring logic
- AI orchestration, prompts, and model routing
- Modal, vLLM, and model downloading
- Docker Compose
- Frontend React migration

## Next planned phase

Local Infrastructure — PostgreSQL + MongoDB + Redis via Docker Compose
