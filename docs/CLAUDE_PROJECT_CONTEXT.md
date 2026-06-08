# PitchFight AI — Claude Project Context

> **Read this file before starting any implementation phase.**
> Generated after full repository inspection on 2026-06-08.

---

## 1. Project Summary

PitchFight AI is a voice-and-text AI sparring arena for student founders built for the Hugging Face **Build Small Hackathon** (Backyard AI track). The core use case: let founders get grilled by a realistic AI judge before they face real judges, mentors, investors, or sponsors. The AI does not give advice — it applies pressure, remembers prior answers, attacks vague claims, and scores the conversation.

The project runs on **Gradio Server** (not default Gradio UI), hosts a **custom HTML/CSS/JS frontend**, and exposes a clean **`/api/*` REST layer**. All AI model calls are strictly backend-only. The frontend never touches any model provider API.

---

## 2. Current Strategy

| Decision | Value |
|---|---|
| Hackathon track | Backyard AI |
| Off-the-Grid | **Not targeted** — intentional |
| Model cap | ≤32B parameters (all models comply) |
| Default model mode | `premium_nvidia` |
| Primary judge model | NVIDIA Nemotron 3 Nano Omni 30B-A3B |
| Frontend model calls | **Never** — frontend calls `/api/*` only |
| API keys | Backend `.env` locally; HF Space Secrets in deployment |
| Target prizes | Backyard AI, Best Demo, Best Agent, Off-Brand, NVIDIA Nemotron Quest, OpenBMB Awards, Sharing is Caring, Field Notes, Tiny Titan |
| Current build status | Phase 1 complete (mock APIs running) |

---

## 3. Current Model Stack

| Role | Model | Mode Key | Status |
|---|---|---|---|
| Primary judge (text, voice, scoring, rewrites) | `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning` | `premium_nvidia` | **Live (Phase 2)** — client tested |
| OpenBMB omni mode | `openbmb/MiniCPM-o-4_5` | `openbmb_omni` | Stub — Phase 9 |
| Tiny fallback / Tiny Mode | `openbmb/MiniCPM5-1B` | `tiny_minicpm` | Stub — Phase 9 |
| Pitch deck critique | `openbmb/MiniCPM-V-4.6` | `vision_deck` | Stub — Phase 10 |
| Audio transcription fallback | `faster-whisper` (tiny or base) | `whisper_fallback` | Stub — Phase 7 |

> **Reasoning model note:** `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning` uses tokens for an internal chain-of-thought before writing `message.content`. Confirmed token defaults: opponent=500, scorecard=2000, rewrite=800.

NVIDIA endpoint base URL: `https://integrate.api.nvidia.com/v1`

All model calls must go through `core/model_router.py` → individual client files. No model provider URL or key must ever appear in frontend code.

---

## 4. Backend Architecture

```
app.py                        ← Gradio Server entrypoint
  /health                     ← health check
  /                           ← serves frontend/index.html
  /api/load-sample            ← REST endpoint
  /api/start-session          ← REST endpoint
  /api/chat-round             ← REST endpoint
  /api/end-battle             ← REST endpoint
  /api/reset-session          ← REST endpoint
  /api/voice-pitch            ← placeholder (Phase 7)
  /api/start-deal-session     ← placeholder (Phase 8)
  /api/deck-critique          ← placeholder (Phase 10)
  @app.api wrappers           ← same handlers, Gradio client compat

core/api_handlers.py          ← shared handler logic (REST + Gradio route)
core/session_manager.py       ← in-memory session store (SESSIONS dict)
core/persona_builder.py       ← builds system prompt per persona + startup
core/attack_tags.py           ← attack tag taxonomy, round-based selection
core/scoring_engine.py        ← mock scorecard (Phase 1); real model call planned Phase 5
core/feedback_generator.py    ← mock rewrite logic (Phase 1); model call planned Phase 5
core/json_utils.py            ← JSON extraction + safe_json_parse + fallback_scorecard()
core/local_text_model.py      ← stub placeholder (Phase 1 only)
core/voice_transcriber.py     ← stub placeholder (Phase 7)
core/samples.py               ← get_sample_startup() (EventRadar AI)

config/personas.json          ← persona metadata (ids, names, focus areas)
config/attack_tags.json       ← attack tag reference (not yet used in code — code uses attack_tags.py)
config/pitch_rubric.json      ← 6 dimensions + weights
config/sample_startups.json   ← sample startup data

ADDED in Phase 2:
  model_router.py             ← routes tasks; premium_nvidia live; others stub
  nvidia_client.py            ← NVIDIA Nemotron client; live, tested
  minicpm_client.py           ← health_check stub (Phase 9)
  vision_client.py            ← health_check stub (Phase 10)
  transcription_client.py     ← health_check stub (Phase 7)
```

