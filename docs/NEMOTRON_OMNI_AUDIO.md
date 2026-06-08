# NVIDIA Nemotron 3 Nano Omni — Audio & Voice Architecture

Technical reference for how **NVIDIA Nemotron 3 Nano Omni 30B-A3B** processes pitch audio in PitchFight AI, what it can infer about hesitation and confidence, and how the app should wire voice mode.

> **PitchFight context:** Nemotron Omni is the **primary premium judge** (backend-only API). Raw audio goes to the model on the primary path. **faster-whisper** is transcription fallback only — not the main judge. Frontend never calls NVIDIA directly; audio flows through `/api/voice-pitch`.

See also: [`MODELS_FINAL.md`](MODELS_FINAL.md) · [`BACKEND_API.md`](BACKEND_API.md) · [`PHASE_WISE_PLAN.md`](PHASE_WISE_PLAN.md)

---

## 1. Model Identity

| Field | Value |
|---|---|
| **Model** | NVIDIA Nemotron 3 Nano Omni 30B-A3B |
| **Env var** | `NVIDIA_OMNI_MODEL=nvidia/nemotron-3-nano-omni-30b-a3b-reasoning` |
| **Parameter cap** | ~30B — complies with Build Small ≤32B rule |
| **Access** | Backend-only via `NVIDIA_API_KEY` + `NVIDIA_BASE_URL` |
| **Role in PitchFight** | Primary voice/text/multimodal judge, scorecard, rewrites |

---

## 2. How the Model Works With Audio

### Unified encoder–projector–decoder design

NeMoTron Nano Omni uses a **unified multimodal architecture**:

- **Language backbone:** Nemotron 3 Nano 30B-A3B (reasoning)
- **Vision encoder:** C-RADIOv4-H
- **Audio encoder:** Parakeet-TDT-0.6B-v2

Modality-specific encoders connect into the LLM backbone through **lightweight projectors**. Audio and text share the same reasoning loop inside the backbone.

### Exact pipeline when an audio file hits the model

```text
Your WAV / audio file (raw bytes)
        ↓
Parakeet-TDT-0.6B-v2 (dedicated audio encoder)
        ↓ converts audio into audio tokens
Lightweight projector (aligns audio tokens to LLM embedding space)
        ↓
Nemotron 30B-A3B backbone (reasoning happens here)
        ↓
Structured text output (transcript, observations, judge question, etc.)
```

### What this is *not*

This is **fundamentally different** from Whisper → LLM:

| Approach | Flow |
|---|---|
| **Whisper → LLM** | Audio → text transcript → text-only reasoning |
| **Nemotron Omni (primary path)** | Audio → audio tokens → projected embeddings → unified reasoning |

On the Nemotron primary path, the model does **not** need to transcribe to plain text first before reasoning. Audio signals are preserved as tokens that flow into the backbone.

### Paralinguistic coverage

Parakeet provides strong ASR. NVIDIA extends the audio surface with **Granary** and **Music Flamingo** extensions, broadening coverage beyond bare transcription to include:

- Paralinguistic signals (tone, pace, stress, hesitation sounds)
- Music and ambient sound understanding

**Paralinguistic** = signals beyond literal words — how something is said, not only what is said. This is what makes the model competitive on voice benchmarks and useful for media understanding, not just dictation.

---

## 3. Quick Answers (FAQ)

| Question | Answer |
|---|---|
| Does the raw audio file go to Nemotron? | **Yes** — Parakeet processes native audio input. |
| Does it get transcribed to text first? | **No** on the primary Omni path — audio tokens flow directly into reasoning. |
| Does it use embeddings? | **Yes** — audio tokens are projected into the LLM embedding space. |
| Can it detect hesitation? | **Yes** — linguistic hesitation and filler words reliably. |
| Can it detect confidence from voice tone? | **Partially** — paralinguistic inference, not clinical prosody analysis. |
| Is this strong enough for a pitch trainer? | **Yes** — linguistic hesitation is the most actionable signal for founders. |
| How do you make it accurate? | **Prompt explicitly** for delivery observations alongside content. |

---

## 4. Hesitation & Confidence Detection

### Partially yes — with important caveats

#### What it can detect reliably

The Parakeet encoder (with Granary / Music Flamingo extensions) processes **paralinguistic features**. When preserved as audio tokens in the backbone, the LLM can reason about:

| Signal | Example |
|---|---|
| Filler words | "um", "uh", "like", "you know" |
| Long pauses | Mid-sentence gaps before a key claim |
| Trailing off | Weak endings on important statements |
| Rushed speech | Compressed delivery on uncertain phrases |
| Repetition / self-correction | Restarts, hedging, reformulations |

For pitch training, **linguistic hesitation is often the most useful signal**:

> *"Um… I think… maybe the market is… around 10 million?"*  
> vs  
> *"The addressable market is $10M based on X."*

The model can flag the first pattern when prompted correctly.

#### What it cannot detect reliably

Pure acoustic / physiological confidence signals require dedicated prosody tools (e.g. Praat, specialized emotion models), not a general-purpose multimodal LLM:

- Heart rate change
- Micro-tremors in voice
- Subtle pitch drops indicating clinical-level uncertainty

**Do not claim** heart-rate or micro-tremor detection in PitchFight UI or demo script.

#### Honest positioning

NeMoTron can detect **linguistic hesitation** (words and sounds of hesitation) and make **reasonable inferences** about apparent confidence from speech patterns. It cannot do **clinical-grade prosody analysis**. For a student pitch trainer, that is the right tradeoff.

---

## 5. Voice Scorecard Metrics (Grounded in Architecture)

Only score dimensions the model can plausibly observe:

