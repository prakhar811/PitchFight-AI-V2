# PitchFight AI — Backend API Reference

## 1. Important Note About Gradio Internal Endpoints

When you run `python app.py` and open FastAPI/Swagger (`/docs`), you will see **many routes** that are **not** PitchFight AI product APIs, for example:

- `/gradio_api/*` — config, queue, upload, streaming
- `/queue/*` — Gradio job queue
- `/upload` — Gradio file upload
- `/static/*`, `/assets/*`, `/theme.css` — Gradio UI assets
- Login, monitoring, and other framework runtime routes

These are **automatically registered by Gradio** and are required for Gradio Server to work on Hugging Face Spaces. **Do not delete them.**

**PitchFight AI’s real backend endpoints** are namespaced under **`/api/...`** plus **`/health`** and **`/`**.

> Judge this project’s API design by `/api/*` and this document — not by the long Gradio-generated OpenAPI list.

---

## 2. Backend Design Principles

| Principle | Detail |
|---|---|
| **Frontend never calls model providers** | No NVIDIA/OpenBMB keys in browser JS; only `/api/*` + `/health` |
| **Backend owns model routing** | `core/model_router.py` (Phase 2+) — default `premium_nvidia` (Nemotron Omni 30B-A3B) |
| **Backend owns session state** | `core/session_manager.py` |
| **Backend owns scoring** | `core/scoring_engine.py` |
| **Frontend sends actions, renders results** | Custom HTML/CSS/JS + `fetch()` |
| **Secrets in env only** | `.env` locally, HF Space Secrets in deployment — never in frontend or repo |

> **Strategy:** High-demo sponsor-model build. Off-the-Grid is not targeted. faster-whisper is transcription fallback only; OpenBMB MiniCPM modes are secondary/fallback paths.

Shared logic lives in **`core/api_handlers.py`**. Both REST routes (`/api/...`) and Gradio `@app.api` wrappers call the same handler functions.

---

## 3. Clean Project Endpoints

| Method | Path | Status | Purpose |
|---|---|---|---|
| `GET` | `/health` | **Implemented** | App health check |
| `GET` | `/` | **Implemented** | Serve custom frontend |
| `GET` | `/api/model-health` | **Implemented** (Phase 2) | Model provider config status (no keys) |
| `POST` | `/api/load-sample` | **Implemented** | Load EventRadar AI demo startup |
| `POST` | `/api/start-session` | **Implemented** | Start Pitch Battle session |
| `POST` | `/api/chat-round` | **Implemented** | Send user answer, get AI pushback |
| `POST` | `/api/end-battle` | **Implemented** | Generate scorecard |
| `POST` | `/api/reset-session` | **Implemented** | Delete session |
| `POST` | `/api/voice-pitch` | **Placeholder** | Voice pitch (reserved) |
| `POST` | `/api/start-deal-session` | **Placeholder** | Deal Battle (reserved) |
| `POST` | `/api/deck-critique` | **Placeholder** | Pitch deck critique (reserved) |

### Gradio compatibility wrappers (same handlers)

| Gradio `@app.api` name | Handler |
|---|---|
| `load_sample` | `handle_load_sample()` |
| `start_session` | `handle_start_session()` |
| `chat_round` | `handle_chat_round()` |
| `end_battle` | `handle_end_battle()` |
| `reset_session` | `handle_reset_session()` |

---

## 4. Endpoint Details

### `GET /health`

**Purpose:** Verify the server is running.

**Response:**

```json
{
  "status": "ok",
  "app": "PitchFight AI",
  "version": "0.1.0"
}
```

---

### `GET /api/model-health`

**Purpose:** Return model provider configuration status. API keys are **never** included in the response.

**Response:**

```json
{
  "default_mode": "premium_nvidia",
  "supported_modes": ["openbmb_omni", "premium_nvidia", "tiny_minicpm", "vision_deck", "whisper_fallback"],
  "providers": {
    "nvidia": {
      "provider": "nvidia",
      "configured": true,
      "base_url": "https://integrate.api.nvidia.com/v1",
      "model": "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning",
      "api_key_present": true,
      "message": "NVIDIA client ready"
    },
    "minicpm": { "status": "not_configured", "provider": "openbmb", "message": "MiniCPM integration planned for Phase 9" },
    "vision":  { "status": "not_configured", "provider": "openbmb", "message": "Vision/deck critique planned for Phase 10" },
    "transcription": { "status": "not_configured", "provider": "local", "message": "faster-whisper fallback planned for Phase 7" }
  }
}
```

---

### `GET /`

**Purpose:** Serve `frontend/index.html` (custom battle arena UI).

Static assets: `/frontend/styles.css`, `/frontend/script.js`, `/frontend/assets/*`

---

### `POST /api/load-sample`

**Purpose:** Load the EventRadar AI sample startup into the form.

**Request body:** none

**Response:**

```json
{
  "startup": {
    "name": "EventRadar AI",
    "problem": "...",
    "target_users": "...",
    "solution": "...",
    "why_ai": "...",
    "competitors": "...",
    "traction": "...",
    "ask": "..."
  }
}
```

---

### `POST /api/start-session`

**Purpose:** Start a new Pitch Battle session.