---

## 5. Frontend Architecture

File: `frontend/script.js`

The frontend uses **`fetch()`** calls exclusively to `/api/*` backend routes. No model provider URLs or API keys exist in any frontend file. This is verified and correct.

Key functions:
- `apiPost(path, body)` — all API calls go through this helper
- `loadSample()` → `POST /api/load-sample`
- `startSession()` → `POST /api/start-session` (sends `model_mode: "premium_nvidia"`)
- `sendMessage()` → `POST /api/chat-round`
- `endBattle()` → `POST /api/end-battle`
- `resetBattle()` → `POST /api/reset-session`
- `renderScorecard(data)` — renders overall score, bars, rewrites, questions

The `boot()` function calls `GET /health` on page load for backend availability check.

Static assets served at `/frontend/*` via Gradio StaticFiles mount.

---

## 6. Real Product API Endpoints

These are the only endpoints that matter for PitchFight as a product. Ignore Gradio-internal Swagger routes.

| Method | Path | Status | Phase |
|---|---|---|---|
| GET | `/health` | Live (mock-free) | Phase 1 |
| GET | `/` | Live | Phase 1 |
| POST | `/api/load-sample` | Live (real config data) | Phase 1 |
| POST | `/api/start-session` | Live (mock AI response) | Phase 1 |
| POST | `/api/chat-round` | Live (mock AI response) | Phase 1 |
| POST | `/api/end-battle` | Live (mock scorecard) | Phase 1 |
| POST | `/api/reset-session` | Live | Phase 1 |
| POST | `/api/voice-pitch` | Placeholder 501 | Phase 7 |
| POST | `/api/start-deal-session` | Placeholder 501 | Phase 8 |
| POST | `/api/deck-critique` | Placeholder 501 | Phase 10 |

Gradio internal routes (`/gradio_api/*`, `/queue/*`, `/upload`, `/static/*`) are framework runtime routes registered automatically. **Do not call or maintain them as product APIs.**

---

## 7. Existing File Structure

```
Pitchfight/
├── app.py                         ← Gradio Server + REST endpoints
├── .env.example                   ← env template (complete, correct)
├── .gitignore                     ← must include .env
├── README.md                      ← HF Spaces metadata + project overview
├── core/
│   ├── __init__.py
│   ├── api_handlers.py            ← shared handler logic
│   ├── attack_tags.py             ← tag taxonomy + selector
│   ├── feedback_generator.py      ← mock rewrite (Phase 1)
│   ├── json_utils.py              ← JSON parse + fallback
│   ├── local_text_model.py        ← stub (Phase 1)
│   ├── persona_builder.py         ← system prompt builder
│   ├── samples.py                 ← EventRadar AI sample
│   ├── scoring_engine.py          ← mock scorecard (Phase 1)
│   ├── session_manager.py         ← in-memory sessions
│   └── voice_transcriber.py       ← stub (Phase 1)
├── config/
│   ├── attack_tags.json           ← reference (code uses attack_tags.py)
│   ├── personas.json              ← persona metadata
│   ├── pitch_rubric.json          ← 6-dimension rubric weights
│   └── sample_startups.json       ← sample startup data
├── frontend/
│   ├── index.html
│   ├── script.js                  ← fetch-only, /api/* calls
│   ├── styles.css
│   └── assets/
└── docs/
    ├── BACKEND_API.md             ← endpoint reference
    ├── CLAUDE_PROJECT_CONTEXT.md  ← this file
    ├── DEMO_NOTES.md              ← demo flow + prize talking points
    ├── DOCUMENTATION.md           ← full project documentation
    ├── FIELD_NOTES.md             ← build log
    ├── MODELS_FINAL.md            ← model strategy
    ├── PHASE_WISE_PLAN.md         ← 14-phase build plan
    ├── PROMPTS.md                 ← prompt templates
    └── TASK_TRACKER.md            ← phase + task status
```

