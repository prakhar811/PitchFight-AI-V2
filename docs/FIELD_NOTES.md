# PitchFight AI — Field Notes

## Why This Exists

Student founders often practice pitches alone or with friendly feedback. The first real pressure hits during judging, mentoring, investor calls, or sponsorship negotiations. PitchFight AI creates a safe but intense sparring arena before that moment.

## Strategic Pivot (Phase 0)

We moved from an **Off-the-Grid / local-first** strategy to a **high-demo sponsor-model** strategy:

- **Not targeting** Off-the-Grid badge.
- **Targeting** Backyard AI, Best Demo, Best Agent, Off-Brand, NVIDIA Nemotron Quest, OpenBMB Awards, Sharing is Caring, Field Notes.
- Still compliant: ≤32B models, Gradio, HF Spaces, no frontend API keys.

## What Was Built

### Phase 1 (Complete)

- Hugging Face Spaces-ready Gradio Server skeleton
- Custom battle arena frontend (HTML/CSS/JS)
- In-memory session manager
- Persona + attack-tag routing
- Mock scoring and feedback (placeholder for real models)
- Config files for personas, rubric, samples

### Planned (Phases 2–14)

- Model router + NVIDIA / OpenBMB clients
- Real Pitch Battle + Deal Battle engines
- Voice pitch mode (Nemotron primary, whisper fallback)
- Pitch deck critique (MiniCPM-V)
- Retry weakest question + downloadable report
- UI polish + public HF Space deployment

## What the Models Will Do

| Model | Job |
|---|---|
| Nemotron Omni | Premium judge, voice, scoring, rewrites |
| MiniCPM-o | OpenBMB multimodal mode |
| MiniCPM5-1B | Tiny/fallback text |
| MiniCPM-V 4.6 | Slide critique |
| faster-whisper | Backup transcription |

## What Worked

- Clean separation: frontend → Gradio API → model router → clients
- Attack-tag driven pressure design
- Runnable Phase 1 skeleton for fast iteration
- Clear phase-wise plan for hackathon execution

## What Will Be Improved

- Replace mock APIs with Nemotron + MiniCPM routing (Phase 2–5)
- Voice mode as headline demo feature (Phase 7)
- Deal Battle + deck critique (Phases 8–10)
- Product polish and public deployment (Phases 12–14)

## Build Log

### Phase 2 — Model Router + Secrets Setup (2026-06-08)

**What shipped:**
- `core/nvidia_client.py` — backend-only NVIDIA Nemotron client using OpenAI-compatible SDK
- `core/model_router.py` — central routing layer (premium_nvidia live; other modes return clean stubs)
- `core/minicpm_client.py` — health_check stub (Phase 9 placeholder)
- `core/vision_client.py` — health_check stub (Phase 10 placeholder)
- `core/transcription_client.py` — health_check stub (Phase 7 placeholder)
- `scripts/test_nvidia_client.py` — isolated connectivity test (exits 0/1, no key exposure)
- `GET /api/model-health` — config status endpoint, keys never exposed
- `requirements.txt` updated: added `openai>=1.0.0`, `httpx`, `requests`

**What worked:**
- NVIDIA API key read from `NVIDIA_API_KEY` env var only — no hardcoding, no key leak
- `health_check()` correctly reports configured/not-configured without printing key
- `generate_nemotron_response()` returns clean judge question on first real test
- `get_model_health()` returns correct provider status for all four providers
- Error handling catches timeout, connection, and status errors cleanly

**What surprised us:**
- `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning` is a **reasoning model**: it writes an internal chain-of-thought before the final answer. When `max_tokens` is too small (< ~400 for opponent mode), all tokens are consumed by the reasoning trace and `message.content` is `None`.
- The fix: increase `max_tokens` defaults (opponent: 500, scorecard: 2000, rewrite: 800) and add a `reasoning_content` fallback for edge cases.
- The final answer in `message.content` is sharp, in-character, and correctly short — the reasoning trace stays internal.

**What the model returned (live test):**
> "How does your AI differentiate between similar events and avoid false positives in ranking?"

**What we'd do differently:**
- Test with the actual model before setting token defaults — reasoning models have different budget dynamics than completion models.

**What's next:**
- Phase 3: Wire `model_router.generate_opponent_response()` into `handle_start_session` and `handle_chat_round` in `core/api_handlers.py` — replacing hardcoded mock followups with live Nemotron responses.
