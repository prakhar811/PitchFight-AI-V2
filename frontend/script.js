import { initVoiceUI } from "./voice.js";

const state = {
  sessionId: null,
  persona: "hackathon_judge",
  difficultyProfile: "practice",
  round: 1,
  scoreExplanation: null,
  startMode: "text",
  pendingVoicePitch: null,
  pendingVoiceTurn: null,
  retryDrill: null,
  pendingRetryVoiceTurn: null,
  judgeVerdict: null,
  dealContext: null,
  dealRound: 1,
  uiMode: "pitch",
  pendingDealVoiceTurn: null,
  negotiationTranscript: [],
  conversationLog: [],
  dealConversationLog: [],
  battleLog: [],
  dealBattleLog: [],
  battleMetaSnapshot: null,
  scorecardSnapshot: null,
  briefingMode: "quick",
  briefStructured: false,
  pitchExtractionConfidence: null,
  battleConfidencePct: null,
};

let liveJudgeTurn = { text: "", meta: "" };
let liveFounderReply = "";
let liveDealJudgeTurn = { text: "", meta: "" };
let liveDealFounderReply = "";

const screens = {
  landing: document.getElementById("screen-landing"),
  startMethod: document.getElementById("screen-start-method"),
  voicePitch: document.getElementById("screen-voice-pitch"),
  voiceConfirm: document.getElementById("screen-voice-confirm"),
  setup: document.getElementById("screen-setup"),
  battle: document.getElementById("screen-battle"),
  scorecard: document.getElementById("screen-scorecard"),
  deal: document.getElementById("screen-deal"),
  dealScorecard: document.getElementById("screen-deal-scorecard"),
};

const dealChatWindow = document.getElementById("deal-chat-window");
const dealInput = document.getElementById("deal-input");
const dealStatus = document.getElementById("deal-status");

const startupForm = document.getElementById("startup-form");
const briefPreviewForm = document.getElementById("brief-preview-form");
const quickPitchPanel = document.getElementById("panel-quick-pitch");
const briefPreviewPanel = document.getElementById("brief-preview-panel");
const briefingLeftCol = document.querySelector(".briefing-left-col");
const chatWindow = document.getElementById("chat-window");
const userInput = document.getElementById("user-input");
const loadingOverlay = document.getElementById("loading-overlay");
const loadingText = document.getElementById("loading-message");
const battleStatus = document.getElementById("battle-status");
const errorBanner = document.getElementById("error-banner");

function showScreen(name) {
  Object.entries(screens).forEach(([key, el]) => {
    el.classList.toggle("active", key === name);
  });
  const app = document.getElementById("app");
  app?.classList.toggle("app-arena-fullwidth", name === "battle" || name === "deal" || name === "scorecard");
  app?.classList.toggle("app-scorecard-fullwidth", name === "scorecard");
  if (name === "landing" && landingIntroComplete) {
    finalizeLandingIntroStatic();
  }
}

/* ---- Landing typewriter intro (Pass 1 — isolated, no API impact) ---- */

let landingIntroComplete = false;
let landingIntroRunning = false;