**Missing from `core/` (needed Phase 2+):**
- `model_router.py`
- `nvidia_client.py`
- `minicpm_client.py`
- `vision_client.py`
- `transcription_client.py`

---

## 8. Current Implementation Status

### Working (Phase 1)
- Gradio Server app starts and serves custom frontend
- GET `/health` returns version + status
- GET `/` serves `frontend/index.html`
- POST `/api/load-sample` returns EventRadar AI startup dict from `samples.py`
- POST `/api/start-session` creates in-memory session, returns mock opening question keyed by persona
- POST `/api/chat-round` increments round, rotates attack tags, returns hardcoded mock follow-up per persona
- POST `/api/end-battle` returns mock scorecard with static scores, real user quotes from session history
- POST `/api/reset-session` deletes session from SESSIONS dict
- Frontend flow: landing → setup (load sample or enter custom) → battle arena → scorecard
- Error banners and loading overlay functional in frontend
- Health check on boot functional

### Mock / Placeholder
- All AI opponent messages in `api_handlers.py` — hardcoded string lists per persona
- All scorecard scores — hardcoded integers (overall: 68, clarity: 64, etc.)
- `feedback_generator.py` — template string rewrites, no model call
- `local_text_model.py` — stub, returns placeholder string
- `voice_transcriber.py` — stub, returns not_loaded status
- `/api/voice-pitch` — returns `{"status": "not_implemented"}`
- `/api/start-deal-session` — returns `{"status": "not_implemented"}`
- `/api/deck-critique` — returns `{"status": "not_implemented"}`

### Missing (Phase 2+)
- `core/model_router.py` — central routing logic
- `core/nvidia_client.py` — NVIDIA Nemotron API calls
- `core/minicpm_client.py` — MiniCPM-o and MiniCPM5-1B API/local calls
- `core/vision_client.py` — MiniCPM-V 4.6 image/vision calls
- `core/transcription_client.py` — faster-whisper audio fallback
- Real AI response in `handle_chat_round` (replace hardcoded followups)
- Real scoring in `handle_end_battle` (replace `mock_scorecard`)
- Real rewrite in `feedback_generator` (replace template strings)
- Voice audio handling in `/api/voice-pitch`
- Deal battle logic in `/api/start-deal-session`
- Image upload and critique in `/api/deck-critique`

---

## 9. Mock vs Real Components

| Component | Mock or Real | Notes |
|---|---|---|
| Session management | **Real** | In-memory, uuid-based, correct |
| Persona system prompt builder | **Real** | `persona_builder.py` builds full system prompt |
| Attack tag rotator | **Real** | `attack_tags.py` rotates by round index |
| Sample startup data | **Real** | EventRadar AI data loaded from `samples.py` |
| Config JSON files | **Real** | personas, rubric, tags all present |
| JSON utils | **Real** | Extraction + safe parse + fallback all coded |
| `json_utils.fallback_scorecard()` | **Real** | Safe fallback ready |
| Opening AI question | **Mock** | Hardcoded per persona in `api_handlers.py` |
| Follow-up AI questions | **Mock** | Hardcoded list per persona, index by round |
| Scorecard scores | **Mock** | All integers hardcoded in `scoring_engine.mock_scorecard()` |
| Answer rewrite | **Mock** | Template string in `feedback_generator.py` |
| Pitch rewrite | **Mock** | Template string in `feedback_generator.py` |
| NVIDIA API client | **Real** | `core/nvidia_client.py` — live, tested Phase 2 |
| Model router | **Real** | `core/model_router.py` — premium_nvidia live; others stub |
| MiniCPM clients | **Stub** | `core/minicpm_client.py` — health_check only, Phase 9 |
| Vision client | **Stub** | `core/vision_client.py` — health_check only, Phase 10 |
| Whisper transcription | **Stub** | `core/transcription_client.py` — health_check only, Phase 7 |

