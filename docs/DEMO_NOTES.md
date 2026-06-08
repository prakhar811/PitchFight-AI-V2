# PitchFight AI — Demo Notes

## Strategic Demo Positioning

PitchFight AI is a **high-demo sponsor-model build** — not Off-the-Grid. Lead with voice, pressure, and scorecard quality. Mention NVIDIA Nemotron Omni and OpenBMB MiniCPM modes as sponsor-aligned small models under 32B.

## Full Demo Flow (Target Build)

1. Open the app — custom battle arena UI (not default Gradio).
2. Show **model mode badge** (Premium Nemotron / OpenBMB Omni / Tiny MiniCPM).
3. **Text path:** Load EventRadar AI → Hackathon Judge → Enter Arena → get grilled → End Battle → scorecard.
4. **Voice path:** Record spoken pitch → Nemotron interprets → first hard question → continue battle.
5. **Deal Battle:** Sponsorship or salary negotiation scenario → deal-specific scorecard.
6. **Deck critique (if built):** Upload slide screenshot → 3 judge questions.
7. **Retry:** Retry weakest question → show improvement.

## Phase 1 Demo Flow (Current)

1. Open the app.
2. Click **Load Demo Startup** (EventRadar AI).
3. Select **Hackathon Judge**.
4. Click **Enter the Arena**.
5. Answer weakly (e.g., "We use AI to rank events better").
6. Watch mock AI push back with attack tag + pressure level.
7. Click **End Battle** after 2–3 rounds.
8. Show scorecard: overall, bars, rewrites, top prep questions.

## Talking Points

- Custom Gradio Server frontend + `@app.api` backend.
- All model calls backend-only; keys in HF Space Secrets.
- ≤32B models: Nemotron Omni, MiniCPM-o, MiniCPM5-1B, MiniCPM-V.
- Voice + multimodal judging as differentiator.
- Rubric-based scorecard with quotes and rewrites.
- Off-the-Grid **not** claimed — demo quality is the goal.

## Prize Alignment Talking Points

| Prize | Hook |
|---|---|
| Backyard AI | Student founders, real pressure practice |
| Best Demo | Voice pitch → grill → scorecard in one flow |
| Best Agent | Persona + memory + attack tags + scoring loop |
| Off-Brand | Custom HTML/CSS/JS arena UI |
| NVIDIA Nemotron Quest | Premium voice/multimodal judge |
| OpenBMB Awards | MiniCPM-o / 5-1B / V modes |
| Sharing is Caring | Public prompts, rubrics, attack tags |
| Field Notes | Build story post-deployment |