| Metric | How Nemotron detects it | Reliability |
|---|---|---|
| Filler word count | Direct from audio tokens + transcript | **High** |
| Pause before key claims | Temporal gap in audio | **Medium–High** |
| Self-corrections | Restarts in transcript / audio pattern | **High** |
| Trailing off on weak claims | Audio token patterns | **Medium** |
| Speaking pace (rushed vs calm) | Token density over time | **Medium** |
| Confidence on specific claims | Inference from above signals | **Medium** |

When on **Whisper fallback**, mark voice-derived metrics as unavailable or transcript-only.

---

## 6. PitchFight AI Voice Architecture

### Path A — Nemotron direct (primary, when API available)

```text
Browser records audio
        ↓
POST /api/voice-pitch (backend only)
        ↓
NVIDIA Nemotron Omni
        ↓
Parakeet encoder processes raw audio
        ↓
Paralinguistic + linguistic signals preserved in backbone
        ↓
Single API response includes:
  - transcript
  - delivery_observations (hesitation / pace / fillers)
  - detected_startup_context
  - opening judge question
        ↓
Pitch Battle continues (voice or text)
```

**UI badge:** `⚡ Voice Analysis Active` (or similar) when Path A is active.

### Path B — Whisper fallback (when Nemotron audio path fails)

```text
Browser records audio
        ↓
POST /api/voice-pitch
        ↓
faster-whisper local transcription
        ↓
Clean transcript text only (no paralinguistic tokens)
        ↓
Nemotron or MiniCPM5-1B text reasoning
        ↓
Judge question (no delivery observations)
        ↓
Scorecard notes: "Voice delivery metrics unavailable in fallback mode"
```

**UI badge:** `📝 Text Mode` (transcript-only fallback).

Path A is the **demo differentiator**. Path B keeps the app working when audio API fails, keys are missing, or latency/errors trigger fallback.

### Security

- Audio upload hits **backend only** — never send `NVIDIA_API_KEY` to the browser.
- Keys live in `.env` locally and **HF Space Secrets** in deployment.

---

## 7. Recommended Voice Prompt (Hesitation / Delivery)

When sending audio to Nemotron for `/api/voice-pitch`, include instructions like:

```text
Listen to this pitch audio carefully.

Beyond the words spoken, note:
- Any filler words (um, uh, like, you know, sort of)
- Any long pauses before answering a key claim
- Any statements that trail off or sound uncertain
- Any rushing through parts they seem unsure about
- Any self-corrections or restarts

After understanding the pitch, include a section called
DELIVERY OBSERVATIONS with specific timestamps or quotes
where hesitation or low confidence was audible.

Extract startup context fields if possible.
Then ask your first hard judge question in character.
Return structured JSON when requested.
```

Anchoring the model to **delivery observations** makes paralinguistic reporting explicit instead of hoping it infers them silently.

### Suggested structured response fields (Phase 7+)

```json
{
  "transcript": "...",
  "delivery_observations": [
    {
      "type": "filler_words",
      "quote_or_timestamp": "0:12 — 'um, I think maybe...'",
      "note": "Hedging before market size claim"
    }
  ],
  "detected_startup_context": { },
  "opening_question": "..."
}
```

Exact schema should match `core/api_handlers.py` when voice mode is implemented.

---

## 8. Comparison: Nemotron Omni vs faster-whisper

| | Nemotron Omni (Path A) | faster-whisper (Path B) |
|---|---|---|
| **Input** | Raw audio | Raw audio |
| **Output** | Transcript + reasoning + delivery signals | Transcript text only |
| **Hesitation / pace** | Paralinguistic tokens in backbone | Not available |
| **Judge question** | Same call or follow-up text call | Requires separate text model call |
| **Role in PitchFight** | Primary voice judge | Transcription fallback only |
| **Runs** | NVIDIA API (backend) | Local on Space / dev machine |

---

## 9. Implementation Notes (Future Phases)

Planned wiring (no app logic in this doc — reference only):

| Module | Responsibility |
|---|---|
| `core/nvidia_client.py` | Send audio + prompt to Nemotron API; parse structured response |
| `core/model_router.py` | Choose `premium_nvidia` vs `whisper_fallback` |
| `core/transcription_client.py` | faster-whisper when Omni audio fails |
| `core/api_handlers.py` | `handle_voice_pitch()` orchestration |
| `frontend/script.js` | Upload audio to `/api/voice-pitch` only |

### Fallback triggers (suggested)

- NVIDIA API timeout or 5xx
- Missing `NVIDIA_API_KEY`
- Audio format unsupported by API
- Explicit `WHISPER_FALLBACK_ENABLED=true` override for debugging

### Demo talking points

1. **Raw audio goes to Nemotron** — not transcribe-then-reason on the premium path.
2. **Delivery observations** — fillers, pauses, trailing off — are first-class signals.
3. **Honest limits** — we score linguistic hesitation, not biometrics.
4. **Graceful fallback** — whisper keeps voice mode alive without breaking the demo.

---

## 10. References

- NVIDIA Nemotron 3 Nano Omni model card and integrate API docs (NVIDIA NIM / integrate.api.nvidia.com)
- Build Small Hackathon: ≤32B models, Gradio/HF Spaces, demo-first
- PitchFight model stack: [`MODELS_FINAL.md`](MODELS_FINAL.md)

---

## 11. Bottom Line

Nemotron Omni is the right primary voice model for PitchFight because it processes **raw audio through a dedicated encoder into a shared reasoning backbone**, preserving paralinguistic cues that matter for pitch coaching. Pair it with an explicit **delivery observations** prompt, honest scorecard metrics, and a **whisper fallback** that degrades visibly — not silently — when the premium audio path is unavailable.