---

## 10. Next Recommended Phase

**Phase 3: Wire model_router into battle flow**

Phase 2 is complete. NVIDIA Nemotron is live and tested. Next step is connecting `model_router.generate_opponent_response()` to the actual battle endpoints.

Goals:
1. In `core/api_handlers.py`: import `model_router` and `persona_builder`
2. In `handle_start_session`: build system prompt, call `model_router.generate_opponent_response()`, fall back to mock if `ok=False`
3. In `handle_chat_round`: build full message history, call `model_router.generate_opponent_response()`, fall back to mock if `ok=False`
4. End-to-end test: full battle with live Nemotron responses
5. Update docs

Do **not** connect voice, deal battle, scoring, or deck critique in Phase 3.

---

## 11. Rules for Future Claude Code Work

1. **Always read docs before implementing a phase.** Read `PHASE_WISE_PLAN.md`, this file, and `BACKEND_API.md` before touching code.
2. **Never expose API keys in frontend.** No env reads, no hardcoded keys, no fetch calls to model provider URLs from frontend JS.
3. **Never commit `.env`.** `.gitignore` must include `.env`. Only `.env.example` (empty values) goes to repo.
4. **Keep frontend calls limited to `/api/*`.** The only external call from frontend is to `/health`. All AI calls go through backend `/api/*` routes.
5. **Keep model calls backend-only.** All `openai.Client`, `requests.post`, or SDK calls to NVIDIA/OpenBMB must be in `core/` files only.
6. **After each phase, update `docs/PHASE_WISE_PLAN.md`** with a status line marking the phase complete.
7. **After each phase, update `docs/FIELD_NOTES.md`** with what changed, what worked, and what was learned.
8. **After each phase, update `docs/BACKEND_API.md`** if any endpoint changed signature, status, or behavior.
9. **After each phase, update `docs/MODELS_FINAL.md`** if the model strategy or routing changed.
10. **Do not silently change architecture.** Any change to the API contract, session model, or model routing must be documented before implementation.
11. **Preserve the working mock flow while replacing parts incrementally.** Never delete a working mock endpoint before its replacement is tested. The mock is the safety net.
12. **Use `os.getenv()` only** for API key reads. Never use hardcoded fallback values for secrets. If the key is missing, log a warning and return a clear error — do not silently continue.
13. **Do not add features outside the current phase scope.** One phase at a time. Phase 2 is model router only. Phase 3 is NVIDIA text only. Do not reach forward.
14. **Test each model client independently** before wiring it into the session/handler flow.
15. **`core/json_utils.py` already has `safe_json_parse` and `fallback_scorecard`.** Use them — do not rewrite JSON parsing logic elsewhere.

---

## 12. Documentation Update Rules

After every phase:

| Doc | What to update |
|---|---|
| `docs/PHASE_WISE_PLAN.md` | Mark phase status as Complete. Add date. |
| `docs/FIELD_NOTES.md` | Add a build log entry: what changed, what worked, what surprised you. |
| `docs/BACKEND_API.md` | Update endpoint status column if a placeholder became real. |
| `docs/MODELS_FINAL.md` | Update model-to-file mapping if new client files were created or routes changed. |
| `docs/TASK_TRACKER.md` | Move completed tasks to done; update current phase and next tasks. |
| `docs/CLAUDE_PROJECT_CONTEXT.md` | Update "Current Implementation Status" and "Mock vs Real Components" sections. |

Do **not** update docs prophylactically for future phases. Only document what is actually implemented.
