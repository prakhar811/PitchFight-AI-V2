# PitchFight AI — Phase-Wise Implementation Plan

## Full Sponsor-Model Build Plan for Voice, Text, Deal Battle, Scorecards, and Demo Polish

PitchFight AI is a voice-and-text AI sparring arena for student founders. The project prioritizes the strongest possible demo experience using small models under 32B, including NVIDIA Nemotron Omni for premium voice/multimodal judge behavior, OpenBMB MiniCPM models for sponsor-aligned modes, a custom Gradio Server frontend, persona-based pitch battles, deal negotiation battles, and rubric-based scorecards.

> **Strategy note:** This version does **not** claim the Off-the-Grid badge because the default high-quality build may use sponsor/model APIs. This is intentional. The project instead targets **Backyard AI**, **Best Demo**, **Best Agent**, **Off-Brand**, **NVIDIA Nemotron Quest**, **OpenBMB Awards**, **Sharing is Caring**, and **Field Notes**.

---

## 1. Final Build Goal

The complete final app includes:

- Custom Gradio Server app
- Custom HTML/CSS/JS frontend
- Pitch Battle mode
- Deal Battle mode
- Voice Pitch mode
- Text Pitch mode
- AI opponent personas
- Attack-tag routing
- Session memory
- NVIDIA Nemotron Omni integration
- MiniCPM-o / MiniCPM fallback modes
- MiniCPM-V pitch deck critique mode
- Scorecard engine
- Weakest answer rewrite
- Improved 60-second pitch
- Retry weakest question
- HF Spaces deployment
- Documentation and demo notes

**Focus:** demo strength, model quality, and sponsor-model alignment — **not** Off-the-Grid.

All models stay **≤32B parameters**. The app is built on **Gradio**, hosted as a **Hugging Face Space**, uses a **custom non-default UI**, and keeps **all API keys in backend/HF Space Secrets** only (never in the frontend).

---

## 2. Master Build Order

| Phase | Name |
|---|---|
| **Phase 0** | Strategy Reset + Documentation Alignment |
| **Phase 1** | Project Skeleton Verification |
| **Phase 2** | Model Router + Secrets Setup |
| **Phase 3** | NVIDIA Nemotron Omni Integration |
| **Phase 4** | Pitch Battle Engine |
| **Phase 5** | Scorecard + Feedback Engine |
| **Phase 6** | Custom Frontend Integration |
| **Phase 7** | Voice Pitch Mode |
| **Phase 8** | Deal Battle Mode |
| **Phase 9** | MiniCPM / OpenBMB Modes |
| **Phase 10** | Pitch Deck Critique Mode |
| **Phase 11** | Retry + Report Enhancements |
| **Phase 12** | UI Polish + Demo Flow |
| **Phase 13** | Hugging Face Spaces Deployment |
| **Phase 14** | Final Testing + Submission Readiness |

---

## 3. Phase 0 — Strategy Reset + Documentation Alignment

**Goal:** Ensure all repository docs reflect the high-demo sponsor-model strategy (historical local-first/off-grid wording removed).

**Tasks:**

- Remove wording that says the default build is Off-the-Grid.
- Keep a note that Off-the-Grid is **not** targeted.
- Update model strategy to include **NVIDIA Nemotron Omni** as the primary premium model.
- Add **MiniCPM-o** as OpenBMB advanced mode.
- Add **MiniCPM5-1B** as Tiny/Fallback mode.
- Add **MiniCPM-V 4.6** as pitch deck critique mode.
- Keep **faster-whisper** as backup transcription fallback.
- Update `README.md`, `docs/DOCUMENTATION.md`, `docs/PROMPTS.md`, `docs/DEMO_NOTES.md`, `docs/FIELD_NOTES.md`, and `docs/MODELS_FINAL.md` accordingly.

**Success check:** All docs agree that the project is under 32B, Gradio/HF Spaces based, and high-demo sponsor-model focused.

---

## 4. Phase 1 — Project Skeleton Verification

**Goal:** Verify that the existing Gradio Server + custom frontend skeleton works.

**Tasks:**

- Check `app.py` exists.
- Check `frontend/index.html`, `styles.css`, `script.js` exist.
- Check `core/` modules exist.
- Check `config/` files exist.
- Run `python app.py`.
- Confirm custom UI opens.
- Confirm mock battle works.
- Confirm mock scorecard appears.

**Files:**

- `app.py`
- `frontend/*`
- `core/*`
- `config/*`
- `docs/*`

**Success check:** Custom PitchFight AI UI opens and mock demo flow runs.

**Current status:** ✅ Complete (Phase 1 skeleton in place with mock APIs).

**API layer:** Clean product endpoints live under `/api/...` (see [`BACKEND_API.md`](BACKEND_API.md)). Gradio internal routes in Swagger are framework runtime routes, not PitchFight product APIs.

---

