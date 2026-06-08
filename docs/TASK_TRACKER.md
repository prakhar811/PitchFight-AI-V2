# PitchFight AI — Task Tracker

## Current Phase

Phase 2 complete: Model Router + Secrets Setup (2026-06-08)

## Next Phase

Phase 3: Wire model_router into battle flow (handle_start_session + handle_chat_round)

---

## Phase Status Table

| Phase | Name | Status | Notes |
|---|---|---|---|
| 0 | Strategy Reset + Documentation Alignment | Complete | Off-the-Grid removed; sponsor-model strategy locked |
| 1 | Project Skeleton Verification | Complete | Mock app runs; custom frontend live; all /api/* endpoints return responses |
| 2 | Model Router + Secrets Setup | **Complete** (2026-06-08) | nvidia_client, model_router, stub clients created; NVIDIA tested live |
| 3 | NVIDIA Nemotron Omni Integration | Pending | Depends on Phase 2 |
| 4 | Pitch Battle Engine | Pending | Replace mock followups with real Nemotron responses |
| 5 | Scorecard + Feedback Engine | Pending | Real scoring via Nemotron; json_utils already ready |
| 6 | Custom Frontend Integration | Pending | Model mode badge; error/loading polish |
| 7 | Voice Pitch Mode | Pending | Browser audio → Nemotron Omni; fallback to whisper |
| 8 | Deal Battle Mode | Pending | Negotiation scenarios + deal personas |
| 9 | MiniCPM / OpenBMB Modes | Pending | MiniCPM-o, MiniCPM5-1B, fallback routing |
| 10 | Pitch Deck Critique Mode | Pending | MiniCPM-V 4.6 image upload + slide critique |
| 11 | Retry + Report Enhancements | Pending | Retry weakest question; downloadable markdown report |
| 12 | UI Polish + Demo Flow | Pending | Animations, model badges, mobile, dark arena look |
| 13 | Hugging Face Spaces Deployment | Pending | HF Space Secrets, public test, screenshots |
| 14 | Final Testing + Submission Readiness | Pending | All endpoints, all modes, all failure paths |

---

## Immediate Next Tasks (Phase 3)

1. In `core/api_handlers.py`: import `model_router` and `persona_builder`
2. In `handle_start_session`: build system prompt via `persona_builder.build_persona_prompt()`, call `model_router.generate_opponent_response()`, use mock opening as fallback if `ok=False`
3. In `handle_chat_round`: build message list from session history, call `model_router.generate_opponent_response()`, use mock followup as fallback if `ok=False`
4. Run full battle flow end-to-end: load sample → start session → 2 chat rounds → end battle
5. Confirm Nemotron response is sharp, persona-locked, and references attack tag
6. Update docs after confirming end-to-end works

**Do not touch scoring, voice, deal battle, or deck critique in Phase 3.**

---

## Phase 2 Completed Tasks

- [x] `.env.example` verified — all variables present and correct
- [x] `core/nvidia_client.py` created
  - [x] Reads keys from `os.getenv` only — no hardcoded values
  - [x] `generate_nemotron_response(messages, mode, temperature, max_tokens, timeout)` implemented
  - [x] Timeout handling (30s default)
  - [x] Returns string on success; raises `RuntimeError` with clean message on failure
  - [x] `reasoning_content` fallback for reasoning model edge cases
  - [x] No API key or URL hardcoded anywhere
- [x] `core/model_router.py` created
  - [x] Routes `premium_nvidia` → nvidia_client (live)
  - [x] Stub/placeholder routes for `openbmb_omni`, `tiny_minicpm`, `vision_deck`, `whisper_fallback`
  - [x] Graceful fallback if NVIDIA fails (`ok=False`, fallback message returned, no crash)
  - [x] `get_model_health()` — all providers, no key exposure
- [x] `core/minicpm_client.py` stub created (health_check only)
- [x] `core/vision_client.py` stub created (health_check only)
- [x] `core/transcription_client.py` stub created (health_check only)
- [x] `scripts/test_nvidia_client.py` — isolated test, exits 0 on success / 1 on failure
- [x] Isolated NVIDIA test: **PASSED** — live Nemotron response confirmed
- [x] `GET /api/model-health` added to `app.py`
- [x] `requirements.txt` updated: `openai>=1.0.0`, `httpx`, `requests` added
- [x] Mock followup lists remain in `api_handlers.py` — not removed
- [x] `docs/PHASE_WISE_PLAN.md` Phase 2 marked Complete
- [x] `docs/FIELD_NOTES.md` updated with Phase 2 build log
- [x] `docs/BACKEND_API.md` `/api/model-health` added
- [x] `docs/MODELS_FINAL.md` model-to-file mapping updated with Phase 2 status

---

## Phase 1 Completed Tasks (for reference)

- [x] `app.py` — Gradio Server with `/api/*` REST routes and `@app.api` wrappers
- [x] `frontend/index.html`, `styles.css`, `script.js` — custom battle arena UI
- [x] `core/session_manager.py` — in-memory session store
- [x] `core/persona_builder.py` — system prompt builder per persona
- [x] `core/attack_tags.py` — tag taxonomy + round-based selector
- [x] `core/scoring_engine.py` — mock scorecard with real session quotes
- [x] `core/feedback_generator.py` — mock rewrite templates
- [x] `core/json_utils.py` — JSON extraction, safe parse, fallback scorecard
- [x] `core/samples.py` — EventRadar AI sample startup
- [x] `core/local_text_model.py` — Phase 1 stub
- [x] `core/voice_transcriber.py` — Phase 1 stub
- [x] `config/personas.json`, `attack_tags.json`, `pitch_rubric.json`, `sample_startups.json`
- [x] `docs/BACKEND_API.md`, `DOCUMENTATION.md`, `FIELD_NOTES.md`, `DEMO_NOTES.md`, `MODELS_FINAL.md`, `PHASE_WISE_PLAN.md`, `PROMPTS.md`
- [x] `.env.example` — all required variables present

---

## Risks Before Phase 2

| Risk | Mitigation |
|---|---|
| NVIDIA API key not yet provisioned | Get key from NVIDIA developer portal; add to `.env` before Phase 2 testing |
| Nemotron endpoint may need special headers or model format | Test isolated before wiring into session flow |
| `openai` Python SDK compatibility with NVIDIA base URL | NVIDIA uses OpenAI-compatible API; use `openai.OpenAI(base_url=..., api_key=...)` |
| Session manager is in-memory; process restart loses sessions | Acceptable for hackathon; note as known limitation |
| Mock fallback strings (MOCK_FOLLOWUPS) must stay in api_handlers.py | Do not delete until real model routing is confirmed stable |
