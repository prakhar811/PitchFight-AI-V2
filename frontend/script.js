const state = {
  sessionId: null,
  persona: "hackathon_judge",
  round: 1,
};

const screens = {
  landing: document.getElementById("screen-landing"),
  setup: document.getElementById("screen-setup"),
  battle: document.getElementById("screen-battle"),
  scorecard: document.getElementById("screen-scorecard"),
};

const startupForm = document.getElementById("startup-form");
const chatWindow = document.getElementById("chat-window");
const userInput = document.getElementById("user-input");
const loadingOverlay = document.getElementById("loading-overlay");
const loadingText = loadingOverlay?.querySelector("p");
const battleStatus = document.getElementById("battle-status");
const errorBanner = document.getElementById("error-banner");

function showScreen(name) {
  Object.entries(screens).forEach(([key, el]) => {
    el.classList.toggle("active", key === name);
  });
}

function setGlobalLoading(isLoading, message = "Loading...") {
  if (loadingText) loadingText.textContent = message;
  loadingOverlay.hidden = !isLoading;
}

function showErrorBanner(message) {
  errorBanner.textContent = message;
  errorBanner.hidden = false;
}

function hideErrorBanner() {
  errorBanner.hidden = true;
  errorBanner.textContent = "";
}

function getStartupPayload() {
  const data = new FormData(startupForm);
  return Object.fromEntries(data.entries());
}

function fillStartupForm(startup) {
  Object.entries(startup).forEach(([key, value]) => {
    const field = startupForm.elements.namedItem(key);
    if (field) field.value = value ?? "";
  });
}

function appendMessage(role, text, meta = "") {
  const bubble = document.createElement("div");
  bubble.className = `message ${role}`;
  bubble.innerHTML = meta
    ? `<span class="message-meta">${meta}</span><p>${escapeHtml(text)}</p>`
    : `<p>${escapeHtml(text)}</p>`;
  chatWindow.appendChild(bubble);
  chatWindow.scrollTop = chatWindow.scrollHeight;
}

function escapeHtml(text) {
  return String(text)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

function updateBattleMeta(data) {
  document.getElementById("round-counter").textContent = data.round ?? state.round;
  const pressureEl = document.getElementById("pressure-level");
  pressureEl.textContent = data.pressure_level ?? "High";
  pressureEl.className = `pressure-${(data.pressure_level ?? "high").toLowerCase()}`;
  document.getElementById("attack-tag").textContent = data.attack_tag ?? "—";
  state.round = data.round ?? state.round;

  const phaseEl = document.getElementById("battle-phase");
  if (phaseEl && data.battle_phase) {
    phaseEl.textContent = data.battle_phase;
    phaseEl.hidden = false;
  }
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
    setGlobalLoading(true, "Loading demo startup...");
    const data = await apiPost("/api/load-sample");
    fillStartupForm(data.startup);
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
    setGlobalLoading(true, "Starting pitch battle...");
    battleStatus.hidden = true;
    chatWindow.innerHTML = "";

    const payload = {
      mode: "pitch_battle",
      startup: getStartupPayload(),
      persona: state.persona,
      difficulty: "high",
      input_mode: "text",
      model_mode: "premium_nvidia",
    };

    const data = await apiPost("/api/start-session", payload);

    if (data.error) {
      showErrorBanner(data.error);
      return;
    }

    state.sessionId = data.session_id;
    state.round = data.round ?? 1;
    userInput.disabled = false;
    const submitBtn = document.getElementById("chat-form").querySelector("button[type=submit]");
    if (submitBtn) submitBtn.disabled = false;
    updateBattleMeta(data);
    const startBadge = data.model_ok ? "⚡ Premium Nemotron" : "Mock";
    appendMessage("ai", data.ai_message, `${data.attack_tag} · Round ${data.round} · ${startBadge}`);
    showScreen("battle");
    hideErrorBanner();
  } catch (error) {
    console.error(error);
    showErrorBanner("Failed to start battle. Check backend logs.");
  } finally {
    setGlobalLoading(false);
  }
}

