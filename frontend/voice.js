/** Voice recording + API helpers for PitchFight AI Phase 7. */

let mediaRecorder = null;
let audioChunks = [];
let recordTimerInterval = null;
let recordStartMs = 0;
let currentRecordMode = null; // "pitch" | "turn"

const MIME_CANDIDATES = [
  "audio/webm;codecs=opus",
  "audio/webm",
  "audio/ogg;codecs=opus",
  "audio/mp4",
];

function pickMimeType() {
  if (!window.MediaRecorder) return "";
  for (const m of MIME_CANDIDATES) {
    if (MediaRecorder.isTypeSupported(m)) return m;
  }
  return "";
}

function mimeToFormat(mime) {
  if (!mime) return "webm";
  if (mime.includes("ogg")) return "ogg";
  if (mime.includes("mp4")) return "m4a";
  return "webm";
}

export function blobToBase64(blob) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onloadend = () => {
      const dataUrl = reader.result || "";
      const base64 = String(dataUrl).split(",")[1] || "";
      resolve(base64);
    };
    reader.onerror = reject;
    reader.readAsDataURL(blob);
  });
}

async function apiPost(path, body) {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(data.error || data.detail || response.statusText);
  }
  return data;
}

export async function sendVoicePitch(base64, format) {
  return apiPost("/api/voice-pitch", { audio: base64, audio_format: format });
}

export async function sendVoiceTurn(sessionId, base64, format) {
  return apiPost("/api/voice-turn", {
    session_id: sessionId,
    audio: base64,
    audio_format: format,
  });
}

function formatTimer(seconds) {
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}

function _retryModeActive() {
  const overlay = document.getElementById("retry-overlay");
  return overlay && !overlay.hidden;
}

function _dealModeActive() {
  const dealScreen = document.getElementById("screen-deal");
  return dealScreen?.classList.contains("active");
}

function _voiceContext() {
  if (_dealModeActive()) return "deal";
  if (_retryModeActive()) return "retry";
  return "battle";
}

function setRecordingUI(active, mode) {
  const pitchBtn = document.getElementById("btn-voice-pitch-record");
  const turnBtn = document.getElementById("btn-voice-turn-record");
  const retryBtn = document.getElementById("btn-retry-voice-record");
  const dealBtn = document.getElementById("btn-deal-voice-record");
  const pitchStatus = document.getElementById("voice-pitch-status");
  const turnStatus = document.getElementById("voice-turn-status");
  const retryStatus = document.getElementById("retry-voice-status");
  const dealStatus = document.getElementById("deal-voice-status");
  const pitchTimer = document.getElementById("voice-pitch-timer");
  const turnTimer = document.getElementById("voice-turn-timer");
  const retryTimer = document.getElementById("retry-voice-timer");
  const dealTimer = document.getElementById("deal-voice-timer");
  const ctx = _voiceContext();
  const retryRecording = active && mode === "turn" && ctx === "retry";
  const dealRecording = active && mode === "turn" && ctx === "deal";

  [pitchBtn, turnBtn, retryBtn, dealBtn].forEach((btn) => btn?.classList.remove("recording"));
  if (active && mode === "pitch" && pitchBtn) pitchBtn.classList.add("recording");
  if (active && mode === "turn" && ctx === "battle" && turnBtn) turnBtn.classList.add("recording");
  if (retryRecording && retryBtn) retryBtn.classList.add("recording");
  if (dealRecording && dealBtn) dealBtn.classList.add("recording");

  if (pitchStatus) pitchStatus.textContent = active && mode === "pitch" ? "Recording…" : "";
  if (turnStatus) turnStatus.textContent = active && mode === "turn" && ctx === "battle" ? "Recording…" : "";
  if (retryStatus) retryStatus.textContent = retryRecording ? "Recording…" : "";
  if (dealStatus) dealStatus.textContent = dealRecording ? "Recording…" : "";
  if (!active) {
    if (pitchTimer) pitchTimer.textContent = "0:00";
    if (turnTimer) turnTimer.textContent = "0:00";
    if (retryTimer) retryTimer.textContent = "0:00";
    if (dealTimer) dealTimer.textContent = "0:00";
  }
}

function startTimer(el) {
  recordStartMs = Date.now();
  clearInterval(recordTimerInterval);
  recordTimerInterval = setInterval(() => {
    const sec = Math.floor((Date.now() - recordStartMs) / 1000);
    if (el) el.textContent = formatTimer(sec);
  }, 250);
}

function stopTimer() {
  clearInterval(recordTimerInterval);
  recordTimerInterval = null;
}