function prefersReducedMotion() {
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

function finalizeLandingIntroStatic() {
  const line1Text = document.querySelector("#landing-type-line-1 .arena-type-text");
  const line2Text = document.querySelector("#landing-type-line-2 .arena-type-text");
  const line1 = document.getElementById("landing-type-line-1");
  const line2 = document.getElementById("landing-type-line-2");
  const landing = document.querySelector(".arena-landing");

  if (line1Text?.dataset.text) line1Text.textContent = line1Text.dataset.text;
  if (line2Text?.dataset.text) line2Text.textContent = line2Text.dataset.text;
  line1?.classList.add("done");
  line2?.classList.add("done");
  document.getElementById("landing-typewriter")?.classList.add("intro-complete");
  landing?.classList.add("intro-complete");
  document.getElementById("landing-cta-row")?.classList.add("visible");
  document.getElementById("landing-feature-chips")?.classList.add("visible");
  landingIntroComplete = true;
}

function typeText(el, text, speedMs, onDone) {
  if (!el || !text) {
    onDone?.();
    return;
  }
  el.textContent = "";
  let i = 0;
  const step = () => {
    if (i < text.length) {
      el.textContent += text.charAt(i);
      i += 1;
      setTimeout(step, speedMs);
    } else {
      onDone?.();
    }
  };
  step();
}

function initLandingIntro() {
  if (landingIntroRunning || landingIntroComplete) return;
  landingIntroRunning = true;

  const line1Text = document.querySelector("#landing-type-line-1 .arena-type-text");
  const line2Text = document.querySelector("#landing-type-line-2 .arena-type-text");
  const line1 = document.getElementById("landing-type-line-1");
  const line2 = document.getElementById("landing-type-line-2");

  if (!line1Text || !line2Text) {
    landingIntroRunning = false;
    return;
  }

  if (prefersReducedMotion()) {
    finalizeLandingIntroStatic();
    landingIntroRunning = false;
    return;
  }

  const text1 = line1Text.dataset.text || "";
  const text2 = line2Text.dataset.text || "";

  typeText(line1Text, text1, 32, () => {
    line1?.classList.add("done");
    line2?.classList.add("active");
    setTimeout(() => {
      typeText(line2Text, text2, 28, () => {
        line2?.classList.add("done");
        setTimeout(() => {
          finalizeLandingIntroStatic();
          landingIntroRunning = false;
        }, 180);
      });
    }, 220);
  });
}

function setGlobalLoading(isLoading, message = "Loading...") {
  if (loadingText) loadingText.textContent = message;
  loadingOverlay.hidden = !isLoading;
}

const NEMOTRON_SCORECARD_SOURCES = new Set(["nemotron_full", "nemotron", "nemotron_repaired"]);

function isNemotronScorecardSource(src) {
  return NEMOTRON_SCORECARD_SOURCES.has(String(src ?? "").trim());
}

const INTERNAL_ERROR_PATTERNS = [
  /nvidia/i,
  /max_tokens/i,
  /reasoning model/i,
  /empty response/i,
  /mock fallback/i,
  /model scoring fallback/i,
  /local fallback/i,
  /server logs/i,
  /nemotron omni/i,
  /api_key/i,
];

function isInternalErrorMessage(message) {
  const text = String(message ?? "").trim();
  if (!text) return true;
  return INTERNAL_ERROR_PATTERNS.some((pattern) => pattern.test(text));
}

function showErrorBanner(message) {
  if (isInternalErrorMessage(message)) {
    console.warn("[PitchFight] suppressed internal error from UI:", message);
    return;
  }
  errorBanner.textContent = message;
  errorBanner.hidden = false;
}

function hideErrorBanner() {
  errorBanner.hidden = true;
  errorBanner.textContent = "";
}

const BRIEF_FIELD_KEYS = [
  "name", "target_users", "problem", "solution", "why_ai", "traction", "competitors", "ask",
];

function setBriefFieldValue(key, value) {
  const card = briefPreviewForm?.querySelector(`[data-field="${key}"]`);
  if (!card) return;
  const display = card.querySelector(".brief-read-value");
  const input = card.querySelector(".brief-read-input");
  const text = String(value ?? "").trim();
  if (input) input.value = text;
  if (display) {
    display.textContent = text || "Not specified";
    display.classList.toggle("is-empty", !text);
  }
}

let _briefEditSnapshot = "";

function closeBriefFieldExpanded(card) {
  if (!card) return;
  const input = card.querySelector(".brief-read-input");
  const display = card.querySelector(".brief-read-value");
  card.classList.remove("is-editing", "is-editing-expanded");
  if (input) input.hidden = true;
  if (display) display.hidden = false;
  briefPreviewForm?.classList.remove("is-editing-active");
  briefPreviewPanel?.classList.remove("is-editing-active");
}

function commitBriefFieldEdit(card) {
  if (!card) return;
  const input = card.querySelector(".brief-read-input");
  const display = card.querySelector(".brief-read-value");
  const text = (input?.value || "").trim();
  if (display) {
    display.textContent = text || "Not specified";
    display.classList.toggle("is-empty", !text);
  }
  closeBriefFieldExpanded(card);
  syncBriefToStartupForm();
}

function cancelBriefFieldEdit(card) {
  if (!card) return;
  const input = card.querySelector(".brief-read-input");
  if (input) input.value = _briefEditSnapshot;
  closeBriefFieldExpanded(card);
}

function startBriefFieldEdit(card) {
  if (!card) return;

  briefPreviewForm?.querySelectorAll(".brief-read-card.is-editing-expanded").forEach((open) => {
    if (open !== card) cancelBriefFieldEdit(open);
  });

  const input = card.querySelector(".brief-read-input");
  const display = card.querySelector(".brief-read-value");
  _briefEditSnapshot = input?.value ?? "";

  card.classList.add("is-editing", "is-editing-expanded");
  briefPreviewForm?.classList.add("is-editing-active");
  briefPreviewPanel?.classList.add("is-editing-active");

  if (display) display.hidden = true;
  if (input) {
    input.hidden = false;
    if (input.classList.contains("brief-read-textarea")) {
      input.rows = 5;
    }
    requestAnimationFrame(() => {
      input.focus();
      if (typeof input.select === "function" && input.tagName === "INPUT") {
        input.select();
      } else if (input.tagName === "TEXTAREA") {
        input.setSelectionRange(input.value.length, input.value.length);
      }
      card.scrollIntoView({ behavior: "smooth", block: "center" });
    });
  }
}

function initBriefPreviewEditors() {
  briefPreviewForm?.querySelectorAll(".brief-read-card").forEach((card) => {
    if (!card.querySelector(".brief-read-edit-actions")) {
      const actions = document.createElement("div");
      actions.className = "brief-read-edit-actions";
      actions.innerHTML = `
        <button type="button" class="btn btn-ghost btn-sm brief-read-cancel">Cancel</button>
        <button type="button" class="btn btn-primary btn-sm brief-read-done">Done</button>
      `;
      card.appendChild(actions);
    }

    card.querySelector(".brief-read-edit")?.addEventListener("click", (e) => {
      e.stopPropagation();
      if (card.classList.contains("is-editing-expanded")) {
        commitBriefFieldEdit(card);
      } else {
        startBriefFieldEdit(card);
      }
    });
    card.querySelector(".brief-read-done")?.addEventListener("mousedown", (e) => e.preventDefault());
    card.querySelector(".brief-read-done")?.addEventListener("click", (e) => {
      e.stopPropagation();
      commitBriefFieldEdit(card);
    });
    card.querySelector(".brief-read-cancel")?.addEventListener("mousedown", (e) => e.preventDefault());
    card.querySelector(".brief-read-cancel")?.addEventListener("click", (e) => {
      e.stopPropagation();
      cancelBriefFieldEdit(card);
    });
    card.querySelector(".brief-read-input")?.addEventListener("keydown", (e) => {
      if (e.key === "Escape") {
        e.preventDefault();
        cancelBriefFieldEdit(card);
      }
      if (e.key === "Enter" && e.ctrlKey) {
        e.preventDefault();
        commitBriefFieldEdit(card);
      }
    });
  });
}

function syncBriefToStartupForm() {
  if (!briefPreviewForm || !startupForm) return;
  BRIEF_FIELD_KEYS.forEach((key) => {
    const input = briefPreviewForm.querySelector(`[name="${key}"]`);
    const field = startupForm.elements.namedItem(key);
    if (field && input) field.value = input.value ?? "";
  });
}

function getStartupPayload() {
  if (briefPreviewPanel && !briefPreviewPanel.hidden) {
    syncBriefToStartupForm();
  }
  const data = new FormData(startupForm);
  return Object.fromEntries(data.entries());
}

function fillStartupForm(startup) {
  Object.entries(startup).forEach(([key, value]) => {
    const field = startupForm?.elements.namedItem(key);
    if (field) field.value = value ?? "";
    if (BRIEF_FIELD_KEYS.includes(key)) setBriefFieldValue(key, value);
  });
}

function setBriefingMode(mode) {
  state.briefingMode = mode;
  const isQuick = mode === "quick";
  const previewVisible = state.briefStructured;

  document.getElementById("tab-quick-pitch")?.classList.toggle("active", isQuick);
  document.getElementById("tab-advanced-briefing")?.classList.toggle("active", !isQuick);
  document.getElementById("tab-quick-pitch")?.setAttribute("aria-selected", String(isQuick));
  document.getElementById("tab-advanced-briefing")?.setAttribute("aria-selected", String(!isQuick));
  briefingLeftCol?.classList.toggle("mode-quick", isQuick);
  briefingLeftCol?.classList.toggle("mode-advanced", !isQuick);

  const advancedPanel = document.getElementById("panel-advanced-briefing");
  if (advancedPanel) advancedPanel.hidden = isQuick;

  if (isQuick) {
    if (quickPitchPanel) quickPitchPanel.hidden = previewVisible;
    if (briefPreviewPanel) briefPreviewPanel.hidden = !previewVisible;
  } else {
    if (quickPitchPanel) quickPitchPanel.hidden = true;
    if (briefPreviewPanel) briefPreviewPanel.hidden = true;
    syncBriefToStartupForm();
  }

  const subtitle = document.getElementById("briefing-subtitle");
  if (subtitle) {
    subtitle.textContent = isQuick
      ? "Pitch naturally. We'll structure it before the judge attacks it."
      : "Want full control? Edit every field manually.";
  }
}

function showBriefPreview(meta = {}) {
  if (quickPitchPanel) quickPitchPanel.hidden = true;
  if (briefPreviewPanel) briefPreviewPanel.hidden = false;
  const advancedPanel = document.getElementById("panel-advanced-briefing");
  if (advancedPanel) advancedPanel.hidden = true;

  const confEl = document.getElementById("brief-preview-confidence");
  if (confEl) {
    const conf = meta.confidence || "medium";
    confEl.textContent = `Confidence: ${String(conf).toUpperCase()}`;
    confEl.className = `brief-confidence-chip confidence-${conf}`;
  }

  const hintEl = document.getElementById("brief-preview-hint");
  if (hintEl) {
    if (meta.source === "local_fallback") {
      hintEl.textContent = "Quick structure applied — tap ✎ on any field to edit.";
      hintEl.hidden = false;
    } else if (Array.isArray(meta.missing_fields) && meta.missing_fields.length) {
      hintEl.textContent = `Not in your pitch: ${meta.missing_fields.join(", ")}`;
      hintEl.hidden = false;
    } else {
      hintEl.hidden = true;
      hintEl.textContent = "";
    }
  }
}

function hideBriefPreview() {
  state.briefStructured = false;
  if (quickPitchPanel) quickPitchPanel.hidden = false;
  if (briefPreviewPanel) briefPreviewPanel.hidden = true;
  document.getElementById("structure-pitch-hint")?.setAttribute("hidden", "");
  document.getElementById("brief-preview-hint")?.setAttribute("hidden", "");
  briefPreviewForm?.querySelectorAll(".brief-read-card.is-editing").forEach((card) => {
    commitBriefFieldEdit(card);
  });
}

function extractionConfidenceLevel(meta = {}) {
  const raw = meta.confidence ?? meta.extraction_confidence ?? "";
  const key = String(raw).toLowerCase();
  if (key === "high" || key === "medium" || key === "low") return key;
  return null;
}

function confidenceFromStartupFields(startup = {}) {
  const fields = ["name", "problem", "solution", "why_ai", "target_users", "traction", "competitors", "ask"];
  const filled = fields.filter((field) => String(startup?.[field] ?? "").trim()).length;
  if (filled >= 5) return "high";
  if (filled >= 3) return "medium";
  return "low";
}

function confidenceLevelToPct(level) {
  const key = String(level || "medium").toLowerCase();
  if (key === "high") return 76;
  if (key === "low") return 22;
  return 50;
}

function syncPitchExtractionConfidence(meta = {}, startup = null) {
  const level = extractionConfidenceLevel(meta) || confidenceFromStartupFields(startup) || "medium";
  state.pitchExtractionConfidence = level;
  return level;
}

function fillBriefPreview(startup, meta = {}) {
  state.briefStructured = true;
  syncPitchExtractionConfidence(meta, startup);
  fillStartupForm(startup);
  showBriefPreview(meta);
}

function resetSetupScreen() {
  state.briefStructured = false;
  state.pitchExtractionConfidence = null;
  setBriefingMode("quick");
  hideBriefPreview();
  const quickText = document.getElementById("quick-pitch-text");
  if (quickText) quickText.value = "";
  state.pendingVoicePitch = null;
  state.startMode = "text";
}

async function structurePitch() {
  const pitchText = document.getElementById("quick-pitch-text")?.value?.trim();
  if (!pitchText) {
    showErrorBanner("Type or paste your pitch first.");
    return;
  }
  try {
    setGlobalLoading(true, "Structuring your pitch…");
    state.startMode = "text";
    const data = await apiPost("/api/structure-pitch", { pitch_text: pitchText });
    if (!data.ok) {
      showErrorBanner(data.error || "Could not structure your pitch. Try Advanced Briefing.");
      return;
    }
    fillBriefPreview(data.startup_context, data);
    hideErrorBanner();
  } catch (error) {
    console.error(error);
    showErrorBanner("We couldn't structure that pitch. Try Advanced Briefing or edit manually.");
  } finally {
    setGlobalLoading(false);
  }
}

function applyVoicePitchToBriefing(data) {
  state.pendingVoicePitch = data;
  state.startMode = "voice";
  const extracted = data.extracted ?? {};
  fillBriefPreview(extracted, {
    brief_summary: (data.transcript || "").slice(0, 240),
    confidence: data.extraction_confidence || "medium",
  });
  const quickText = document.getElementById("quick-pitch-text");
  if (quickText && data.transcript) quickText.value = data.transcript;
  setBriefingMode("quick");
}

const PERSONA_LABELS = {
  skeptical_vc: "Skeptical VC",
  technical_judge: "Technical Judge",
  hackathon_judge: "Hackathon Judge",
};

const DIFFICULTY_LABELS = {
  practice: "Practice Mode",
  judge: "Judge Mode",
  investor: "Investor Mode",
};

function pressureMeterLevel(data) {
  const label = String(data.pressure_label ?? data.pressure_level ?? "").toLowerCase();
  if (label.includes("extreme")) return { pct: 100, tier: "extreme" };
  if (label.includes("high")) return { pct: 78, tier: "high" };
  if (label.includes("focused") || label.includes("medium")) return { pct: 52, tier: "focused" };
  if (label.includes("warm")) return { pct: 28, tier: "warmup" };
  const phase = String(data.battle_phase ?? "").toLowerCase();
  if (phase.includes("extreme") || phase.includes("pressure")) return { pct: 78, tier: "high" };
  if (phase.includes("challenge")) return { pct: 52, tier: "focused" };
  const round = Number(data.round ?? state.round ?? 1);
  if (round >= 4) return { pct: 100, tier: "extreme" };
  if (round === 3) return { pct: 78, tier: "high" };
  if (round === 2) return { pct: 52, tier: "focused" };
  return { pct: 28, tier: "warmup" };
}

const ATTACK_PROGRESSION = [
  "User Pain",
  "Novelty",
  "MVP Strength",
  "Business Model",
  "Objection Handling",
];

function normalizeAttackKey(tag) {
  return String(tag || "").trim().toLowerCase();
}

function updateProgressStrip(round, attack, mode = "battle") {
  const roundStrip = document.getElementById(
    mode === "deal" ? "deal-progress-rounds" : "battle-progress-rounds",
  );
  if (roundStrip) {
    roundStrip.querySelectorAll(".progress-node").forEach((node) => {
      const n = Number(node.dataset.round);
      node.classList.remove("progress-node-active", "progress-node-done");
      if (n < round) node.classList.add("progress-node-done");
      else if (n === round) node.classList.add("progress-node-active");
    });
  }

  if (mode !== "battle") return;
  const attackStrip = document.getElementById("battle-progress-attacks");
  if (!attackStrip) return;
  const key = normalizeAttackKey(attack);
  let activeIdx = ATTACK_PROGRESSION.findIndex((a) => {
    const ak = normalizeAttackKey(a);
    return key === ak || key.includes(ak.split(" ")[0]) || ak.includes(key);
  });
  if (activeIdx < 0 && key) activeIdx = Math.min(round - 1, ATTACK_PROGRESSION.length - 1);

  attackStrip.querySelectorAll(".progress-attack-tag").forEach((tag, idx) => {
    tag.classList.remove("progress-attack-active", "progress-attack-done");
    if (activeIdx >= 0 && idx < activeIdx) tag.classList.add("progress-attack-done");
    if (activeIdx >= 0 && idx === activeIdx) tag.classList.add("progress-attack-active");
  });
}

function addBattleLogEntry(roundNum, judge, founderReply, mode = "battle") {
  const log = mode === "deal" ? state.dealBattleLog : state.battleLog;
  const entry = { roundNum, judge: { ...judge }, founderReply };
  log.push(entry);

  const ribbonId = mode === "deal" ? "deal-log-ribbon" : "battle-log-ribbon";
  const tabsId = mode === "deal" ? "deal-log-tabs" : "battle-log-tabs";
  const detailId = mode === "deal" ? "deal-log-detail" : "battle-log-detail";
  const ribbon = document.getElementById(ribbonId);
  const tabs = document.getElementById(tabsId);
  if (!ribbon || !tabs) return;
  /* Ribbon stays hidden — log only opens via drawer */

  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "battle-log-tab";
  btn.textContent = mode === "deal" ? `D${roundNum}` : `R${roundNum}`;
  btn.dataset.round = roundNum;
  btn.addEventListener("click", () => {
    tabs.querySelectorAll(".battle-log-tab").forEach((t) => t.classList.remove("active"));
    btn.classList.add("active");
    const detail = document.getElementById(detailId);
    if (!detail) return;
    detail.hidden = false;
    detail.innerHTML = `
      <p class="log-detail-attack">${escapeHtml(simplifyJudgeMeta(judge.meta) || "—")}</p>
      <p class="log-detail-label">Judge</p>
      <p class="log-detail-text">${escapeHtml(judge.text)}</p>
      ${founderReply ? `<p class="log-detail-label">You</p><p class="log-detail-text">${escapeHtml(founderReply)}</p>` : ""}`;
  });
  tabs.appendChild(btn);
}

function updateJudgeAttackPill(attack, mode = "battle") {
  const pill = document.getElementById(mode === "deal" ? "deal-judge-attack-pill" : "judge-attack-pill");
  if (pill) pill.textContent = attack && attack !== "—" ? attack : "Pressing";
}

function simplifyJudgeMeta(meta) {
  if (!meta) return "";
  const attack = String(meta).split("·")[0]?.trim();
  return attack || meta;
}

function updatePressureCore(tier, label) {
  const ring = document.querySelector(".duel-node-ring");
  if (ring) {
    ring.className = `duel-node-ring pressure-core-${tier}`;
  }
  const lbl = document.getElementById("duel-pressure-label");
  if (lbl && label) lbl.textContent = label;
  const judgePressure = document.getElementById("judge-stat-pressure");
  if (judgePressure && label) judgePressure.textContent = label;
}

function renderConfidenceMeter(confidencePct) {
  const fill = document.getElementById("confidence-meter-fill");
  if (!fill) return;
  const confidence = Math.max(8, Math.min(92, Math.round(confidencePct)));
  fill.style.width = `${confidence}%`;
  fill.classList.toggle("confidence-low", confidence < 35);
  fill.classList.toggle("confidence-mid", confidence >= 35 && confidence < 65);
  fill.classList.toggle("confidence-high", confidence >= 65);
}

function refreshBattleConfidenceFromPressure(pressurePct, round = 1) {
  const base = confidenceLevelToPct(state.pitchExtractionConfidence || "medium");
  const pressureDrag = Math.round(Number(pressurePct) * 0.25);
  const roundDrag = Math.max(0, Number(round) - 1) * 2;
  const ceiling = Math.max(8, base - pressureDrag - roundDrag);
  if (state.battleConfidencePct == null) {
    state.battleConfidencePct = ceiling;
  } else {
    state.battleConfidencePct = Math.min(state.battleConfidencePct, ceiling);
  }
  renderConfidenceMeter(state.battleConfidencePct);
}

function adjustBattleConfidenceFromAnswer(quality) {
  const deltas = { strong: 8, partial: -2, weak: -12, non_answer: -20 };
  const delta = deltas[String(quality || "").toLowerCase()] ?? 0;
  if (!delta) return;
  state.battleConfidencePct = Math.max(
    8,
    Math.min(92, (state.battleConfidencePct ?? confidenceLevelToPct(state.pitchExtractionConfidence)) + delta),
  );
  renderConfidenceMeter(state.battleConfidencePct);
}

function updateComboMeter(round) {
  const meter = document.getElementById("combo-meter");
  if (!meter) return;
  const streak = Math.max(0, Math.min(5, Number(round) - 1));
  meter.querySelectorAll(".combo-pip").forEach((pip) => {
    const n = Number(pip.dataset.pip);
    pip.classList.toggle("combo-pip-lit", n <= streak);
  });
}

function updateJudgeSignalChips(attack, pressureLabel) {
  const focus = document.getElementById("judge-stat-focus");
  if (focus) focus.textContent = attack && attack !== "—" ? attack : "Scanning";
  const pressure = document.getElementById("judge-stat-pressure");
  if (pressure && pressureLabel) pressure.textContent = pressureLabel;
  const judgeName = document.getElementById("judge-fighter-name");
  const sidebarName = document.getElementById("sidebar-persona-name");
  const persona = PERSONA_LABELS[state.persona] ?? "AI Judge";
  if (judgeName) judgeName.textContent = persona;
  if (sidebarName) sidebarName.textContent = persona;
}

function updateJudgeLiveCard(text, meta) {
  const q = document.getElementById("judge-question-text");
  const metaEl = document.getElementById("judge-question-meta");
  const card = document.getElementById("judge-live-card");
  const attack = simplifyJudgeMeta(meta);
  if (q) q.textContent = text || "AI judge is preparing the next attack…";
  if (metaEl) metaEl.textContent = attack;
  updateJudgeAttackPill(attack, "battle");
  const pressureLbl = document.getElementById("judge-stat-pressure")?.textContent;
  updateJudgeSignalChips(attack !== "—" ? attack : simplifyJudgeMeta(meta), pressureLbl);
  if (card) {
    card.classList.remove("judge-attack-enter");
    void card.offsetWidth;
    card.classList.add("judge-attack-enter");
  }
}

function updateDealJudgeCard(text, meta) {
  const q = document.getElementById("deal-judge-text");
  const metaEl = document.getElementById("deal-judge-meta");
  const card = document.getElementById("deal-judge-card");
  if (q) q.textContent = text || "Preparing deal terms…";
  if (metaEl) metaEl.textContent = simplifyJudgeMeta(meta);
  const attack = simplifyJudgeMeta(meta);
  updateJudgeAttackPill(attack !== "—" ? attack : "Terms", "deal");
  if (card) {
    card.classList.remove("judge-attack-enter");
    void card.offsetWidth;
    card.classList.add("judge-attack-enter");
  }
}

function refreshCoachBar() {
  const dockHint = document.getElementById("dock-assist-hint");
  const coach = (document.getElementById("micro-coach")?.textContent || "").trim();
  const hintRaw = (document.getElementById("answer-hint")?.textContent || "").trim();

  if (dockHint) {
    if (coach) {
      dockHint.textContent = coach;
    } else if (hintRaw) {
      dockHint.textContent = `Tip: ${hintRaw}`;
    } else {
      dockHint.textContent = "Tip: use numbers";
    }
  }

  const bar = document.getElementById("battle-coach-bar");
  if (bar) {
    bar.hidden = true;
    bar.textContent = "";
  }
}

function extractRoundFromMeta(meta) {
  const match = String(meta || "").match(/Round\s+(\d+)/i);
  return match ? match[1] : null;
}

function archiveBattleRound(_container, judge, founderReply, mode = "battle") {
  if (!judge.text) return;
  const roundNum = extractRoundFromMeta(judge.meta) ?? Math.max(1, (state.round || 1) - 1);
  addBattleLogEntry(roundNum, judge, founderReply, mode);
  updateTimelineVisibility(mode, mode === "deal" ? "deal-timeline-count" : "timeline-count");
}

function updateTimelineVisibility(mode = "battle", countId) {
  const count = mode === "deal"
    ? (state.dealBattleLog?.length ?? 0)
    : (state.battleLog?.length ?? 0);
  const countEl = document.getElementById(countId);
  if (countEl) countEl.textContent = count ? `(${count})` : "";
  const toggleId = mode === "deal" ? "btn-open-deal-rounds" : "btn-open-battle-rounds";
  const toggle = document.getElementById(toggleId);
  if (toggle) toggle.hidden = count === 0;
}

const CONV_FOUNDER_AVATAR = `<svg class="conv-avatar-svg conv-avatar-founder" viewBox="0 0 64 88" aria-hidden="true"><circle cx="32" cy="24" r="11" fill="#3d2810" stroke="#c084fc" stroke-width="1"/><path d="M18 38 Q32 30 46 38 L48 62 Q32 68 16 62 Z" fill="#1a1208" stroke="#c084fc" stroke-width="1"/></svg>`;
const CONV_JUDGE_AVATAR = `<svg class="conv-avatar-svg conv-avatar-judge" viewBox="0 0 64 88" aria-hidden="true"><rect x="20" y="18" width="24" height="20" rx="4" fill="#060a10" stroke="#22d3ee" stroke-width="1"/><path d="M16 40 Q32 32 48 40 L50 64 Q32 70 14 64 Z" fill="#0a1420" stroke="#22d3ee" stroke-width="1"/></svg>`;

function renderConversationMessage(role, text, meta = "") {
  const isJudge = role === "ai";
  const speaker = isJudge ? (PERSONA_LABELS[state.persona] ?? "AI Judge") : "You · Founder";
  const row = document.createElement("div");
  row.className = `conv-message ${isJudge ? "conv-message-judge" : "conv-message-founder"}`;
  row.innerHTML = `
    <div class="conv-avatar ${isJudge ? "conv-avatar-judge-wrap" : "conv-avatar-founder-wrap"}">
      ${isJudge ? CONV_JUDGE_AVATAR : CONV_FOUNDER_AVATAR}
    </div>
    <div class="conv-bubble">
      <div class="conv-bubble-head">
        <span class="conv-speaker">${escapeHtml(speaker)}</span>
        ${meta ? `<span class="conv-meta">${escapeHtml(meta)}</span>` : ""}
      </div>
      <p class="conv-text">${escapeHtml(text)}</p>
    </div>`;
  return row;
}

function renderConversationThread(log, container) {
  if (!container) return;
  container.innerHTML = "";
  (log || []).forEach(({ role, text, meta }) => {
    container.appendChild(renderConversationMessage(role, text, meta));
  });
  container.scrollTop = container.scrollHeight;
}

function renderConversationSidebar(context = "battle") {
  const sidebar = document.getElementById("conversation-sidebar");
  if (!sidebar) return;

  const meta = state.battleMetaSnapshot ?? {};
  const score = state.scorecardSnapshot;
  const persona = PERSONA_LABELS[meta.persona ?? state.persona] ?? "AI Judge";
  const rounds = state.battleLog?.length ?? Math.max(0, Math.floor((state.conversationLog?.length ?? 0) / 2));
  const attacks = ATTACK_PROGRESSION.map((label) => {
    const done = state.battleLog?.some((e) => simplifyJudgeMeta(e.judge?.meta) === label);
    const active = meta.attack === label;
    return `<li class="${done ? "sidebar-attack-done" : ""} ${active ? "sidebar-attack-active" : ""}">${escapeHtml(label)}</li>`;
  }).join("");

  sidebar.innerHTML = `
    <p class="sidebar-eyebrow hud-font">Battle Details</p>
    <dl class="sidebar-stats">
      <div><dt>Rounds</dt><dd>${rounds || meta.round || "—"}</dd></div>
      <div><dt>Opponent</dt><dd>${escapeHtml(persona)}</dd></div>
      <div><dt>Mode</dt><dd>${escapeHtml(meta.mode ?? "Practice")}</dd></div>
      <div><dt>Last Attack</dt><dd>${escapeHtml(meta.attack ?? "—")}</dd></div>
      <div><dt>Pressure</dt><dd>${escapeHtml(meta.pressure ?? "—")}</dd></div>
    </dl>
    ${context === "scorecard" && score ? `
      <p class="sidebar-eyebrow hud-font sidebar-eyebrow-score">Scorecard</p>
      <dl class="sidebar-stats sidebar-score-block">
        <div><dt>Score</dt><dd class="sidebar-score-val">${score.overall ?? "—"}</dd></div>
        <div><dt>Label</dt><dd>${escapeHtml(score.overallLabel ?? "—")}</dd></div>
        <div><dt>Strongest</dt><dd class="sidebar-strong">${escapeHtml(score.strongest ?? "—")}</dd></div>
        <div><dt>Weakest</dt><dd class="sidebar-weak">${escapeHtml(score.weakest ?? "—")}</dd></div>
      </dl>` : ""}
    <p class="sidebar-eyebrow hud-font">Attack Progression</p>
    <ul class="sidebar-attack-list">${attacks}</ul>`;
}

function openBattleConversationLog(fromScorecard = false) {
  renderConversationSidebar(fromScorecard ? "scorecard" : "battle");
  renderConversationThread(state.conversationLog, chatWindow);
  openRoundsDrawer("battle-rounds-drawer");
  document.getElementById("conversation-sidebar")?.scrollTo(0, 0);
  chatWindow?.scrollTo(0, chatWindow.scrollHeight);
}

function openRoundsDrawer(drawerId) {
  const drawer = document.getElementById(drawerId);
  if (!drawer) return;
  drawer.hidden = false;
  document.body.classList.add("rounds-drawer-open");
}

function closeRoundsDrawer(drawerId) {
  const drawer = document.getElementById(drawerId);
  if (!drawer) return;
  drawer.hidden = true;
  if (!document.querySelector(".previous-rounds-drawer:not([hidden])")) {
    document.body.classList.remove("rounds-drawer-open");
  }
}

function appendFounderBubble(container, text, meta = "", extraClass = "") {
  const bubble = document.createElement("div");
  bubble.className = `message message-founder user${extraClass ? ` ${extraClass}` : ""}`;
  const preview = text.length > 160 ? `${text.slice(0, 157)}…` : text;
  bubble.innerHTML = meta
    ? `<span class="message-meta">${escapeHtml(meta)}</span><p class="message-preview">${escapeHtml(preview)}</p>`
    : `<p class="message-preview">${escapeHtml(preview)}</p>`;
  bubble.title = text;
  container.appendChild(bubble);
  container.scrollTop = container.scrollHeight;
}

function rebuildConversationView() {
  openBattleConversationLog(true);
}

function resetLiveTurnTracking() {
  liveJudgeTurn = { text: "", meta: "" };
  liveFounderReply = "";
  liveDealJudgeTurn = { text: "", meta: "" };
  liveDealFounderReply = "";
}

function appendMessage(role, text, meta = "") {
  state.conversationLog.push({ role, text, meta });

  if (role === "ai") {
    if (liveJudgeTurn.text) {
      archiveBattleRound(null, liveJudgeTurn, liveFounderReply, "battle");
      liveFounderReply = "";
    }
    liveJudgeTurn = { text, meta };
    updateJudgeLiveCard(text, meta);
    updateTimelineVisibility("battle", "timeline-count");
    return;
  }

  liveFounderReply = text;
  updateTimelineVisibility("battle", "timeline-count");
}

function appendDealMessage(role, text, meta = "") {
  if (!dealChatWindow) return;
  state.dealConversationLog.push({ role, text, meta });

  if (role === "ai") {
    dealChatWindow?.querySelector(".live-pending")?.remove();
    if (liveDealJudgeTurn.text) {
      archiveBattleRound(null, liveDealJudgeTurn, liveDealFounderReply, "deal");
      liveDealFounderReply = "";
    }
    liveDealJudgeTurn = { text, meta };
    updateDealJudgeCard(text, meta);
    updateTimelineVisibility("deal", "deal-timeline-count");
    return;
  }

  liveDealFounderReply = text;
  dealChatWindow?.querySelector(".live-pending")?.remove();
  updateTimelineVisibility("deal", "deal-timeline-count");
}

// "Minimum viable answer" recipe shown above the input for the current question.
function setAnswerHint(hint) {
  const el = document.getElementById("answer-hint");
  if (!el) return;
  el.textContent = (hint || "").trim();
  el.hidden = true;
  refreshCoachBar();
}

// Gentle after-round nudge — shown only in the response dock hint line.
function setMicroCoach(tip) {
  const el = document.getElementById("micro-coach");
  if (!el) return;
  el.textContent = (tip || "").trim();
  el.hidden = true;
  refreshCoachBar();
}

function escapeHtml(text) {
  return String(text)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

function updateBattleMeta(data) {
  const round = data.round ?? state.round ?? 1;
  document.getElementById("round-counter").textContent = round;
  const roundDisplay = document.getElementById("round-display");
  if (roundDisplay) roundDisplay.textContent = String(round).padStart(2, "0");
  const roundDuel = document.getElementById("round-counter-duel");
  if (roundDuel) roundDuel.textContent = String(round).padStart(2, "0");
  state.round = round;

  const pressureDisplay = data.pressure_label ?? data.pressure_level ?? "Warm-up";
  const pressureEl = document.getElementById("pressure-level");
  if (pressureEl) {
    pressureEl.textContent = pressureDisplay;
    const { tier } = pressureMeterLevel(data);
    pressureEl.className = `pressure-${tier}`;
  }

  const { pct, tier } = pressureMeterLevel(data);
  const fill = document.getElementById("pressure-meter-fill");
  if (fill) {
    fill.style.width = `${pct}%`;
    fill.className = `pressure-meter-fill pressure-${tier}`;
  }
  refreshBattleConfidenceFromPressure(pct, round);
  updateComboMeter(round);
  const progressFill = document.getElementById("battle-progress-fill");
  if (progressFill) {
    progressFill.style.width = `${pct}%`;
    progressFill.className = `battle-progress-fill pressure-${tier}`;
  }

  const attack = data.attack_tag ?? "—";
  document.getElementById("attack-tag").textContent = attack;
  const attackChip = document.getElementById("attack-tag-chip");
  if (attackChip) attackChip.textContent = attack;

  const pressureChip = document.getElementById("pressure-chip");
  if (pressureChip) pressureChip.textContent = pressureDisplay;

  const diffLabel = data.difficulty_label ?? "Practice Mode";
  const diffLabelEl = document.getElementById("difficulty-label");
  if (diffLabelEl) diffLabelEl.textContent = diffLabel;

  const modeChip = document.getElementById("mode-chip");
  if (modeChip) modeChip.textContent = diffLabel.replace(" Mode", "");

  const phaseEl = document.getElementById("battle-phase");
  if (phaseEl && data.battle_phase) phaseEl.textContent = data.battle_phase;

  const sidebarMode = document.getElementById("sidebar-persona-mode");
  if (sidebarMode) sidebarMode.textContent = diffLabel;

  const sidebarPersona = document.getElementById("sidebar-persona-name");
  if (sidebarPersona) {
    sidebarPersona.textContent = PERSONA_LABELS[state.persona] ?? "AI Judge";
  }

  updateProgressStrip(round, attack, "battle");
  updateJudgeAttackPill(attack, "battle");
  updatePressureCore(tier, pressureDisplay);
  updateJudgeSignalChips(attack, pressureDisplay);

  state.battleMetaSnapshot = {
    round,
    attack,
    pressure: pressureDisplay,
    mode: diffLabel.replace(" Mode", ""),
    persona: state.persona,
  };
}

function updateBattleReadiness(data) {
  const prompt = document.getElementById("battle-readiness-prompt");
  const text = document.getElementById("battle-readiness-text");
  if (!prompt) return;
  const show = data.soft_round_limit_reached || data.recommended_action === "end_battle";
  if (!show) {
    prompt.hidden = true;
    return;
  }
  if (text) {
    text.textContent = data.completion_message
      ?? data.readiness?.reason
      ?? "Enough signal collected. Ready for your scorecard?";
  }
  prompt.hidden = false;
}

function hideBattleReadiness() {
  document.getElementById("battle-readiness-prompt")?.setAttribute("hidden", "");
}

async function apiPost(path, body = undefined) {
  console.log(`API POST ${path}`, body ?? {});
  const options = { method: "POST", headers: {} };

  if (body !== undefined) {
    options.headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(body);
  }

  const response = await fetch(path, options);
  const data = await response.json().catch(() => ({}));

  if (!response.ok) {
    const detail = data.detail || data.error || response.statusText;
    throw new Error(`${path} failed: ${detail}`);
  }

  console.log(`API POST ${path} OK`, data);
  return data;
}

export async function loadSample() {
  try {
    setGlobalLoading(true, "Loading demo founder…");
    const data = await apiPost("/api/load-sample");
    state.startMode = "text";
    setBriefingMode("quick");
    fillBriefPreview(data.startup, {
      brief_summary: data.startup?.solution || data.startup?.problem || "Demo founder loaded.",
      confidence: "high",
    });
    const quickText = document.getElementById("quick-pitch-text");
    if (quickText) {
      quickText.value = [
        data.startup?.name,
        data.startup?.problem,
        data.startup?.solution,
        data.startup?.traction,
        data.startup?.ask,
      ].filter(Boolean).join(" ");
    }
    showScreen("setup");
    hideErrorBanner();
  } catch (error) {
    console.error(error);
    showErrorBanner("Failed to load demo startup. Check backend logs.");
  } finally {
    setGlobalLoading(false);
  }
}

export async function startSession() {
  try {
    setGlobalLoading(true, "AI judge is preparing the first attack…");
    battleStatus.hidden = true;
    hideBattleReadiness();
    chatWindow.innerHTML = "";
    state.conversationLog = [];
    state.battleLog = [];
    resetLiveTurnTracking();
    document.getElementById("battle-log-tabs") && (document.getElementById("battle-log-tabs").innerHTML = "");
    document.getElementById("battle-log-detail")?.setAttribute("hidden", "");
    document.getElementById("battle-log-ribbon")?.setAttribute("hidden", "");
    document.getElementById("btn-open-battle-rounds")?.setAttribute("hidden", "");
    document.getElementById("battle-rounds-drawer")?.setAttribute("hidden", "");
    document.getElementById("battle-coach-bar")?.setAttribute("hidden", "");
    document.getElementById("voice-turn-preview")?.setAttribute("hidden", "");

    if (!state.pitchExtractionConfidence) {
      syncPitchExtractionConfidence({}, getStartupPayload());
    }
    state.battleConfidencePct = null;

    const payload = {
      mode: "pitch_battle",
      startup: getStartupPayload(),
      persona: state.persona,
      difficulty_profile: state.difficultyProfile,
      difficulty: state.difficultyProfile,  // keep for backward compat
      input_mode: state.startMode === "voice" ? "voice" : "text",
      model_mode: "premium_nvidia",
    };

    if (state.startMode === "voice" && state.pendingVoicePitch) {
      payload.voice_pitch = {
        transcript: state.pendingVoicePitch.transcript,
        delivery_observations: state.pendingVoicePitch.delivery_observations,
        extraction_confidence: state.pendingVoicePitch.extraction_confidence,
      };
    }

    const data = await apiPost("/api/start-session", payload);

    if (data.error) {
      showErrorBanner(data.error);
      return;
    }

    state.sessionId = data.session_id;
    state.round = data.round ?? 1;
    state.uiMode = "pitch";
    userInput.disabled = false;
    const submitBtn = document.getElementById("chat-form").querySelector("button[type=submit]");
    if (submitBtn) submitBtn.disabled = false;
    updateBattleMeta(data);
    const startMeta = data.model_ok
      ? `${data.attack_tag} · Round ${data.round} · ⚡ Premium Nemotron`
      : `${data.attack_tag} · Round ${data.round}`;
    if (data.model_error) {
      console.warn("Opponent model fallback (not shown to user):", data.model_error);
    }
    appendMessage("ai", data.ai_message, startMeta);
    setMicroCoach("");
    setAnswerHint(data.answer_hint);
    showScreen("battle");
    hideErrorBanner();
  } catch (error) {
    console.error(error);
    showErrorBanner("Failed to start battle. Check backend logs.");
  } finally {
    setGlobalLoading(false);
  }
}

export async function sendMessage(messageOverride, voiceMeta = null) {
  const message = (messageOverride ?? userInput.value).trim();
  if (!message || !state.sessionId) return;

  try {
    setGlobalLoading(true, "Scoring your answer…");
    userInput.value = "";
    appendMessage("user", message);

    const chatPayload = {
      session_id: state.sessionId,
      user_message: message,
    };
    if (voiceMeta?.voice_turn_id) {
      chatPayload.input_mode = "voice";
      chatPayload.voice_turn_id = voiceMeta.voice_turn_id;
      if (voiceMeta.delivery_metadata) {
        chatPayload.delivery_metadata = voiceMeta.delivery_metadata;
      }
    }

    const data = await apiPost("/api/chat-round", chatPayload);

    if (data.error) {
      battleStatus.hidden = false;
      battleStatus.textContent = data.ai_message || data.error;
      return;
    }

    updateBattleMeta(data);
    if (data.answer_quality) {
      adjustBattleConfidenceFromAnswer(data.answer_quality);
    }
    const chatMeta = data.model_ok
      ? `${data.attack_tag} · Round ${data.round} · ⚡ Premium Nemotron`
      : `${data.attack_tag} · Round ${data.round}`;
    if (data.model_error) {
      console.warn("Opponent model fallback (not shown to user):", data.model_error);
    }
    appendMessage("ai", data.ai_message, chatMeta);
    setMicroCoach(data.micro_coach);
    setAnswerHint(data.answer_hint);

    if (data.soft_round_limit_reached) {
      updateBattleReadiness(data);
    } else {
      hideBattleReadiness();
    }

    state.pendingVoiceTurn = null;
    document.getElementById("voice-turn-preview")?.setAttribute("hidden", "");
  } catch (error) {
    console.error(error);
    battleStatus.hidden = false;
    battleStatus.textContent = "Message failed. Try again.";
  } finally {
    setGlobalLoading(false);
  }
}

export async function endBattle() {
  if (!state.sessionId) return;

  try {
    setGlobalLoading(true, "Building scorecard…");
    const data = await apiPost("/api/end-battle", {
      session_id: state.sessionId,
    });

    if (data.error) {
      showErrorBanner(data.error);
      return;
    }

    renderScorecard(data);
    showScreen("scorecard");
    hideErrorBanner();
  } catch (error) {
    console.error(error);
    showErrorBanner("Failed to generate scorecard. Check backend logs.");
  } finally {
    setGlobalLoading(false);
  }
}

export async function resetBattle() {
  if (state.sessionId) {
    try {
      await apiPost("/api/reset-session", { session_id: state.sessionId });
    } catch (error) {
      console.error(error);
    }
  }

  state.sessionId = null;
  state.round = 1;
  state.pendingVoicePitch = null;
  state.pendingVoiceTurn = null;
  state.retryDrill = null;
  state.pendingRetryVoiceTurn = null;
  state.judgeVerdict = null;
  state.dealContext = null;
  state.dealRound = 1;
  state.uiMode = "pitch";
  state.pendingDealVoiceTurn = null;
  state.startMode = "text";
  state.pitchExtractionConfidence = null;
  state.battleConfidencePct = null;
  state.conversationLog = [];
  state.dealConversationLog = [];
  state.battleLog = [];
  state.dealBattleLog = [];
  resetLiveTurnTracking();
  chatWindow.innerHTML = "";
  if (dealChatWindow) dealChatWindow.innerHTML = "";
  ["battle-log-tabs", "deal-log-tabs"].forEach((id) => {
    const el = document.getElementById(id);
    if (el) el.innerHTML = "";
  });
  document.getElementById("battle-log-ribbon")?.setAttribute("hidden", "");
  document.getElementById("deal-log-ribbon")?.setAttribute("hidden", "");
  document.getElementById("btn-open-battle-rounds")?.setAttribute("hidden", "");
  document.getElementById("battle-rounds-drawer")?.setAttribute("hidden", "");
  document.getElementById("btn-open-deal-rounds")?.setAttribute("hidden", "");
  document.getElementById("deal-rounds-drawer")?.setAttribute("hidden", "");
  document.getElementById("battle-coach-bar")?.setAttribute("hidden", "");
  hideBattleReadiness();
  updateJudgeLiveCard("", "");
  updateDealJudgeCard("", "");
  userInput.value = "";
  showScreen("landing");
}

function formatDimLabel(dim) {
  return String(dim ?? "").replaceAll("_", " ");
}

function scoreBand(score) {
  const s = Number(score) || 0;
  if (s >= 70) return "score-high";
  if (s >= 50) return "score-mid";
  return "score-low";
}

function getStrongestWeakest(scores) {
  const entries = Object.entries(scores || {}).filter(([, v]) => v && typeof v.score === "number");
  if (!entries.length) return { strongest: null, weakest: null };
  const sorted = [...entries].sort((a, b) => (b[1].score ?? 0) - (a[1].score ?? 0));
  return { strongest: sorted[0], weakest: sorted[sorted.length - 1] };
}

function attachShowMore(el) {
  if (!el || !el.textContent?.trim()) return;
  el.classList.add("clamp-text");
  if (el.nextElementSibling?.classList?.contains("show-more-btn")) return;
  requestAnimationFrame(() => {
    if (el.scrollHeight <= el.clientHeight + 2) return;
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "show-more-btn";
    btn.textContent = "Show more";
    btn.addEventListener("click", () => {
      const expanded = el.classList.toggle("expanded");
      btn.textContent = expanded ? "Show less" : "Show more";
    });
    el.insertAdjacentElement("afterend", btn);
  });
}

function buildDimensionRow(key, value, opts = {}) {
  const s = value?.score ?? 0;
  const band = scoreBand(s);
  const dimLabel = formatDimLabel(key);
  const labelSlug = String(value?.label || "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "");
  const reason = value?.reason ?? "";
  const layout = opts.layout ?? "default";

  if (layout === "scorecard") {
    const row = document.createElement("div");
    const fillSlug = labelSlug || "developing";
    let highlightClass = "";
    if (opts.weakestKey === key) highlightClass = " sc-dim-weakest";
    else if (opts.strongestKey === key) highlightClass = " sc-dim-strongest";
    row.className = `dimension-row score-row dimension-row-scorecard sc-dim-card ${band}${highlightClass}`;
    const flagHtml =
      opts.weakestKey === key
        ? `<span class="sc-dim-flag sc-dim-flag-weak">Weakest</span>`
        : opts.strongestKey === key
          ? `<span class="sc-dim-flag sc-dim-flag-strong">Strongest</span>`
          : "";
    const badgeHtml = value?.label
      ? `<span class="score-label dimension-badge score-label-${escapeHtml(labelSlug)}">${escapeHtml(value.label)}</span>`
      : "";
    row.innerHTML = `
      <div class="sc-dim-head">
        <div class="sc-dim-title">
          <span class="dimension-name">${dimLabel}</span>
          ${flagHtml}
        </div>
        <div class="sc-dim-meta">
          <strong class="dimension-score">${s}</strong>
          ${badgeHtml}
        </div>
      </div>
      <div class="dimension-bar bar-track"><div class="dimension-bar-fill bar-fill dim-fill-${escapeHtml(fillSlug)}" style="width:0%" data-width="${s}%"></div></div>
    `;
    requestAnimationFrame(() => {
      const fill = row.querySelector(".dimension-bar-fill");
      if (fill) fill.style.width = fill.dataset.width || `${s}%`;
    });
    return row;
  }

  const row = document.createElement("div");
  row.className = `dimension-row score-row ${band}`;
  const labelHtml = value?.label
    ? `<span class="score-label score-label-${escapeHtml(labelSlug)}">${escapeHtml(value.label)}</span>`
    : "";
  const quote = value?.quote && opts.showQuote
    ? `<span class="quote-chip">"${escapeHtml(value.quote)}"</span>`
    : "";
  row.innerHTML = `
    <div class="dimension-row-head score-row-head">
      <span class="dimension-name">${dimLabel}${labelHtml}</span>
      <strong class="dimension-score">${s}</strong>
    </div>
    <div class="dimension-bar bar-track"><div class="dimension-bar-fill bar-fill" style="width:0%" data-width="${s}%"></div></div>
    <p class="dimension-reason score-reason clamp-text">${escapeHtml(reason)}</p>
    ${quote}
  `;
  requestAnimationFrame(() => {
    const fill = row.querySelector(".dimension-bar-fill");
    if (fill) fill.style.width = fill.dataset.width || `${s}%`;
  });
  return row;
}

function initResultTabs(tabsRootId, panelsRootId) {
  const tabsRoot = document.getElementById(tabsRootId);
  const panelsRoot = document.getElementById(panelsRootId);
  if (!tabsRoot || !panelsRoot || tabsRoot.dataset.tabsInit === "1") return;
  tabsRoot.dataset.tabsInit = "1";

  const activate = (tabName) => {
    tabsRoot.querySelectorAll(".result-tab").forEach((tab) => {
      const active = tab.dataset.tab === tabName;
      tab.classList.toggle("active", active);
      tab.setAttribute("aria-selected", active ? "true" : "false");
    });
    panelsRoot.querySelectorAll(".result-panel").forEach((panel) => {
      const active = panel.dataset.panel === tabName;
      panel.classList.toggle("active", active);
      panel.hidden = !active;
    });
  };

  tabsRoot.addEventListener("click", (e) => {
    const tab = e.target.closest(".result-tab");
    if (!tab || tab.hidden) return;
    activate(tab.dataset.tab);
  });
}

function switchResultTab(tabsRootId, tabName) {
  const tabsRoot = document.getElementById(tabsRootId);
  const tab = tabsRoot?.querySelector(`.result-tab[data-tab="${tabName}"]`);
  tab?.click();
}

function initScorecardTabs() {
  const root = document.getElementById("scorecard-tabs");
  if (!root || root.dataset.init === "1") return;
  root.dataset.init = "1";
  root.addEventListener("click", (e) => {
    const tab = e.target.closest(".sc-tab");
    if (!tab) return;
    activateScorecardTab(tab.dataset.tab);
  });
}

function activateScorecardTab(tabName) {
  document.querySelectorAll("#scorecard-tabs .sc-tab").forEach((tab) => {
    const active = tab.dataset.tab === tabName;
    tab.classList.toggle("active", active);
    tab.setAttribute("aria-selected", active ? "true" : "false");
  });
  document.querySelectorAll(".sc-tab-panels .sc-tab-panel").forEach((panel) => {
    const active = panel.dataset.panel === tabName;
    panel.classList.toggle("active", active);
    panel.hidden = !active;
  });
}

function renderSignalsGroups(css) {
  const container = document.getElementById("signals-summary");
  const emptyEl = document.getElementById("signals-empty");
  if (!container) return false;

  const groups = [
    { key: "numbers", label: "Numbers" },
    { key: "validation", label: "Validation" },
    { key: "competitors", label: "Competitors" },
    { key: "revenue_signals", label: "Revenue" },
    { key: "technical_mechanisms", label: "Mechanisms" },
  ];

  container.innerHTML = "";
  let hasAny = false;

  groups.forEach(({ key, label }) => {
    const items = (css?.[key] ?? []).filter((s) => String(s).trim());
    if (!items.length) return;
    hasAny = true;
    const group = document.createElement("div");
    group.className = "sc-signal-group";
    const groupLabel = document.createElement("p");
    groupLabel.className = "sc-signal-group-label";
    groupLabel.textContent = label;
    group.appendChild(groupLabel);
    const chips = document.createElement("div");
    chips.className = "sc-signal-chips";
    items.forEach((sig) => {
      const chip = document.createElement("span");
      chip.className = "sc-signal-chip";
      chip.textContent = sig;
      chips.appendChild(chip);
    });
    group.appendChild(chips);
    container.appendChild(group);
  });

  if (emptyEl) emptyEl.hidden = hasAny;
  return hasAny;
}

function hasNoBattleAnswers(data) {
  const scores = data.scores ?? {};
  const allZero = Object.values(scores).every((v) => (v?.score ?? 0) === 0);
  const noBest = !String(data.best_answer ?? "").trim();
  return allZero || noBest;
}

function renderScorecard(data) {
  const overall = data.overall ?? 0;
  const overallEl = document.getElementById("overall-score");
  if (overallEl) overallEl.textContent = overall;

  const overallLabelEl = document.getElementById("overall-label");
  if (overallLabelEl) {
    overallLabelEl.textContent = data.overall_label ?? "";
    overallLabelEl.hidden = !data.overall_label;
  }

  const scores = data.scores ?? {};
  const { strongest, weakest } = getStrongestWeakest(scores);
  const se = data.score_explanation ?? {};
  const explanation = se;
  const nemotronScored = isNemotronScorecardSource(data.scorecard_source);

  const opponent = PERSONA_LABELS[state.persona] ?? data.opponent ?? "AI Judge";
  const mode = DIFFICULTY_LABELS[state.difficultyProfile]
    ?? data.difficulty_label
    ?? "Practice Mode";
  const heroLabel = document.getElementById("sc-hero-label");
  if (heroLabel) {
    heroLabel.textContent = `Pitch Battle Result · ${opponent} · ${mode}`;
  }

  const whySentence = se.why_you_scored_this?.split(/[.!?]/)[0]?.trim() ?? "";
  const readoutEl = document.getElementById("pitch-readout");
  if (readoutEl) {
    const parts = [];
    if (data.overall_label) parts.push(data.overall_label);
    if (whySentence) parts.push(whySentence);
    readoutEl.textContent = parts.length
      ? parts.join(" — ")
      : "Your pitch battle is complete.";
  }

  const strongChip = document.getElementById("chip-strongest-dim");
  const weakChip = document.getElementById("chip-weakest-dim");
  if (strongChip) {
    strongChip.textContent = strongest
      ? `↑ Strongest: ${formatDimLabel(strongest[0])}`
      : "↑ Strongest: —";
  }
  if (weakChip) {
    weakChip.textContent = weakest
      ? `↓ Weakest: ${formatDimLabel(weakest[0])}`
      : "↓ Weakest: —";
  }

  const chipSource = document.getElementById("chip-score-source");
  const sourceBadgeEl = document.getElementById("scorecard-source-badge");
  if (chipSource) {
    chipSource.textContent = nemotronScored ? "⚡ Nemotron" : "⚡ Local";
    chipSource.hidden = false;
  }
  if (sourceBadgeEl) {
    sourceBadgeEl.textContent = nemotronScored ? "Powered by NVIDIA Nemotron" : "Local scoring";
  }

  const fallbackWarnEl = document.getElementById("scorecard-fallback-warning");
  if (fallbackWarnEl) {
    fallbackWarnEl.textContent = "";
    fallbackWarnEl.hidden = true;
  }
  if (data.model_error) {
    console.warn("Scorecard model note (not shown to user):", data.model_error);
  }

  const bars = document.getElementById("score-bars");
  if (bars) {
    bars.innerHTML = "";
    Object.entries(scores).forEach(([key, value]) => {
      bars.appendChild(
        buildDimensionRow(key, value, {
          layout: "scorecard",
          strongestKey: strongest?.[0] ?? null,
          weakestKey: weakest?.[0] ?? null,
        }),
      );
    });
  }

  renderSignalsGroups(data.concrete_signals_summary ?? {});

  const atr = se.answer_to_retry ?? {};
  const nextLine = atr.retry_advice ?? "";
  const nextText = document.getElementById("pitch-next-action-text");
  if (nextText) {
    nextText.textContent = nextLine
      ? (nextLine.endsWith(".") ? nextLine : `${nextLine}.`)
      : "";
  }

  const whyScoredEl = document.getElementById("score-why-scored");
  const whatStoppedEl = document.getElementById("score-what-stopped");
  if (whyScoredEl) whyScoredEl.textContent = explanation.why_you_scored_this ?? "";
  if (whatStoppedEl) whatStoppedEl.textContent = explanation.what_stopped_80 ?? "";

  const setText = (id, text) => {
    const el = document.getElementById(id);
    if (!el) return;
    el.textContent = text ?? "";
    el.classList.remove("expanded");
    const next = el.nextElementSibling;
    if (next?.classList?.contains("show-more-btn")) next.remove();
  };

  setText("improved-answer", data.improved_answer);
  setText("improved-pitch", data.improved_pitch);
  setText("best-answer", data.best_answer);
  setText("weakest-answer", data.weakest_answer);

  const setRoundBadge = (id, round) => {
    const el = document.getElementById(id);
    if (!el) return;
    if (round) {
      el.textContent = `Round ${round}`;
      el.hidden = false;
    } else {
      el.textContent = "";
      el.hidden = true;
    }
  };
  setRoundBadge("best-answer-round", data.best_answer_round);
  setRoundBadge("weakest-answer-round", data.weakest_answer_round);

  const whyWeakEl = document.getElementById("why-weak");
  if (whyWeakEl) {
    const why = data.why_weak ?? "";
    whyWeakEl.textContent = why ? `Why it hurt: ${why}` : "";
    whyWeakEl.hidden = !why;
  }

  const list = document.getElementById("top-questions");
  if (list) {
    list.innerHTML = "";
    (data.top_3_questions ?? []).forEach((q) => {
      const li = document.createElement("li");
      li.textContent = q;
      list.appendChild(li);
    });
  }

  const prepRetryText = document.getElementById("sc-prep-retry-text");
  if (prepRetryText) {
    const weakDim = weakest ? formatDimLabel(weakest[0]).toLowerCase() : "your weakest dimension";
    prepRetryText.textContent = `Your weakest answer was on ${weakDim}. Practice it again?`;
  }

  const noAnswers = hasNoBattleAnswers(data);
  const answersEmpty = document.getElementById("answers-empty-state");
  const answersContent = document.getElementById("answers-content");
  if (answersEmpty) answersEmpty.hidden = !noAnswers;
  if (answersContent) answersContent.hidden = noAnswers;

  state.scoreExplanation = data.score_explanation ?? null;

  const pathBtn = document.getElementById("btn-path-to-80");
  if (pathBtn) pathBtn.hidden = !Boolean(state.scoreExplanation);

  renderVoiceDelivery(data.voice_delivery);
  renderJudgeVerdict(data.judge_verdict);
  state.judgeVerdict = data.judge_verdict ?? null;

  const orb = document.querySelector("#screen-scorecard .sc-ring");
  if (orb) {
    orb.classList.remove("score-high", "score-mid", "score-low");
    orb.classList.add(scoreBand(overall));
  }

  activateScorecardTab("overview");

  state.scorecardSnapshot = {
    overall,
    overallLabel: data.overall_label ?? "",
    strongest: strongest ? formatDimLabel(strongest[0]) : null,
    weakest: weakest ? formatDimLabel(weakest[0]) : null,
    roundsCompleted: state.battleLog?.length ?? 0,
  };
}

const DEAL_TYPE_LABELS = {
  equity: "Equity Negotiation",
  mentorship: "Mentorship Terms",
  pilot: "Pilot Agreement",
  sponsorship: "Sponsorship Terms",
  verdict_only: "Hackathon Verdict",
  none: "General Discussion",
};

function verdictNegotiationCta(label, fallback = "Start Negotiation →") {
  const text = String(label || "").trim();
  if (!text || /pitch practice/i.test(text)) return fallback;
  return text
    .replace(/Continue to Deal Practice/i, "Start Negotiation")
    .replace(/Continue to Deal Round/i, "Start Negotiation")
    .replace(/Deal Practice/i, "Negotiation")
    .replace(/Deal Round/i, "Negotiation");
}

function renderJudgeVerdict(verdict) {
  const heroWrap = document.getElementById("judge-verdict-hero");
  if (!verdict || !verdict.interest_level) {
    if (heroWrap) heroWrap.hidden = true;
    return;
  }
  if (heroWrap) heroWrap.hidden = false;

  const interest = verdict.interest_level || "no_interest";
  const personaLine = `${verdict.persona_name || "Judge"} — ${verdict.persona_type || ""}`.trim();

  document.getElementById("verdict-persona-badge").textContent = personaLine;
  const badge = document.getElementById("verdict-interest-badge");
  badge.textContent = verdict.interest_label || interest.replaceAll("_", " ");
  badge.className = `sc-verdict-pill interest-${interest}`;

  const reactionEl = document.getElementById("verdict-reaction");
  if (reactionEl) {
    reactionEl.textContent = verdict.judge_reaction || "";
  }
  document.getElementById("verdict-deal-type").textContent =
    DEAL_TYPE_LABELS[verdict.deal_type] || verdict.deal_type || "—";
  const whyEl = document.getElementById("verdict-why");
  if (whyEl) whyEl.textContent = verdict.why_this_verdict || "";

  const offerEl = document.getElementById("verdict-opening-offer");
  if (offerEl) {
    if (verdict.deal_opening_offer) {
      offerEl.textContent = `Opening offer: ${verdict.deal_opening_offer}`;
      offerEl.hidden = false;
    } else {
      offerEl.hidden = true;
    }
  }

  const actions = document.getElementById("verdict-actions");
  if (!actions) return;
  actions.innerHTML = "";

  if (verdict.can_continue_to_deal) {
    const btn = document.createElement("button");
    btn.className = "btn btn-deal-continue";
    btn.textContent = verdictNegotiationCta(verdict.next_step_label);
    btn.type = "button";
    btn.addEventListener("click", startDealPhase);
    actions.appendChild(btn);
  } else if (interest === "too_early") {
    /* Footer sc-cta-row handles retry / setup */
  } else if (interest === "no_interest") {
    /* Footer sc-cta-row handles Path to 80+ and New Battle */
  } else if (interest === "mild_interest" || interest === "strong_interest") {
    if (!verdict.can_continue_to_deal) {
      const btn = document.createElement("button");
      btn.className = "btn btn-deal-continue";
      btn.textContent = verdictNegotiationCta(verdict.next_step_label);
      btn.type = "button";
      btn.addEventListener("click", startDealPhase);
      actions.appendChild(btn);
    }
  } else if (verdict.deal_type === "verdict_only") {
    /* Footer sc-cta-row handles Path to 80+ */
  }
}

function renderDealArena(data) {
  state.uiMode = "deal";
  state.dealContext = data.deal_context || {};
  state.dealRound = data.round ?? 1;

  document.getElementById("deal-round-counter").textContent = state.dealRound;
  const dealRoundDisplay = document.getElementById("deal-round-display");
  if (dealRoundDisplay) dealRoundDisplay.textContent = String(state.dealRound).padStart(2, "0");
  const dealRoundDuel = document.getElementById("deal-round-counter-duel");
  if (dealRoundDuel) dealRoundDuel.textContent = state.dealRound;

  const dealType = DEAL_TYPE_LABELS[data.deal_type] || data.deal_type || "—";
  document.getElementById("deal-type-label").textContent = dealType;
  const typeChip = document.getElementById("deal-type-chip");
  if (typeChip) typeChip.textContent = dealType;

  const focus = data.negotiation_tag || "—";
  document.getElementById("deal-negotiation-tag").textContent = focus;
  const focusChip = document.getElementById("deal-focus-chip");
  if (focusChip) focusChip.textContent = focus;

  document.getElementById("deal-persona-name").textContent =
    `${data.persona_name || ""} — ${data.persona_role || ""}`.trim();
  document.getElementById("deal-opening-offer").textContent =
    data.deal_context?.opening_offer || data.deal_context?.judge_position || "—";
  document.getElementById("deal-your-ask").textContent = data.deal_context?.ask || "—";

  updateProgressStrip(state.dealRound, focus, "deal");
  updateJudgeAttackPill(focus, "deal");
}

export async function startDealPhase() {
  if (!state.sessionId) return;
  try {
    setGlobalLoading(true, "Preparing deal terms…");
    const data = await apiPost("/api/start-deal-phase", { session_id: state.sessionId });
    if (data.error) {
      showErrorBanner(data.error);
      return;
    }
    if (dealChatWindow) dealChatWindow.innerHTML = "";
    state.dealConversationLog = [];
    state.dealBattleLog = [];
    liveDealJudgeTurn = { text: "", meta: "" };
    liveDealFounderReply = "";
    document.getElementById("deal-log-tabs") && (document.getElementById("deal-log-tabs").innerHTML = "");
    document.getElementById("deal-log-ribbon")?.setAttribute("hidden", "");
    document.getElementById("btn-open-deal-rounds")?.setAttribute("hidden", "");
    document.getElementById("deal-rounds-drawer")?.setAttribute("hidden", "");
    if (dealInput) dealInput.value = "";
    dealStatus.hidden = true;
    document.getElementById("deal-readiness-prompt")?.setAttribute("hidden", "");
    renderDealArena(data);
    appendDealMessage(
      "ai",
      data.ai_message,
      `${data.negotiation_tag} · Round ${data.round}`,
    );
    showScreen("deal");
    hideErrorBanner();
  } catch (error) {
    console.error(error);
    showErrorBanner("Could not start deal phase.");
  } finally {
    setGlobalLoading(false);
  }
}

export async function sendDealRound(messageOverride, voiceMeta = null) {
  const message = (messageOverride ?? dealInput?.value ?? "").trim();
  if (!message || !state.sessionId) return;

  try {
    setGlobalLoading(true, "Scoring your counter…");
    if (dealInput) dealInput.value = "";
    appendDealMessage("user", message);

    const payload = {
      session_id: state.sessionId,
      user_message: message,
      input_mode: voiceMeta?.voice_turn_id ? "voice" : "text",
    };
    if (voiceMeta?.voice_turn_id) payload.voice_turn_id = voiceMeta.voice_turn_id;

    const data = await apiPost("/api/deal-round", payload);
    if (data.error) {
      if (dealStatus) {
        dealStatus.hidden = false;
        dealStatus.textContent = data.error;
      }
      return;
    }

    state.dealRound = data.round ?? state.dealRound;
    document.getElementById("deal-round-counter").textContent = state.dealRound;
    const dealRoundDisplay = document.getElementById("deal-round-display");
    if (dealRoundDisplay) dealRoundDisplay.textContent = String(state.dealRound).padStart(2, "0");
    const dealRoundDuel = document.getElementById("deal-round-counter-duel");
    if (dealRoundDuel) dealRoundDuel.textContent = state.dealRound;
    document.getElementById("deal-negotiation-tag").textContent = data.negotiation_tag || "—";
    updateProgressStrip(state.dealRound, data.negotiation_tag, "deal");

    appendDealMessage(
      "ai",
      data.ai_message,
      `${data.negotiation_tag} · Round ${data.round}`,
    );

    updateDealReadiness(data.readiness, data.soft_limit_reached, data.completion_message);

    state.pendingDealVoiceTurn = null;
    document.getElementById("deal-voice-preview")?.setAttribute("hidden", "");
  } catch (error) {
    console.error(error);
    dealStatus.hidden = false;
    dealStatus.textContent = "Deal round failed. Try again.";
  } finally {
    setGlobalLoading(false);
  }
}

function updateDealReadiness(readiness, softLimit, completionMessage) {
  const prompt = document.getElementById("deal-readiness-prompt");
  const text = document.getElementById("deal-readiness-text");
  const action = readiness?.recommended_action;
  const shouldShow = action === "recommend_end" || action === "force_end" || softLimit;
  if (!prompt) return;
  if (!shouldShow) {
    prompt.hidden = true;
    return;
  }
  if (text) {
    text.textContent = readiness?.reason
      || completionMessage
      || "You have enough negotiation signal for a scorecard. You can end now or continue one more round.";
  }
  // At the hard cap, hide the "continue" option.
  const continueBtn = document.getElementById("btn-deal-readiness-continue");
  if (continueBtn) continueBtn.style.display = action === "force_end" ? "none" : "";
  prompt.hidden = false;
}

function showDealVoicePreview(data) {
  state.pendingDealVoiceTurn = data;
  const preview = document.getElementById("deal-voice-preview");
  const transcriptEl = document.getElementById("deal-voice-transcript");
  if (preview) preview.hidden = false;
  if (transcriptEl) transcriptEl.value = data.transcript ?? "";
  if (dealInput) dealInput.value = data.transcript ?? "";
}

export async function endDeal() {
  if (!state.sessionId) return;
  try {
    setGlobalLoading(true, "Building deal scorecard…");
    const data = await apiPost("/api/end-deal", { session_id: state.sessionId });
    if (data.error) {
      showErrorBanner(data.error);
      return;
    }
    state.negotiationTranscript = data.negotiation_transcript || [];
    renderDealScorecard(data);
    showScreen("dealScorecard");
    hideErrorBanner();
  } catch (error) {
    console.error(error);
    showErrorBanner("Failed to generate deal scorecard.");
  } finally {
    setGlobalLoading(false);
  }
}

function renderDealScorecard(data) {
  const combined = data.combined_scorecard || {};
  const deal = data.deal_scorecard || {};

  const pitch = combined.pitch_overall ?? 0;
  const dealScore = combined.deal_overall ?? 0;
  const overall = combined.combined_overall ?? 0;

  document.getElementById("combined-pitch").textContent = pitch;
  document.getElementById("combined-deal").textContent = dealScore;
  document.getElementById("combined-overall").textContent = overall;

  ["combined-pitch-tab", "combined-deal-tab", "combined-overall-tab"].forEach((id, i) => {
    const el = document.getElementById(id);
    if (el) el.textContent = [pitch, dealScore, overall][i];
  });

  const profile = combined.founder_profile ?? "";
  document.getElementById("combined-profile").textContent = profile;
  const profileTab = document.getElementById("combined-profile-tab");
  if (profileTab) profileTab.textContent = profile;

  const summaryEl = document.getElementById("combined-summary");
  if (summaryEl) {
    summaryEl.textContent = combined.summary ?? "";
    attachShowMore(summaryEl);
  }

  const nextEl = document.getElementById("combined-next-action");
  if (nextEl) {
    nextEl.textContent = combined.next_best_action ?? "Review deal dimensions and prep points below.";
  }

  const outcomeEl = document.getElementById("deal-outcome-badge");
  if (outcomeEl) {
    outcomeEl.textContent = (deal.deal_outcome || "balanced").replaceAll("_", " ");
    outcomeEl.className = `deal-outcome-badge result-verdict-badge outcome-${deal.deal_outcome || "balanced"}`;
  }
  document.getElementById("deal-overall-label").textContent =
    `${deal.overall ?? 0} — ${deal.overall_label ?? ""}`;

  const dealWeakest = getStrongestWeakest(deal.scores || {}).weakest;
  const weakestLine = document.getElementById("deal-summary-weakest");
  if (weakestLine) {
    weakestLine.textContent = dealWeakest
      ? `Weakest negotiation skill: ${formatDimLabel(dealWeakest[0])} (${dealWeakest[1].score ?? 0})`
      : "";
  }

  const bars = document.getElementById("deal-score-bars");
  if (bars) {
    bars.innerHTML = "";
    Object.entries(deal.scores || {}).forEach(([key, value]) => {
      bars.appendChild(buildDimensionRow(key, value, { showQuote: true }));
    });
  }

  const WEAK_FALLBACK =
    "No major single weak move detected; the main weakness was lack of alternatives/leverage.";
  const bestEl = document.getElementById("deal-best-move");
  const weakEl = document.getElementById("deal-weakest-move");
  const improvedEl = document.getElementById("deal-improved-response");
  if (bestEl) {
    bestEl.textContent = cleanMoveText(deal.best_move) || "No standout negotiation move was recorded.";
    attachShowMore(bestEl);
  }
  if (weakEl) {
    weakEl.textContent = cleanMoveText(deal.weakest_move) || WEAK_FALLBACK;
    attachShowMore(weakEl);
  }
  if (improvedEl) {
    improvedEl.textContent = deal.improved_response ?? "";
    attachShowMore(improvedEl);
  }

  const prep = document.getElementById("deal-prep-points");
  if (prep) {
    prep.innerHTML = "";
    (deal.top_3_prep_points || []).forEach((p) => {
      const li = document.createElement("li");
      li.textContent = p;
      prep.appendChild(li);
    });
  }

  const metaEl = document.getElementById("deal-scorecard-meta");
  if (metaEl) {
    const nemotronScored = isNemotronScorecardSource(deal.scorecard_source);
    metaEl.textContent = nemotronScored ? "Powered by NVIDIA Nemotron" : "";
    metaEl.hidden = !nemotronScored;
  }

  initResultTabs("deal-result-tabs", "deal-result-panels");
  switchResultTab("deal-result-tabs", "deal-summary");
}

// Reject empty / single-word / obviously truncated move text so the UI never
// shows a lone "sure" or a half-sentence.
function cleanMoveText(text) {
  const t = (text || "").trim();
  if (!t) return "";
  const bareWords = ["sure", "ok", "okay", "yes", "fine", "yeah"];
  if (bareWords.includes(t.toLowerCase().replace(/[.!?]$/, ""))) return "";
  if (t.length < 12) return "";
  return t;
}

function renderNegotiationTranscript() {
  const container = document.getElementById("negotiation-transcript");
  if (!container) return;
  container.innerHTML = "";
  const transcript = state.negotiationTranscript || [];
  if (!transcript.length) {
    container.innerHTML = `<p class="negotiation-empty">No negotiation messages were recorded.</p>`;
    return;
  }
  transcript.forEach((turn) => {
    const row = document.createElement("div");
    const role = turn.role === "judge" ? "judge" : "founder";
    row.className = `negotiation-turn negotiation-${role}`;
    const speaker = role === "judge" ? "Judge" : "Founder";
    const badges = [];
    if (turn.negotiation_tag) {
      badges.push(`<span class="neg-badge neg-tag source-chip">${escapeHtml(turn.negotiation_tag)}</span>`);
    }
    if (turn.answer_quality) {
      badges.push(`<span class="neg-badge neg-quality neg-q-${escapeHtml(turn.answer_quality)} source-chip">${escapeHtml(turn.answer_quality)}</span>`);
    }
    if ((turn.input_mode || "") === "voice") {
      badges.push(`<span class="neg-badge neg-voice source-chip">Voice</span>`);
    }
    if (turn.action_taken) {
      badges.push(`<span class="neg-badge source-chip">${escapeHtml(turn.action_taken)}</span>`);
    }
    row.innerHTML = `
      <div class="negotiation-turn-head">
        <span class="negotiation-speaker">${turn.round ? `Round ${turn.round} · ` : ""}${speaker}</span>
        <span class="negotiation-badges">${badges.join("")}</span>
      </div>
      <p class="negotiation-message">${escapeHtml(turn.message || "")}</p>
    `;
    container.appendChild(row);
  });
  container.scrollTop = container.scrollHeight;
}

function openNegotiationModal() {
  renderNegotiationTranscript();
  const overlay = document.getElementById("negotiation-overlay");
  if (overlay) overlay.hidden = false;
}

function closeNegotiationModal() {
  const overlay = document.getElementById("negotiation-overlay");
  if (overlay) overlay.hidden = true;
}

function renderVoiceDelivery(vd) {
  const content = document.getElementById("voice-delivery-content");
  const section = document.getElementById("voice-delivery-section");
  const tab = document.getElementById("tab-voice-delivery");
  if (!content) return;
  if (!vd || typeof vd !== "object") {
    if (section) section.hidden = true;
    if (tab) tab.hidden = true;
    content.innerHTML = "";
    return;
  }
  if (section) section.hidden = false;
  if (tab) tab.hidden = false;

  const fillers = (vd.filler_word_list ?? []).slice(0, 6).join(", ") || "None detected";
  const overallNote = vd.overall_delivery_feedback
    || (vd.delivery_notes ?? []).find((n) => String(n).trim()) || "";

  content.innerHTML = `
    <div class="voice-wave-decor" aria-hidden="true"></div>
    <div class="voice-delivery-summary voice-delivery-grid">
      <div class="voice-delivery-stat"><span>Voice turns</span><strong>${vd.total_voice_turns ?? 0}</strong></div>
      <div class="voice-delivery-stat"><span>Filler words</span><strong>${vd.total_filler_words ?? 0}</strong></div>
      <div class="voice-delivery-stat"><span>Common fillers</span><strong>${escapeHtml(fillers)}</strong></div>
      <div class="voice-delivery-stat"><span>Pace</span><strong>${escapeHtml(vd.average_pace ?? "—")}</strong></div>
      <div class="voice-delivery-stat"><span>Clarity signal</span><strong>${escapeHtml(vd.clarity_signal ?? "—")}</strong></div>
      <div class="voice-delivery-stat"><span>Confidence signal</span><strong>${escapeHtml(vd.confidence_signal ?? "—")}</strong></div>
    </div>
    ${overallNote ? `<p class="voice-delivery-overall">${escapeHtml(overallNote)}</p>` : ""}
  `;

  const notes = (vd.delivery_notes ?? []).filter((n) => {
    const t = String(n || "").trim().toLowerCase();
    const overallLower = String(overallNote).trim().toLowerCase();
    return t && t !== "clean delivery." && t !== "clean delivery" && t !== overallLower;
  });
  const uniqueNotes = [...new Set(notes.map((n) => String(n).trim()))].slice(0, 3);
  if (uniqueNotes.length) {
    const ul = document.createElement("ul");
    ul.className = "voice-delivery-notes";
    uniqueNotes.forEach((n) => {
      const li = document.createElement("li");
      li.textContent = n;
      ul.appendChild(li);
    });
    content.appendChild(ul);
  }
}

function fillVoiceExtractForm(data) {
  const form = document.getElementById("voice-extract-form");
  if (!form || !data) return;
  const extracted = data.extracted ?? {};
  Object.entries(extracted).forEach(([key, value]) => {
    const field = form.elements.namedItem(key);
    if (field) field.value = value ?? "";
  });
  const transcriptEl = document.getElementById("voice-confirm-transcript");
  if (transcriptEl) transcriptEl.textContent = data.transcript ?? "";
  const deliveryEl = document.getElementById("voice-confirm-delivery");
  const obs = data.delivery_observations ?? {};
  if (deliveryEl) {
    deliveryEl.textContent = obs.delivery_note
      ? `Delivery: ${obs.delivery_note}`
      : "";
  }
  const confEl = document.getElementById("voice-confirm-confidence");
  if (confEl) {
    const conf = data.extraction_confidence ?? "medium";
    confEl.textContent = `Confidence: ${conf}`;
    confEl.className = `delivery-chip confidence-${conf}`;
  }
  const warn = document.getElementById("voice-confidence-warning");
  if (warn) warn.hidden = (data.extraction_confidence ?? "medium") !== "low";
}

function showVoiceTurnPreview(data) {
  state.pendingVoiceTurn = data;
  const preview = document.getElementById("voice-turn-preview");
  const transcriptEl = document.getElementById("voice-turn-transcript");
  const deliveryEl = document.getElementById("voice-turn-delivery");
  if (preview) preview.hidden = false;
  if (transcriptEl) transcriptEl.value = data.transcript ?? "";
  if (deliveryEl) {
    deliveryEl.textContent = data.delivery_note
      ? `Delivery: ${data.delivery_note}`
      : "";
  }
}

function openPath80() {
  const ex = state.scoreExplanation;
  if (!ex) return;

  const esif = ex.estimated_score_if_fixed ?? {};
  const atr  = ex.answer_to_retry ?? {};

  const setEl = (id, text) => {
    const el = document.getElementById(id);
    if (el) el.textContent = text ?? "";
  };

  setEl("p80-current-score", esif.current_overall ?? "—");
  setEl("p80-estimated-score", esif.estimated_new_overall ?? "—");
  setEl("p80-estimate-reason", esif.reason ?? "");
  setEl("p80-why-scored", ex.why_you_scored_this ?? "");
  setEl("p80-what-stopped", ex.what_stopped_80 ?? "");

  const dimBadge = document.getElementById("p80-retry-dim");
  if (dimBadge) dimBadge.textContent = (atr.dimension ?? "").replaceAll("_", " ");

  const roundTag = document.getElementById("p80-retry-round");
  if (roundTag) roundTag.textContent = atr.round ? `Round ${atr.round}` : "";

  setEl("p80-original-answer", atr.original_answer ?? "");
  setEl("p80-why-it-hurt", atr.why_it_hurt ?? "");
  setEl("p80-retry-advice", atr.retry_advice ?? "");
  setEl("p80-sample-answer", atr.sample_stronger_answer ?? "");

  ["p80-why-scored", "p80-what-stopped", "p80-original-answer", "p80-why-it-hurt", "p80-retry-advice"].forEach((id) => {
    attachShowMore(document.getElementById(id));
  });

  document.getElementById("path80-overlay").hidden = false;
  document.body.style.overflow = "hidden";
}

function closePath80() {
  document.getElementById("path80-overlay").hidden = true;
  document.body.style.overflow = "";
}

function showRetryDrillView() {
  document.getElementById("retry-drill-view").hidden = false;
  document.getElementById("retry-result-view").hidden = true;
}

function showRetryResultView() {
  document.getElementById("retry-drill-view").hidden = true;
  document.getElementById("retry-result-view").hidden = false;
}

function populateRetryDrill(data) {
  const q = data.retry_question || data.original_question || "";
  document.getElementById("retry-original-question").textContent = q;
  document.getElementById("retry-original-answer").textContent = data.original_answer ?? "";
  document.getElementById("retry-why-hurt").textContent = data.why_it_hurt ?? "";
  document.getElementById("retry-sample").textContent = data.sample_stronger_answer ?? "";
  const input = document.getElementById("retry-answer-input");
  if (input) input.value = "";
  document.getElementById("retry-voice-preview")?.setAttribute("hidden", "");
  state.pendingRetryVoiceTurn = null;
  showRetryDrillView();
}

async function startRetryDrill() {
  if (!state.sessionId) return;
  try {
    setGlobalLoading(true, "Preparing retry drill...");
    const data = await apiPost("/api/retry-weakest-question/start", {
      session_id: state.sessionId,
    });
    if (data.error) {
      showErrorBanner(data.error);
      return;
    }
    state.retryDrill = data;
    closePath80();
    populateRetryDrill(data);
    document.getElementById("retry-overlay").hidden = false;
    document.body.style.overflow = "hidden";
    hideErrorBanner();
  } catch (error) {
    console.error(error);
    showErrorBanner("Could not start retry drill. Try again.");
  } finally {
    setGlobalLoading(false);
  }
}

function showRetryVoicePreview(data) {
  state.pendingRetryVoiceTurn = data;
  const preview = document.getElementById("retry-voice-preview");
  const transcriptEl = document.getElementById("retry-voice-transcript");
  const input = document.getElementById("retry-answer-input");
  if (preview) preview.hidden = false;
  if (transcriptEl) transcriptEl.value = data.transcript ?? "";
  if (input) input.value = data.transcript ?? "";
}

function renderRetryResult(data) {
  const comp = data.comparison ?? {};
  document.getElementById("retry-result-old").textContent = comp.old_answer_summary ?? data.original_answer ?? "";
  document.getElementById("retry-result-new").textContent = comp.new_answer_summary ?? data.retry_answer ?? "";
  document.getElementById("retry-what-improved").textContent = comp.what_improved ?? "";
  document.getElementById("retry-still-missing").textContent = comp.still_missing ?? "";
  document.getElementById("retry-specific-tip").textContent = comp.specific_tip ?? "";

  const dim = formatDimLabel(data.dimension);
  const before = comp.estimated_dimension_before ?? 0;
  const after = comp.estimated_dimension_after ?? before;
  document.getElementById("retry-dim-estimate").textContent =
    `${formatDimLabel(data.dimension)}: ${before} → ${after}`;
  const lift = data.updated_scorecard?.retry_overall_lift ?? comp.estimated_overall_lift ?? 0;
  document.getElementById("retry-overall-lift").textContent =
    data.updated_scorecard
      ? `Overall score: ${data.updated_scorecard.overall} (+${lift})`
      : `Overall lift: +${lift}`;

  const verdictEl = document.getElementById("retry-verdict-badge");
  const verdict = comp.verdict ?? "needs_more_work";
  const verdictLabels = {
    improved: "Improved",
    slightly_improved: "Slightly improved",
    needs_more_work: "Needs more work",
  };
  if (verdictEl) {
    verdictEl.textContent = verdictLabels[verdict] ?? verdict;
    verdictEl.className = `retry-verdict-badge verdict-${verdict}`;
  }

  const nextPrompt = document.getElementById("retry-next-prompt");
  if (nextPrompt) {
    nextPrompt.textContent = data.next_practice_prompt
      ? `Next practice: ${data.next_practice_prompt}`
      : "";
  }
  showRetryResultView();
}

async function submitRetryAnswer() {
  if (!state.sessionId || !state.retryDrill?.retry_id) return;

  const voiceTranscript = document.getElementById("retry-voice-transcript")?.value?.trim();
  const typed = document.getElementById("retry-answer-input")?.value?.trim();
  const answer = voiceTranscript || typed;
  if (!answer) return;

  const payload = {
    session_id: state.sessionId,
    retry_id: state.retryDrill.retry_id,
    retry_answer: answer,
    input_mode: state.pendingRetryVoiceTurn ? "voice" : "text",
  };
  if (state.pendingRetryVoiceTurn?.voice_turn_id) {
    payload.voice_turn_id = state.pendingRetryVoiceTurn.voice_turn_id;
  }

  try {
    setGlobalLoading(true, "Comparing your retry answer...");
    const data = await apiPost("/api/retry-weakest-question/submit", payload);
    if (data.error) {
      showErrorBanner(data.error);
      return;
    }
    renderRetryResult(data);
    if (data.updated_scorecard) {
      renderScorecard(data.updated_scorecard);
      state.scoreExplanation = data.updated_scorecard.score_explanation ?? state.scoreExplanation;
      if (data.judge_verdict) {
        renderJudgeVerdict(data.judge_verdict);
        state.judgeVerdict = data.judge_verdict;
      }
    }
    hideErrorBanner();
  } catch (error) {
    console.error(error);
    showErrorBanner("Retry submission failed. Try again.");
  } finally {
    setGlobalLoading(false);
  }
}

function closeRetryOverlay() {
  document.getElementById("retry-overlay").hidden = true;
  document.body.style.overflow = "";
  state.pendingRetryVoiceTurn = null;
}

function openRetryFromPath80() {
  startRetryDrill();
}

document.getElementById("btn-load-sample").addEventListener("click", loadSample);
document.getElementById("btn-load-sample-setup")?.addEventListener("click", loadSample);
document.getElementById("btn-go-setup").addEventListener("click", () => {
  resetSetupScreen();
  showScreen("setup");
});
document.getElementById("btn-back-landing").addEventListener("click", () => {
  resetSetupScreen();
  showScreen("landing");
});
document.getElementById("tab-quick-pitch")?.addEventListener("click", () => setBriefingMode("quick"));
document.getElementById("tab-advanced-briefing")?.addEventListener("click", () => setBriefingMode("advanced"));
document.getElementById("btn-structure-pitch")?.addEventListener("click", structurePitch);
document.getElementById("btn-record-voice-setup")?.addEventListener("click", () => {
  state.startMode = "voice";
  showScreen("voicePitch");
});
document.getElementById("btn-looks-good-start")?.addEventListener("click", () => {
  syncBriefToStartupForm();
  startSession();
});
document.getElementById("btn-restructure-pitch")?.addEventListener("click", () => {
  hideBriefPreview();
  document.getElementById("quick-pitch-text")?.focus();
});
document.getElementById("btn-start-back-landing").addEventListener("click", () => showScreen("landing"));

document.getElementById("btn-start-text").addEventListener("click", () => {
  state.startMode = "text";
  document.querySelectorAll(".start-method-card").forEach((c) => c.classList.remove("selected"));
  document.getElementById("btn-start-text").classList.add("selected");
});
document.getElementById("btn-start-voice").addEventListener("click", () => {
  state.startMode = "voice";
  document.querySelectorAll(".start-method-card").forEach((c) => c.classList.remove("selected"));
  document.getElementById("btn-start-voice").classList.add("selected");
});
document.getElementById("btn-continue-start").addEventListener("click", () => {
  if (state.startMode === "voice") showScreen("voicePitch");
  else showScreen("setup");
});
document.getElementById("btn-voice-pitch-back").addEventListener("click", () => showScreen("setup"));
document.getElementById("btn-voice-edit-manual").addEventListener("click", () => {
  const form = document.getElementById("voice-extract-form");
  const data = new FormData(form);
  applyVoicePitchToBriefing({
    extracted: Object.fromEntries(data.entries()),
    transcript: document.getElementById("voice-confirm-transcript")?.textContent || "",
    extraction_confidence: "medium",
  });
  setBriefingMode("advanced");
  showScreen("setup");
});
document.getElementById("btn-voice-looks-right").addEventListener("click", () => {
  const form = document.getElementById("voice-extract-form");
  const data = new FormData(form);
  applyVoicePitchToBriefing({
    extracted: Object.fromEntries(data.entries()),
    transcript: document.getElementById("voice-confirm-transcript")?.textContent || "",
    extraction_confidence: document.getElementById("voice-confirm-confidence")?.textContent?.replace("Confidence: ", "") || "medium",
    delivery_observations: {},
  });
  showScreen("setup");
});
document.getElementById("btn-voice-turn-send").addEventListener("click", () => {
  const transcript = document.getElementById("voice-turn-transcript")?.value?.trim();
  if (!transcript || !state.pendingVoiceTurn) return;
  sendMessage(transcript, {
    voice_turn_id: state.pendingVoiceTurn.voice_turn_id,
    delivery_metadata: {
      delivery_note: state.pendingVoiceTurn.delivery_note,
      delivery_cues: state.pendingVoiceTurn.delivery_cues,
      word_count: state.pendingVoiceTurn.word_count,
    },
  });
});
document.getElementById("btn-start-battle").addEventListener("click", startSession);
document.getElementById("btn-end-battle").addEventListener("click", endBattle);
document.getElementById("btn-reset").addEventListener("click", resetBattle);
document.getElementById("btn-back-setup")?.addEventListener("click", () => showScreen("setup"));
document.getElementById("btn-path-to-80").addEventListener("click", openPath80);
document.getElementById("btn-close-path80").addEventListener("click", closePath80);
document.getElementById("btn-close-path80-bottom").addEventListener("click", closePath80);
document.getElementById("btn-retry-question")?.addEventListener("click", openRetryFromPath80);
document.getElementById("btn-scorecard-retry")?.addEventListener("click", startRetryDrill);
document.getElementById("btn-prep-retry")?.addEventListener("click", startRetryDrill);
document.getElementById("btn-answers-retry")?.addEventListener("click", startRetryDrill);
document.getElementById("btn-answers-new-battle")?.addEventListener("click", resetBattle);
document.getElementById("path80-overlay").addEventListener("click", (e) => {
  if (e.target === e.currentTarget) closePath80();
});

document.getElementById("btn-close-retry")?.addEventListener("click", closeRetryOverlay);
document.getElementById("btn-submit-retry")?.addEventListener("click", submitRetryAnswer);
document.getElementById("btn-retry-again")?.addEventListener("click", () => {
  if (state.retryDrill) populateRetryDrill(state.retryDrill);
});
document.getElementById("btn-retry-back-scorecard")?.addEventListener("click", () => {
  closeRetryOverlay();
  showScreen("scorecard");
});
document.getElementById("btn-retry-new-battle")?.addEventListener("click", () => {
  closeRetryOverlay();
  resetBattle();
});
document.getElementById("retry-overlay")?.addEventListener("click", (e) => {
  if (e.target === e.currentTarget) closeRetryOverlay();
});

document.getElementById("btn-view-conversation").addEventListener("click", () => {
  document.getElementById("btn-end-battle").hidden = true;
  document.getElementById("btn-back-scorecard").hidden = false;
  document.getElementById("chat-form").hidden = true;
  showScreen("battle");
  openBattleConversationLog(true);
});

document.getElementById("btn-back-scorecard").addEventListener("click", () => {
  closeRoundsDrawer("battle-rounds-drawer");
  document.getElementById("btn-end-battle").hidden = false;
  document.getElementById("btn-back-scorecard").hidden = true;
  document.getElementById("chat-form").hidden = false;
  showScreen("scorecard");
});

document.getElementById("btn-open-battle-rounds")?.addEventListener("click", () => {
  openBattleConversationLog(false);
});
document.getElementById("btn-close-battle-rounds")?.addEventListener("click", () => {
  closeRoundsDrawer("battle-rounds-drawer");
});
document.getElementById("btn-close-battle-rounds-x")?.addEventListener("click", () => {
  closeRoundsDrawer("battle-rounds-drawer");
});
document.getElementById("btn-open-deal-rounds")?.addEventListener("click", () => {
  openRoundsDrawer("deal-rounds-drawer");
});
document.getElementById("btn-close-deal-rounds")?.addEventListener("click", () => {
  closeRoundsDrawer("deal-rounds-drawer");
});
document.getElementById("btn-close-deal-rounds-x")?.addEventListener("click", () => {
  closeRoundsDrawer("deal-rounds-drawer");
});

document.querySelectorAll(".persona-card").forEach((card) => {
  card.addEventListener("click", () => {
    document.querySelectorAll(".persona-card").forEach((c) => c.classList.remove("selected"));
    card.classList.add("selected");
    state.persona = card.dataset.persona;
  });
});

document.querySelectorAll(".difficulty-card").forEach((card) => {
  card.addEventListener("click", () => {
    document.querySelectorAll(".difficulty-card").forEach((c) => c.classList.remove("selected"));
    card.classList.add("selected");
    state.difficultyProfile = card.dataset.difficulty;
  });
});

document.getElementById("chat-form").addEventListener("submit", (event) => {
  event.preventDefault();
  sendMessage();
});

function bindEnterToSubmit(textarea, onSubmit) {
  textarea?.addEventListener("keydown", (event) => {
    if (event.key !== "Enter" || event.shiftKey || event.isComposing) return;
    event.preventDefault();
    onSubmit();
  });
}

bindEnterToSubmit(userInput, () => sendMessage());
bindEnterToSubmit(document.getElementById("deal-input"), () => sendDealRound());

document.getElementById("deal-form")?.addEventListener("submit", (event) => {
  event.preventDefault();
  sendDealRound();
});

document.getElementById("btn-end-deal")?.addEventListener("click", endDeal);
document.getElementById("btn-deal-back-scorecard")?.addEventListener("click", () => showScreen("scorecard"));
document.getElementById("btn-deal-new-battle")?.addEventListener("click", resetBattle);
document.getElementById("btn-deal-view-pitch-scorecard")?.addEventListener("click", () => showScreen("scorecard"));

document.getElementById("btn-deal-readiness-end")?.addEventListener("click", () => {
  document.getElementById("deal-readiness-prompt")?.setAttribute("hidden", "");
  endDeal();
});
document.getElementById("btn-deal-readiness-continue")?.addEventListener("click", () => {
  document.getElementById("deal-readiness-prompt")?.setAttribute("hidden", "");
  document.getElementById("deal-input")?.focus();
});

document.getElementById("btn-battle-readiness-end")?.addEventListener("click", () => {
  hideBattleReadiness();
  endBattle();
});
document.getElementById("btn-battle-readiness-continue")?.addEventListener("click", () => {
  hideBattleReadiness();
  userInput?.focus();
});

document.querySelectorAll(".hint-chip").forEach((chip) => {
  chip.addEventListener("click", () => {
    const hint = chip.dataset.hint;
    if (!hint || !userInput) return;
    const val = userInput.value.trim();
    userInput.value = val ? `${val} ${hint}`.trim() : hint.trim();
    userInput.focus();
  });
});

document.getElementById("btn-deal-view-negotiation")?.addEventListener("click", openNegotiationModal);
document.getElementById("btn-close-negotiation")?.addEventListener("click", closeNegotiationModal);
document.getElementById("btn-negotiation-back")?.addEventListener("click", closeNegotiationModal);
document.getElementById("negotiation-overlay")?.addEventListener("click", (event) => {
  if (event.target?.id === "negotiation-overlay") closeNegotiationModal();
});

document.getElementById("btn-deal-voice-send")?.addEventListener("click", () => {
  const transcript = document.getElementById("deal-voice-transcript")?.value?.trim();
  if (!transcript || !state.pendingDealVoiceTurn) return;
  sendDealRound(transcript, { voice_turn_id: state.pendingDealVoiceTurn.voice_turn_id });
});

document.getElementById("btn-deal-voice-cancel")?.addEventListener("click", () => {
  document.getElementById("deal-voice-preview")?.setAttribute("hidden", "");
  state.pendingDealVoiceTurn = null;
});

function boot() {
  console.log("PitchFight frontend booting...");
  setGlobalLoading(false);
  hideErrorBanner();
  setBriefingMode("quick");
  initBriefPreviewEditors();
  initLandingIntro();
  initScorecardTabs();

  initVoiceUI({
    getSessionId: () => state.sessionId,
    getUiMode: () => state.uiMode,
    onPitchComplete: (data) => {
      fillVoiceExtractForm(data);
      applyVoicePitchToBriefing(data);
      showScreen("setup");
      hideErrorBanner();
    },
    onTurnComplete: (data) => showVoiceTurnPreview(data),
    onRetryTurnComplete: (data) => showRetryVoicePreview(data),
    onDealTurnComplete: (data) => showDealVoicePreview(data),
    onError: (msg) => showErrorBanner(msg),
  });

  fetch("/health")
    .then((response) => response.json())
    .then((data) => console.log("Backend health:", data))
    .catch((error) => {
      console.warn("Health check failed:", error);
      showErrorBanner(
        "Backend health check failed. Run python app.py and refresh this page."
      );
    });
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", boot);
} else {
  boot();
}