## 5. Phase 2 — Model Router + Secrets Setup

**Goal:** Create a clean backend-only model routing layer.

**Tasks:**

- Create or update `core/model_router.py`.
- Create or update `core/nvidia_client.py`.
- Create or update `core/minicpm_client.py`.
- Create or update `core/vision_client.py`.
- Create or update `core/transcription_client.py`.
- Ensure frontend never calls model APIs.
- Add env variables to `.env.example`.
- Read keys only from `os.getenv` (`.env` locally, HF Space Secrets in deployment).
- Frontend calls `/api/*` only — never model provider APIs.
- Add graceful fallback if a model call fails.

**Environment variables:**

```text
NVIDIA_API_KEY=
NVIDIA_BASE_URL=https://integrate.api.nvidia.com/v1
NVIDIA_OMNI_MODEL=nvidia/nemotron-3-nano-omni-30b-a3b-reasoning

OPENBMB_API_KEY=
OPENBMB_BASE_URL=
MINICPM_OMNI_MODEL=openbmb/MiniCPM-o-4_5
MINICPM_TEXT_MODEL=openbmb/MiniCPM5-1B
MINICPM_VISION_MODEL=openbmb/MiniCPM-V-4.6

HF_TOKEN=
WHISPER_FALLBACK_ENABLED=true
MAX_ROUNDS=6
APP_ENV=development
```

**Success check:** Backend can select a model path:

- `premium_nvidia`
- `openbmb_omni`
- `tiny_minicpm`
- `vision_deck`
- `whisper_fallback`

**Current status:** ✅ Complete (2026-06-08). `core/nvidia_client.py` and `core/model_router.py` created. NVIDIA connectivity tested — live response confirmed. Stub clients created for MiniCPM, vision, and transcription. `GET /api/model-health` added.

**Key discovery:** `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning` is a reasoning model. It uses tokens for an internal chain-of-thought before writing `message.content`. Token defaults: opponent=500, scorecard=2000, rewrite=800. A `reasoning_content` fallback is in place for edge cases.

---

## 6. Phase 3 — NVIDIA Nemotron Omni Integration

**Goal:** Make NVIDIA Nemotron Omni the primary premium reasoning and voice/multimodal judge model.

**Tasks:**

- Implement secure backend call using `NVIDIA_API_KEY`.
- Add function `generate_nemotron_response(messages, mode)`.
- Add timeout handling.
- Add retry handling.
- Add fallback to MiniCPM mode if NVIDIA fails.
- Test text-only judge prompt first.
- Test scoring prompt second.
- Test voice/multimodal input after text works.

**Use cases:**

- AI opponent response
- Voice pitch critique
- Deal battle counterpart
- Scorecard generation
- Weakest answer rewrite
- Optional pitch deck + spoken explanation critique

**Success check:** Backend receives a startup context and Nemotron returns a sharp judge question.

---

## 7. Phase 4 — Pitch Battle Engine

**Goal:** Make Pitch Battle real.

**Tasks:**

- Connect `/start_session` to `model_router`.
- Connect `/chat_round` to `model_router`.
- Use `persona_builder.py`.
- Use `attack_tags.py`.
- Store history in `session_manager.py`.
- Rotate attack tags.
- Return `attack_tag`, `pressure_level`, `round`, `ai_message`.
- Support 3 personas:
  - Skeptical VC
  - Technical Judge
  - Hackathon Judge

**Success check:** User enters EventRadar AI, selects Hackathon Judge, and receives a sharp AI challenge.

---

## 8. Phase 5 — Scorecard + Feedback Engine

**Goal:** Generate real scorecards.

**Tasks:**

- Build scoring prompt from conversation history.
- Use NVIDIA Nemotron as default scorer.
- Use MiniCPM fallback if needed.
- Parse scorecard JSON safely.
- Implement JSON fallback pipeline.
- Generate:
  - overall score
  - 6 pitch dimensions
  - best answer
  - weakest answer
  - improved answer
  - improved pitch
  - top 3 prep questions

**Files:**

- `core/scoring_engine.py`
- `core/feedback_generator.py`
- `core/json_utils.py`
- `app.py`
- `frontend/script.js`

**Success check:** End Battle produces structured scorecard with user quotes and useful rewrites.

---

## 9. Phase 6 — Custom Frontend Integration

**Goal:** Connect UI fully to backend APIs.

**Tasks:**

- Connect Gradio JS Client.
- Load demo startup.
- Start session.
- Render AI question.
- Render user messages.
- Render AI follow-ups.
- Render attack tag.
- Render pressure meter.
- Render scorecard.
- Show model mode badge:
  - Premium Nemotron
  - OpenBMB Omni
  - Tiny MiniCPM
- Handle errors and loading states.

**Success check:** User can complete full Pitch Battle from UI.

---

## 10. Phase 7 — Voice Pitch Mode