async function startRecording(mode) {
  if (mediaRecorder?.state === "recording") return;
  currentRecordMode = mode;
  const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  const mime = pickMimeType();
  mediaRecorder = mime ? new MediaRecorder(stream, { mimeType: mime }) : new MediaRecorder(stream);
  audioChunks = [];
  mediaRecorder.ondataavailable = (e) => {
    if (e.data.size > 0) audioChunks.push(e.data);
  };
  mediaRecorder.start(200);
  let timerEl = document.getElementById("voice-pitch-timer");
  if (mode === "turn") {
    const ctx = _voiceContext();
    timerEl = ctx === "deal"
      ? document.getElementById("deal-voice-timer")
      : ctx === "retry"
        ? document.getElementById("retry-voice-timer")
        : document.getElementById("voice-turn-timer");
  }
  startTimer(timerEl);
  setRecordingUI(true, mode);
}

async function stopRecording() {
  if (!mediaRecorder || mediaRecorder.state !== "recording") {
    return { blob: null, format: "webm", mode: currentRecordMode };
  }
  const mode = currentRecordMode;
  const mime = mediaRecorder.mimeType || "audio/webm";
  const format = mimeToFormat(mime);

  return new Promise((resolve) => {
    mediaRecorder.onstop = () => {
      stopTimer();
      setRecordingUI(false, mode);
      mediaRecorder.stream.getTracks().forEach((t) => t.stop());
      const blob = new Blob(audioChunks, { type: mime });
      audioChunks = [];
      resolve({ blob, format, mode });
    };
    mediaRecorder.stop();
  });
}

async function _handleTurnRecording(handlers, onComplete) {
  if (mediaRecorder?.state === "recording" && currentRecordMode === "turn") {
    const { blob, format } = await stopRecording();
    if (!blob?.size) throw new Error("No audio captured.");
    const base64 = await blobToBase64(blob);
    const sessionId = handlers.getSessionId?.();
    if (!sessionId) throw new Error("No active session.");
    const data = await sendVoiceTurn(sessionId, base64, format);
    if (data.error) throw new Error(data.error);
    onComplete?.(data);
  } else {
    await startRecording("turn");
  }
}

export function initVoiceUI(handlers = {}) {
  const {
    onPitchComplete,
    onTurnComplete,
    onRetryTurnComplete,
    onDealTurnComplete,
    onError,
  } = handlers;

  const resolveTurnComplete = (data) => {
    const ctx = handlers.getUiMode?.() || _voiceContext();
    if (ctx === "deal") onDealTurnComplete?.(data);
    else if (ctx === "retry") (onRetryTurnComplete ?? onTurnComplete)?.(data);
    else onTurnComplete?.(data);
  };

  document.getElementById("btn-voice-pitch-record")?.addEventListener("click", async () => {
    try {
      if (mediaRecorder?.state === "recording" && currentRecordMode === "pitch") {
        const { blob, format } = await stopRecording();
        if (!blob?.size) throw new Error("No audio captured.");
        const base64 = await blobToBase64(blob);
        const data = await sendVoicePitch(base64, format);
        if (data.error) throw new Error(data.error);
        onPitchComplete?.(data);
      } else {
        await startRecording("pitch");
      }
    } catch (err) {
      onError?.(err.message || String(err));
    }
  });

  document.getElementById("btn-voice-pitch-cancel")?.addEventListener("click", async () => {
    if (mediaRecorder?.state === "recording") {
      mediaRecorder.onstop = () => {
        stopTimer();
        setRecordingUI(false, "pitch");
        mediaRecorder?.stream?.getTracks().forEach((t) => t.stop());
      };
      mediaRecorder.stop();
    }
  });

  document.getElementById("btn-voice-turn-record")?.addEventListener("click", async () => {
    try {
      await _handleTurnRecording(handlers, resolveTurnComplete);
    } catch (err) {
      onError?.(err.message || String(err));
    }
  });

  document.getElementById("btn-retry-voice-record")?.addEventListener("click", async () => {
    try {
      await _handleTurnRecording(handlers, resolveTurnComplete);
    } catch (err) {
      onError?.(err.message || String(err));
    }
  });

  document.getElementById("btn-deal-voice-record")?.addEventListener("click", async () => {
    try {
      await _handleTurnRecording(handlers, resolveTurnComplete);
    } catch (err) {
      onError?.(err.message || String(err));
    }
  });

  document.getElementById("btn-voice-turn-cancel")?.addEventListener("click", async () => {
    if (mediaRecorder?.state === "recording") {
      mediaRecorder.onstop = () => {
        stopTimer();
        setRecordingUI(false, "turn");
        mediaRecorder?.stream?.getTracks().forEach((t) => t.stop());
      };
      mediaRecorder.stop();
    }
    document.getElementById("voice-turn-preview")?.setAttribute("hidden", "");
  });
}

export function startVoicePitchRecording() {
  return startRecording("pitch");
}

export function stopVoicePitchRecording() {
  return stopRecording();
}

export function startVoiceTurnRecording() {
  return startRecording("turn");
}

export function stopVoiceTurnRecording() {
  return stopRecording();
}
