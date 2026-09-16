# Field Notes: PitchFight AI

Build log for the Hugging Face **Build Small Hackathon** (Backyard AI track).  
PitchFight AI is a practice arena for student founders — not a replacement for real mentors, investors, or hackathon judges.

---

## What we built

PitchFight AI is an AI founder pressure arena where student builders:

1. Enter a startup idea (quick pitch, advanced form, or voice pitch)
2. Get an AI-structured founder briefing
3. Choose a judge persona and difficulty mode
4. Survive multi-round pitch Q&A in a battle-style UI
5. Enter an optional deal-style pressure round
6. Receive a scorecard with coaching and a retry path for the weakest answer

**Stack:** Hugging Face Spaces · Gradio Server (`app.py`) · custom HTML/CSS/JS frontend · NVIDIA Nemotron API (backend-only) · `ffmpeg` for audio · optional MongoDB persistence.

The browser talks only to `/api/*`. Model calls never run in the frontend.

---

## Why this exists

Most student founders rehearse slides alone or with friends who are too nice. The first hard questions usually come from a real panel — and that is when answers fall apart.

We wanted a low-friction place to practice **under pressure** before that moment. The goal is coaching and repetition, not pretending an AI judge is a substitute for human feedback.

---

## Product decisions

- **Arena, not chatbot.** Flow is staged: landing → briefing → battle → deal → scorecard. It should feel like stepping into a fight, not opening a generic assistant.
- **Structured briefing first.** Raw ideas get structured before the judge attacks, so users practice defending a clear narrative.
- **Personas + difficulty.** Skeptical VC, technical judge, and hackathon judge modes change tone and pressure without swapping the whole product.
- **Scorecard over vibes.** Output is actionable: what landed, what was weak, what to rewrite — not just “good job.”
- **Voice as an entry path, not the whole app.** Voice pitch and voice answers are supported where enabled, but text mode stays fully usable.

---

## AI judge design

Judges are prompt-driven personas routed through a single backend model layer. Design choices:

- **Follow-up questions, not monologues.** Each round pushes on claims, gaps, and vague traction.
- **Persona-specific pressure.** VC mode leans market and defensibility; technical mode probes AI necessity and feasibility; hackathon mode focuses on demo clarity and MVP.
- **Attack tags / rubric hooks** (in config) keep scoring and feedback aligned with what was actually said, not generic startup advice.
- **Retry weakest answer.** After the scorecard, users can rework one weak response — closer to coaching than a one-shot grade.

This is simulated judgment for practice. Real panels bring context, chemistry, and standards no API can fully replicate.

---

## NVIDIA Nemotron usage

- **API:** `https://integrate.api.nvidia.com/v1`
- **Primary model:** `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning`
- **Key handling:** `NVIDIA_API_KEY` lives in `.env` locally and in **HF Space Secrets** in deployment — never in the frontend or git.
- **Routing:** `core/model_router.py` → `core/nvidia_client.py` for judge questions, structuring, scoring, rewrites, and voice-related paths where enabled.

**Practical note:** This is a reasoning model. It can spend tokens on internal reasoning before the visible reply. We tuned `max_tokens` per task so the user-facing answer stays in character and concise.

We use Nemotron as the main inference backend for the demo build. We are **not** claiming fine-tuning or custom model training.

---

## Custom UI / Off Brand decisions

We deliberately avoided default Gradio widgets for the product surface.

- **Custom frontend** (`frontend/`) — cinematic landing, briefing layout, battle stage, deal screen, scorecard.
- **Game-like presentation** — spotlights, arena framing, persona cards, pressure-meter styling. Pitch practice should feel memorable in a demo, not like a form filler.
- **Gradio as host, not as UI.** `app.py` serves the static frontend and REST API; Gradio is the deployment shell on Spaces.

This aligns with an **Off-Brand** spirit (custom experience on HF infrastructure) without claiming we built a different framework.

---

## Hugging Face deployment notes

- **Space type:** Gradio Space, `app_file: app.py`, custom `/` homepage serving `frontend/index.html`.
- **Secrets:** `NVIDIA_API_KEY` required; optional flags for voice, deal battle, deck critique, MongoDB.
- **System deps:** `packages.txt` includes `ffmpeg` for audio pipelines.
- **Layout tuning:** Landing and briefing screens were adjusted for the Spaces desktop viewport — including the white HF navbar above the app iframe. We use `100svh` / `100dvh` with safe padding and a small JS viewport sync so the hero fills the **visible app area** without a dead band at the bottom or content hidden under chrome.

Local dev at `127.0.0.1:7860` does not show the HF navbar; we tested both locally and in the live Space while iterating on layout.

---

## What worked well

- **Backend-only inference** kept secrets out of the browser and simplified deployment.
- **Custom UI + `/api/*` contract** made it easy to iterate on flow without fighting Gradio components.
- **Phased product shape** (brief → battle → deal → scorecard) reads clearly in a short demo.
- **Persona and difficulty toggles** give variety without multiplying model integrations.
- **Honest coaching tone** in prompts and scorecard copy — useful feedback without overclaiming “investor approval.”

---

## Tradeoffs and limitations

- **Coaching tool, not truth.** AI judges can be sharp but wrong, repetitive, or too harsh. Users still need humans for real validation.
- **Reasoning model latency and token budget.** Longer waits and token tuning are part of the tradeoff for quality follow-ups.
- **Voice depends on environment.** `ffmpeg`, browser permissions, and API availability affect voice mode reliability on Spaces.
- **Deck critique / MongoDB** are optional paths — not every deployment enables them.
- **No production-scale eval suite.** We did not run formal benchmarks or user studies for this hackathon build; quality is judged by manual demo runs and iterative prompt tuning.
- **Layout is viewport-sensitive.** Short or embedded viewports may still need scroll on dense screens (e.g. advanced briefing); landing is tuned for HF desktop first.

---

## Submission evidence

| Item | Link |
|------|------|
| **Live Space** | `[Add your HF Space URL]` |
| **Demo video** | `[Add demo video URL]` |
| **Hugging Face blog / write-up** | `[Add blog or post URL]` |

**Repo highlights for judges:** `app.py` (API + frontend host) · `core/api_handlers.py` · `core/model_router.py` · `frontend/` (custom UI) · `docs/DOCUMENTATION.md` (technical depth)

---

### Not claiming

- Not claiming **OpenBMB / MiniCPM**
- Not claiming **Modal**
- Not claiming **Tiny Titan**
- Not claiming **Off the Grid**
- Not claiming **fine-tuning**