**Goal:** Make voice mode a major demo feature.

**Primary path:**

```text
Browser records audio
  → backend sends audio/transcript to NVIDIA Nemotron Omni
  → AI extracts pitch understanding
  → AI asks first hard question
  → user continues by voice or text
```

**Fallback path:**

```text
Browser records audio
  → faster-whisper transcribes locally
  → transcript goes to selected text model
  → battle starts
```

**Tasks:**

- Add browser audio recorder.
- Add `/voice_pitch` endpoint.
- Add audio upload handling.
- Add transcript/interpretation panel.
- Add user editable transcript.
- Add voice-specific metrics:
  - Structure
  - Conciseness
  - Confidence Signals
  - Directness
- Continue battle from voice input.

**Success check:** User records a pitch and receives a hard first question.

---

## 11. Phase 8 — Deal Battle Mode

**Goal:** Add negotiation practice.

**Scenarios:**

- Startup Sponsorship Ask
- Internship Salary Negotiation
- Freelance Client Pricing
- Equity Negotiation

**Personas:**

- Tough Sponsor
- Strict HR Recruiter
- Budget-Conscious Client
- Hard-Negotiating Investor

**Tasks:**

- Add Deal Battle mode to UI.
- Add negotiation context form.
- Add deal personas.
- Add deal attack tags.
- Add deal rubric.
- Route deal battle to `model_router`.
- Generate negotiation-specific scorecard.

**Success check:** User can negotiate and receive a deal-specific scorecard.

---

## 12. Phase 9 — MiniCPM / OpenBMB Modes

**Goal:** Add OpenBMB sponsor-aligned models and fallback modes.

**Models:**

- **MiniCPM-o 4.5** — OpenBMB Omni Mode
- **MiniCPM5-1B** — Tiny Mode / fallback
- **MiniCPM-V 4.6** — vision mode

**Tasks:**

- Add model selector or backend mode switch.
- Add OpenBMB Omni mode.
- Add Tiny MiniCPM mode.
- Add fallback if NVIDIA errors.
- Add docs explaining model use cases.

**Success check:** App can run at least one OpenBMB mode and one fallback mode.

---

## 13. Phase 10 — Pitch Deck Critique Mode

**Goal:** Add image/slide critique.

**Primary model:** MiniCPM-V 4.6 or NVIDIA Omni.

**Tasks:**

- Add image upload.
- Add `/deck_critique` endpoint.
- Extract slide claims.
- Critique clarity, problem, solution, market, ask.
- Generate 3 judge questions based on the slide.

**Success check:** User uploads a pitch slide screenshot and receives useful critique.

---

## 14. Phase 11 — Retry + Report Enhancements

**Goal:** Make it feel product-ready.

**Tasks:**

- Add Retry Weakest Question.
- Store weakest AI question.
- Compare original vs retried answer.
- Generate downloadable markdown report.
- Add full session summary.
- Add “Start New Battle”.

**Success check:** User can retry the weakest objection and get improvement guidance.

---

## 15. Phase 12 — UI Polish + Demo Flow

**Goal:** Make it visually memorable.

**Tasks:**

- Improve landing hero.
- Add model mode badges.
- Add premium voice mode card.
- Add deck critique card.
- Add battle arena split layout.
- Add score animations.
- Add voice recording animation.
- Add mobile responsiveness.
- Add error banners.
- Add loading states.

**Design:** Dark battle arena, red pressure accents, gold score accents, glass cards, custom typography.

**Success check:** The app looks like a custom product, not default Gradio.

---

## 16. Phase 13 — Hugging Face Spaces Deployment

**Goal:** Deploy publicly.

**Tasks:**

- Add README metadata.
- Add required secrets in HF Space Settings.
- Confirm app builds.
- Confirm no keys are exposed.
- Test all modes publicly.
- Add screenshots to README.
- Add final Space link.

**Success check:** Public HF Space completes:

- Text Pitch Battle
- Voice Pitch Battle
- Deal Battle
- Scorecard
- Deck critique (if built)

---

## 17. Phase 14 — Final Testing + Submission Readiness

**Tasks:**

- Test every endpoint.
- Test every UI button.
- Test failure fallback.
- Test missing API keys.
- Test slow responses.
- Test mobile layout.
- Update README.
- Update docs.
- Prepare demo flow.
- Prepare field notes.
- Prepare social post separately.

**Badges/prizes to mention:**

- Backyard AI
- Best Demo
- Best Agent
- Off-Brand
- NVIDIA Nemotron Quest
- OpenBMB Awards
- Sharing is Caring
- Field Notes
- Tiny Titan (if Tiny Mode works)

---

## Final One-Line Pitch

**PitchFight AI is a voice-and-text AI sparring arena where student founders practice tough startup pitches, get grilled by realistic AI judges under 32B parameters, and receive a scorecard that shows exactly how to answer better.**