export async function sendMessage() {
  const message = userInput.value.trim();
  if (!message || !state.sessionId) return;

  try {
    setGlobalLoading(true, "Sending answer...");
    userInput.value = "";
    appendMessage("user", message);

    const data = await apiPost("/api/chat-round", {
      session_id: state.sessionId,
      user_message: message,
    });

    if (data.error) {
      battleStatus.hidden = false;
      battleStatus.textContent = data.ai_message || data.error;
      return;
    }

    updateBattleMeta(data);
    const chatBadge = data.model_ok ? "⚡ Premium Nemotron" : "Mock";
    appendMessage("ai", data.ai_message, `${data.attack_tag} · Round ${data.round} · ${chatBadge}`);

    if (data.soft_round_limit_reached) {
      battleStatus.hidden = false;
      battleStatus.textContent = data.completion_message
        ?? "You have enough material for a scorecard. End Battle when ready.";
      battleStatus.style.color = "var(--gold)";
    }
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
    setGlobalLoading(true, "Generating scorecard...");
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
  chatWindow.innerHTML = "";
  userInput.value = "";
  showScreen("landing");
}

function renderScorecard(data) {
  const overall = data.overall ?? 0;
  document.getElementById("overall-score").textContent = overall;

  const overallLabelEl = document.getElementById("overall-label");
  if (overallLabelEl) {
    overallLabelEl.textContent = data.overall_label ?? "";
    overallLabelEl.hidden = !data.overall_label;
  }

  const sourceBadgeEl = document.getElementById("scorecard-source-badge");
  if (sourceBadgeEl) {
    const src = data.scorecard_source ?? "";
    sourceBadgeEl.textContent =
      src === "hybrid_claims_nemotron" ? "⚡ Claim-based score + Premium Nemotron coaching" :
      src === "hybrid_claims_local" ? "Claim-based local scorecard" :
      src === "nemotron" ? "⚡ Scored by Premium Nemotron" :
      src === "nemotron_repaired" ? "⚡ Scored by Premium Nemotron (repaired)" :
      src === "session_fallback" ? "Session-based scorecard (model unavailable)" :
      "Mock fallback scorecard";
    sourceBadgeEl.hidden = false;
  }

  const bars = document.getElementById("score-bars");
  bars.innerHTML = "";
  const scores = data.scores ?? {};

  Object.entries(scores).forEach(([key, value]) => {
    const row = document.createElement("div");
    row.className = "score-row";
    const dimLabel = key.replaceAll("_", " ");
    const scoreLabel = value.label ? `<span class="score-label">${escapeHtml(value.label)}</span>` : "";
    row.innerHTML = `
      <div class="score-row-head">
        <span>${dimLabel}${scoreLabel}</span>
        <strong>${value.score}</strong>
      </div>
      <div class="bar-track"><div class="bar-fill" style="width:${value.score}%"></div></div>
      <p class="score-reason">${escapeHtml(value.reason ?? "")}</p>
    `;
    bars.appendChild(row);
  });

  // Concrete signals summary
  const sigEl = document.getElementById("signals-summary");
  if (sigEl) {
    const css = data.concrete_signals_summary ?? {};
    const allSigs = [
      ...(css.numbers ?? []),
      ...(css.validation ?? []),
      ...(css.competitors ?? []),
      ...(css.revenue_signals ?? []),
      ...(css.technical_mechanisms ?? []),
    ].slice(0, 8);
    if (allSigs.length > 0) {
      sigEl.textContent = "Signals detected: " + allSigs.join(" · ");
      sigEl.hidden = false;
    } else {
      sigEl.hidden = true;
    }
  }

  // Reordered: improved content first, then answers
  document.getElementById("improved-answer").textContent = data.improved_answer ?? "";
  document.getElementById("improved-pitch").textContent = data.improved_pitch ?? "";
  document.getElementById("best-answer").textContent = data.best_answer ?? "";
  document.getElementById("weakest-answer").textContent = data.weakest_answer ?? "";

  const list = document.getElementById("top-questions");
  list.innerHTML = "";
  (data.top_3_questions ?? []).forEach((q) => {
    const li = document.createElement("li");
    li.textContent = q;
    list.appendChild(li);
  });
}

document.getElementById("btn-load-sample").addEventListener("click", loadSample);
document.getElementById("btn-go-setup").addEventListener("click", () => showScreen("setup"));
document.getElementById("btn-back-landing").addEventListener("click", () => showScreen("landing"));
document.getElementById("btn-start-battle").addEventListener("click", startSession);
document.getElementById("btn-end-battle").addEventListener("click", endBattle);
document.getElementById("btn-reset").addEventListener("click", resetBattle);
document.getElementById("btn-back-setup").addEventListener("click", () => showScreen("setup"));

document.getElementById("btn-view-conversation").addEventListener("click", () => {
  document.getElementById("btn-end-battle").hidden = true;
  document.getElementById("btn-back-scorecard").hidden = false;
  document.getElementById("chat-form").hidden = true;
  showScreen("battle");
  chatWindow.scrollTop = chatWindow.scrollHeight;
});

document.getElementById("btn-back-scorecard").addEventListener("click", () => {
  document.getElementById("btn-end-battle").hidden = false;
  document.getElementById("btn-back-scorecard").hidden = true;
  document.getElementById("chat-form").hidden = false;
  showScreen("scorecard");
});

document.querySelectorAll(".persona-card").forEach((card) => {
  card.addEventListener("click", () => {
    document.querySelectorAll(".persona-card").forEach((c) => c.classList.remove("selected"));
    card.classList.add("selected");
    state.persona = card.dataset.persona;
  });
});

document.getElementById("chat-form").addEventListener("submit", (event) => {
  event.preventDefault();
  sendMessage();
});

function boot() {
  console.log("PitchFight frontend booting...");
  setGlobalLoading(false);
  hideErrorBanner();

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