**Request body:**

```json
{
  "mode": "pitch_battle",
  "persona": "hackathon_judge",
  "difficulty": "high",
  "input_mode": "text",
  "model_mode": "premium_nvidia",
  "startup": {
    "name": "EventRadar AI",
    "problem": "...",
    "target_users": "...",
    "solution": "...",
    "why_ai": "...",
    "competitors": "...",
    "traction": "...",
    "ask": "..."
  }
}
```

**Response:**

```json
{
  "session_id": "uuid",
  "round": 1,
  "pressure_level": "Medium",
  "attack_tag": "User Pain",
  "ai_message": "Students already lurk in WhatsApp groups..."
}
```

---

### `POST /api/chat-round`

**Purpose:** Submit one founder answer and receive the next AI challenge.

**Request body:**

```json
{
  "session_id": "uuid",
  "user_message": "We use AI to rank events for students."
}
```

**Response:**

```json
{
  "session_id": "uuid",
  "round": 2,
  "pressure_level": "Medium",
  "attack_tag": "Demo Clarity",
  "ai_message": "If I only saw a 30-second demo..."
}
```

---

### `POST /api/end-battle`

**Purpose:** End the battle and return a scorecard.

**Request body:**

```json
{
  "session_id": "uuid"
}
```

**Response:**

```json
{
  "overall": 68,
  "scores": {
    "clarity": {
      "score": 64,
      "reason": "...",
      "quote": "..."
    }
  },
  "best_answer": "...",
  "weakest_answer": "...",
  "improved_answer": "...",
  "improved_pitch": "...",
  "top_3_questions": ["...", "...", "..."]
}
```

---

### `POST /api/reset-session`

**Purpose:** Delete a session.

**Request body:**

```json
{
  "session_id": "uuid"
}
```

**Response:**

```json
{
  "status": "reset"
}
```

---

### `POST /api/voice-pitch` (placeholder)

**Planned flow (Phase 7):** audio → Nemotron Omni (primary) → pitch context + opening question. Fallback: faster-whisper transcription → Nemotron or MiniCPM5-1B text path.

**Response (current):**

```json
{
  "status": "not_implemented",
  "message": "Voice Mode endpoint is reserved. Primary path: Nemotron Omni voice; fallback: faster-whisper transcription."
}
```

---

### `POST /api/start-deal-session` (placeholder)

**Response:**

```json
{
  "status": "not_implemented",
  "message": "Deal Battle endpoint is reserved and will be connected in a later phase."
}
```

---

### `POST /api/deck-critique` (placeholder)

**Response:**

```json
{
  "status": "not_implemented",
  "message": "Deck critique endpoint is reserved and will be connected after MiniCPM-V vision integration."
}
```

---

## 5. Endpoint Flow Diagrams

### Pitch Battle flow

```mermaid
flowchart TD
    A[Frontend UI] --> B[/api/start-session]
    B --> C[Session Manager]
    C --> D[Persona Builder]
    D --> E[Attack Tag Selector]
    E --> F[Model Router]
    F --> G[AI Response]
    G --> A
```

### Scorecard flow

```mermaid
flowchart TD
    A[Frontend UI] --> B[/api/end-battle]
    B --> C[Session Manager]
    C --> D[Scoring Engine]
    D --> E[Model Router]
    E --> F[JSON Parser]
    F --> G[Scorecard Response]
    G --> A
```

---

## 6. Why Swagger Shows Many Routes

Gradio Server is built on FastAPI. When the app launches, Gradio **automatically registers** internal endpoints for:

- App configuration (`/gradio_api/config`, `/gradio_api/info`)
- Request queueing (`/queue/join`, `/queue/data`)
- File uploads (`/upload`)
- Static assets and themes
- Streaming, login checks, and monitoring

These are **framework runtime routes**, not hand-written PitchFight product APIs. They exist so Gradio can host the app on Hugging Face Spaces with queuing, MCP, and ZeroGPU support.

**You do not call or maintain those routes manually.** The custom frontend uses only `/api/*` and `/health`.

---

## 7. Final API Contract — Quick Examples

### Load sample

```bash
curl -X POST http://127.0.0.1:7860/api/load-sample
```

### Start session

```bash
curl -X POST http://127.0.0.1:7860/api/start-session \
  -H "Content-Type: application/json" \
  -d '{"mode":"pitch_battle","persona":"hackathon_judge","difficulty":"high","input_mode":"text","model_mode":"premium_nvidia","startup":{"name":"Test","problem":"p","target_users":"u","solution":"s","why_ai":"a","competitors":"c","traction":"t","ask":"a"}}'
```

### Chat round

```bash
curl -X POST http://127.0.0.1:7860/api/chat-round \
  -H "Content-Type: application/json" \
  -d '{"session_id":"<uuid>","user_message":"We use AI for ranking."}'
```

### End battle

```bash
curl -X POST http://127.0.0.1:7860/api/end-battle \
  -H "Content-Type: application/json" \
  -d '{"session_id":"<uuid>"}'
```

### Reset session

```bash
curl -X POST http://127.0.0.1:7860/api/reset-session \
  -H "Content-Type: application/json" \
  -d '{"session_id":"<uuid>"}'
```
