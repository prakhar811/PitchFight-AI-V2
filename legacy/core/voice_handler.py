"""Voice input layer for PitchFight AI — Phase 7.

Converts spoken audio to confirmed text + delivery cues via Nemotron Omni API.
Does not replace the battle engine — only produces transcripts for existing flows.
"""

from __future__ import annotations

import base64
import binascii
import logging
import re
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import Any

from core import nvidia_client
from core import session_manager
from core.json_utils import parse_model_json, safe_json_parse
from core.nvidia_client import OmniAudioError

logger = logging.getLogger(__name__)

_FILLER_PATTERNS = [
    r"\bum\b", r"\buh\b", r"\buhm\b", r"\ber\b", r"\bah\b",
    r"\blike\b", r"\byou know\b", r"\bkind of\b", r"\bsort of\b",
    r"\bbasically\b", r"\bliterally\b", r"\bactually\b", r"\bso+\b",
    r"\bi mean\b", r"\bwell\b",
]

_VOICE_PITCH_PROMPT = """The founder just recorded an opening startup pitch.

Listen to the audio carefully and extract only what was actually said.

Return ONLY valid JSON.
First character must be {.
Last character must be }.
No markdown.
No explanation.
No reasoning.
Do not hallucinate.
Do not invent traction, users, revenue, competitors, or market data.
If a field was not mentioned, return an empty string.

Do NOT claim emotion, stress, anxiety, or psychological state detection.
Only report observable delivery cues such as filler words, pauses, pacing, repetition, self-corrections, and clarity.

Required JSON:

{
"transcript": "exact words spoken",
"extracted": {
"name": "startup name or empty string",
"problem": "problem described or empty string",
"target_users": "who they are building for or empty string",
"solution": "what the product does or empty string",
"why_ai": "why AI is needed or empty string",
"traction": "any validation/users/pilots mentioned or empty string",
"competitors": "any competitors named or empty string",
"ask": "what they are asking for or empty string"
},
"delivery_observations": {
"filler_words": ["list of filler words heard"],
"pace": "rushed / measured / slow / unclear",
"clarity": "one sentence observation based only on delivery",
"confidence_signal": "confident / mixed / hesitant / unclear based only on observable delivery cues",
"delivery_note": "one concise sentence"
},
"extraction_confidence": "high / medium / low"
}"""

_VOICE_TURN_PROMPT = """Transcribe this spoken battle answer exactly as spoken.

Return ONLY valid JSON.
First character must be {.
Last character must be }.
No markdown.
No explanation.
No reasoning.
Do not interpret or expand the answer.
Do not add words not spoken.

Do NOT claim emotion, stress, anxiety, or psychological state detection.
Only report observable delivery cues such as filler words, pauses, pacing, repetition, self-corrections, and clarity.

Required JSON:

{
"transcript": "exact words spoken",
"delivery_note": "one concise sentence about observable delivery cues. If clean, say Clean delivery.",
"word_count": 0,
"delivery_cues": {
"filler_words": [],
"pace": "rushed / measured / slow / unclear",
"clarity": "clear / mostly clear / unclear",
"repetition": "low / medium / high",
"self_corrections": 0,
"confidence_signal": "confident delivery / mixed delivery / hesitant delivery / unclear"
}
}"""

_EXTRACTED_FIELDS = (
    "name", "problem", "target_users", "solution",
    "why_ai", "traction", "competitors", "ask",
)

_WAV_RIFF = b"RIFF"
_WEBM_MAGIC = b"\x1aE\xdf\xa3"
_OGG_MAGIC = b"OggS"
_MP3_ID3 = b"ID3"

# Minimum decoded audio size to treat as a real recording. Anything smaller is an
# empty/instant tap that NVIDIA Omni rejects with HTTP 400. ~1s of webm/opus is several KB.
_MIN_AUDIO_BYTES = 1024
_MP3_SYNC = b"\xff\xfb"


def _detect_audio_magic(data: bytes) -> str:
    if len(data) >= 4 and data[:4] == _WAV_RIFF:
        return "wav"
    if len(data) >= 4 and data[:4] == _WEBM_MAGIC:
        return "webm"
    if len(data) >= 4 and data[:4] == _OGG_MAGIC:
        return "ogg"
    if len(data) >= 3 and data[:3] == _MP3_ID3:
        return "mp3"
    if len(data) >= 2 and data[:2] == _MP3_SYNC:
        return "mp3"
    return "unknown"


def _magic_hex(data: bytes, n: int = 8) -> str:
    return data[:n].hex() if data else ""


def _convert_audio_to_wav_ffmpeg(input_bytes: bytes, input_ext: str) -> bytes | None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return None
    with tempfile.TemporaryDirectory() as tmp:
        inp = Path(tmp) / f"input.{input_ext or 'webm'}"
        out = Path(tmp) / "output.wav"
        inp.write_bytes(input_bytes)
        cmd = [
            ffmpeg,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(inp),
            "-ar",
            "16000",
            "-ac",
            "1",
            "-c:a",
            "pcm_s16le",
            str(out),
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, timeout=45, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            logger.warning("voice_handler: ffmpeg conversion failed — %s", exc)
            return None
        if result.returncode != 0 or not out.is_file():
            stderr = (result.stderr or b"").decode("utf-8", errors="replace")[:200]
            logger.warning("voice_handler: ffmpeg exit=%s stderr=%s", result.returncode, stderr)
            return None
        return out.read_bytes()


def normalize_audio_for_omni(
    audio_base64: str,
    audio_format: str,
    mode: str = "voice_extraction",
) -> dict[str, Any]:
    """Decode browser audio and normalize to WAV for NVIDIA Omni when needed."""
    fmt = str(audio_format or "webm").strip().lower().lstrip(".")
    if fmt not in {"webm", "wav", "mp3", "m4a", "ogg"}:
        return {
            "error": f"Unsupported audio_format: {fmt}",
            "audio_format": fmt,
            "mode": mode,
        }

    try:
        raw = base64.b64decode(audio_base64.strip(), validate=True)
    except (binascii.Error, ValueError) as exc:
        return {
            "error": "Invalid base64 audio payload",
            "detail": str(exc),
            "audio_format": fmt,
            "mode": mode,
        }

    if not raw:
        return {"error": "Decoded audio is empty", "audio_format": fmt, "mode": mode}

    # Guard against empty/instant taps (e.g. a few-byte payload). These are not real
    # recordings and NVIDIA Omni rejects them with HTTP 400 ("Invalid audio file").
    # Catch it here and return a clean, user-facing message instead of an API error.
    if len(raw) < _MIN_AUDIO_BYTES:
        logger.info(
            "voice_handler: rejecting too-small audio mode=%s bytes=%d (min=%d)",
            mode, len(raw), _MIN_AUDIO_BYTES,
        )
        return {
            "error": "That recording was too short. Tap the mic, speak, then tap again to stop.",
            "audio_format": fmt,
            "byte_size": len(raw),
            "mode": mode,
        }

    detected = _detect_audio_magic(raw)
    logger.info(
        "voice_handler: normalize audio mode=%s declared=%s detected=%s bytes=%d magic=%s",
        mode,
        fmt,
        detected,
        len(raw),
        _magic_hex(raw),
    )

    if detected == "wav" or (fmt == "wav" and raw[:4] == _WAV_RIFF):
        return {
            "audio_base64": base64.b64encode(raw).decode("ascii"),
            "audio_format": "wav",
            "source_format": fmt,
            "byte_size": len(raw),
            "converted": fmt != "wav" and detected == "wav",
            "mode": mode,
        }

    source_ext = detected if detected != "unknown" else fmt
    wav_bytes = _convert_audio_to_wav_ffmpeg(raw, source_ext)
    if wav_bytes and wav_bytes[:4] == _WAV_RIFF:
        logger.info(
            "voice_handler: converted %s → wav (%d → %d bytes)",
            source_ext,
            len(raw),
            len(wav_bytes),
        )
        return {
            "audio_base64": base64.b64encode(wav_bytes).decode("ascii"),
            "audio_format": "wav",
            "source_format": fmt,
            "byte_size": len(wav_bytes),
            "converted": True,
            "mode": mode,
        }

    # ffmpeg unavailable or conversion failed — pass through original browser audio
    # (restores pre-stability behavior; Omni accepts webm on many setups).
    send_fmt = source_ext if source_ext != "unknown" else fmt
    logger.info(
        "voice_handler: passthrough audio mode=%s format=%s bytes=%d (ffmpeg=%s)",
        mode,
        send_fmt,
        len(raw),
        bool(shutil.which("ffmpeg")),
    )
    return {
        "audio_base64": base64.b64encode(raw).decode("ascii"),
        "audio_format": send_fmt,
        "source_format": fmt,
        "byte_size": len(raw),
        "converted": False,
        "mode": mode,
    }


def _call_omni_with_normalized_audio(
    prompt: str,
    audio_base64: str,
    audio_format: str,
    mode: str,
) -> str | dict[str, Any]:
    normalized = normalize_audio_for_omni(audio_base64, audio_format, mode=mode)
    if normalized.get("error"):
        return normalized

    def _invoke(payload: dict[str, Any]) -> str:
        return nvidia_client.call_omni_audio_json(
            prompt,
            payload["audio_base64"],
            payload["audio_format"],
            mode=mode,
            source_format=payload.get("source_format", audio_format),
            decoded_bytes=payload.get("byte_size"),
        )

    try:
        return _invoke(normalized)
    except OmniAudioError as exc:
        # If passthrough failed and ffmpeg can convert, retry once as WAV.
        if not normalized.get("converted"):
            raw_bytes = base64.b64decode(normalized["audio_base64"])
            detected = _detect_audio_magic(raw_bytes)
            source_ext = detected if detected != "unknown" else normalized.get("source_format", audio_format)
            wav_bytes = _convert_audio_to_wav_ffmpeg(raw_bytes, source_ext)
            if wav_bytes and wav_bytes[:4] == _WAV_RIFF:
                logger.info("voice_handler: Omni rejected passthrough; retrying as wav")
                retry_payload = {
                    "audio_base64": base64.b64encode(wav_bytes).decode("ascii"),
                    "audio_format": "wav",
                    "source_format": normalized.get("source_format", audio_format),
                    "byte_size": len(wav_bytes),
                    "converted": True,
                }
                try:
                    return _invoke(retry_payload)
                except OmniAudioError as retry_exc:
                    err = retry_exc.to_error_dict()
                    err["source_format"] = normalized.get("source_format", audio_format)
                    err["converted"] = True
                    err["error"] = "Voice transcription failed. Try recording again or type your answer."
                    return err

        err = exc.to_error_dict()
        err["source_format"] = normalized.get("source_format", audio_format)
        err["converted"] = normalized.get("converted", False)
        err["error"] = "Voice transcription failed. Try recording again or type your answer."
        return err
    except ValueError as exc:
        return {"error": str(exc)}
    except RuntimeError as exc:
        return {"error": str(exc)}


def count_filler_words(transcript: str) -> list[str]:
    """Return filler words/phrases found in transcript (case-insensitive)."""
    if not transcript:
        return []
    text = transcript.lower()
    found: list[str] = []
    for pattern in _FILLER_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            label = pattern.strip(r"\b").replace("\\b", "")
            if label not in found:
                found.append(label)
    return found


def estimate_word_count(transcript: str) -> int:
    """Count words in transcript."""
    if not transcript:
        return 0
    return len(re.findall(r"\b\w+\b", transcript))


def detect_self_corrections(transcript: str) -> int:
    """Count simple self-correction cues in transcript."""
    if not transcript:
        return 0
    patterns = [
        r"\bi mean\b", r"\bwait\b", r"\bsorry\b", r"\bno,\s", r"\bactually\b",
        r"\blet me rephrase\b", r"\bwhat i meant\b",
    ]
    count = 0
    lower = transcript.lower()
    for p in patterns:
        count += len(re.findall(p, lower))
    return count


def _detect_repeated_phrases(transcript: str) -> int:
    """Count repeated 3-word phrases (simple repetition signal)."""
    words = re.findall(r"\b\w+\b", (transcript or "").lower())
    if len(words) < 6:
        return 0
    trigrams: dict[str, int] = {}
    for i in range(len(words) - 2):
        tri = " ".join(words[i : i + 3])
        trigrams[tri] = trigrams.get(tri, 0) + 1
    return sum(1 for c in trigrams.values() if c > 1)


def sanitize_voice_json(data: dict[str, Any]) -> dict[str, Any]:
    """Normalize voice JSON fields with safe delivery-only wording."""
    if not isinstance(data, dict):
        return {}
    out = dict(data)
    out["transcript"] = str(out.get("transcript", "")).strip()
    extracted = out.get("extracted")
    if isinstance(extracted, dict):
        out["extracted"] = {
            k: str(extracted.get(k, "")).strip() for k in _EXTRACTED_FIELDS
        }
    delivery = out.get("delivery_observations")
    if isinstance(delivery, dict):
        fillers = delivery.get("filler_words", [])
        out["delivery_observations"] = {
            "filler_words": [str(f).strip() for f in fillers if str(f).strip()][:20]
            if isinstance(fillers, list) else [],
            "pace": str(delivery.get("pace", "")).strip() or "unclear",
            "clarity": str(delivery.get("clarity", "")).strip(),
            "confidence_signal": str(delivery.get("confidence_signal", "")).strip() or "unclear",
            "delivery_note": str(delivery.get("delivery_note", "")).strip(),
        }
    conf = str(out.get("extraction_confidence", "")).strip().lower()
    if conf not in ("high", "medium", "low"):
        conf = "medium"
    out["extraction_confidence"] = conf
    return out


def _sanitize_turn_json(data: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(data, dict):
        return {}
    transcript = str(data.get("transcript", "")).strip()
    cues_raw = data.get("delivery_cues", {})
    cues: dict[str, Any] = {}
    if isinstance(cues_raw, dict):
        fillers = cues_raw.get("filler_words", [])
        cues = {
            "filler_words": [str(f).strip() for f in fillers if str(f).strip()][:20]
            if isinstance(fillers, list) else [],
            "pace": str(cues_raw.get("pace", "")).strip() or "unclear",
            "clarity": str(cues_raw.get("clarity", "")).strip() or "unclear",
            "repetition": str(cues_raw.get("repetition", "")).strip() or "low",
            "self_corrections": int(cues_raw.get("self_corrections", 0) or 0),
            "confidence_signal": str(cues_raw.get("confidence_signal", "")).strip() or "unclear",
        }
    local_fillers = count_filler_words(transcript)
    if not cues.get("filler_words") and local_fillers:
        cues["filler_words"] = local_fillers
    if cues.get("self_corrections", 0) == 0:
        cues["self_corrections"] = detect_self_corrections(transcript)
    rep_count = _detect_repeated_phrases(transcript)
    if cues.get("repetition") == "low" and rep_count >= 2:
        cues["repetition"] = "medium"
    return {
        "transcript": transcript,
        "delivery_note": str(data.get("delivery_note", "")).strip() or "Clean delivery.",
        "word_count": estimate_word_count(transcript),
        "delivery_cues": cues,
    }


def _parse_pitch_json(raw: str) -> dict[str, Any] | None:
    parsed, _ = parse_model_json(raw)
    if not isinstance(parsed, dict) or not parsed:
        parsed = safe_json_parse(raw)
    if not isinstance(parsed, dict) or not parsed:
        return None
    transcript = str(parsed.get("transcript", "")).strip()
    if not transcript:
        return None
    sanitized = sanitize_voice_json(parsed)
    sanitized["transcript"] = transcript
    return sanitized


def _parse_turn_json(raw: str) -> dict[str, Any] | None:
    parsed, _ = parse_model_json(raw)
    if not isinstance(parsed, dict) or not parsed:
        parsed = safe_json_parse(raw)
    if not isinstance(parsed, dict) or not parsed:
        return None
    transcript = str(parsed.get("transcript", "")).strip()
    if not transcript:
        return None
    return _sanitize_turn_json(parsed)


def _repair_pitch_json(raw_bad: str) -> dict[str, Any] | None:
    repair_prompt = (
        "Convert the input into valid JSON matching this schema exactly. "
        "Return ONLY JSON. First char { last char }.\n"
        '{"transcript":"","extracted":{"name":"","problem":"","target_users":"",'
        '"solution":"","why_ai":"","traction":"","competitors":"","ask":""},'
        '"delivery_observations":{"filler_words":[],"pace":"","clarity":"",'
        '"confidence_signal":"","delivery_note":""},"extraction_confidence":"medium"}\n\n'
        + raw_bad[:4000]
    )
    try:
        content = nvidia_client.generate_nemotron_response(
            [{"role": "user", "content": repair_prompt}],
            mode="voice_extraction_repair",
        )
        return _parse_pitch_json(content)
    except Exception as exc:
        logger.warning("voice_handler: pitch repair failed — %s", exc)
        return None


def _repair_turn_json(raw_bad: str) -> dict[str, Any] | None:
    repair_prompt = (
        "Convert the input into valid JSON matching this schema exactly. "
        "Return ONLY JSON. First char { last char }.\n"
        '{"transcript":"","delivery_note":"","word_count":0,'
        '"delivery_cues":{"filler_words":[],"pace":"","clarity":"",'
        '"repetition":"low","self_corrections":0,"confidence_signal":""}}\n\n'
        + raw_bad[:3000]
    )
    try:
        content = nvidia_client.generate_nemotron_response(
            [{"role": "user", "content": repair_prompt}],
            mode="voice_turn_repair",
        )
        return _parse_turn_json(content)
    except Exception as exc:
        logger.warning("voice_handler: turn repair failed — %s", exc)
        return None


def process_voice_pitch(audio_base64: str, audio_format: str) -> dict[str, Any]:
    """Opening spoken pitch → transcript + extracted startup fields + delivery cues."""
    if not nvidia_client.is_configured():
        return {"error": "NVIDIA_API_KEY is not configured on the server."}

    raw = _call_omni_with_normalized_audio(
        _VOICE_PITCH_PROMPT, audio_base64, audio_format, mode="voice_extraction"
    )
    if isinstance(raw, dict):
        return raw

    parsed = _parse_pitch_json(raw)
    if parsed is None:
        logger.warning("voice_handler: pitch parse failed, attempting repair")
        parsed = _repair_pitch_json(raw)

    if parsed is None:
        return {"error": "Could not parse voice pitch response from Nemotron Omni."}

    return parsed


def process_voice_turn(
    session_id: str,
    audio_base64: str,
    audio_format: str,
) -> dict[str, Any]:
    """One battle answer audio → transcript + delivery note (pending confirmation)."""
    session = session_manager.get_session(session_id)
    if not session:
        return {"error": "Session not found", "session_id": session_id}

    if not nvidia_client.is_configured():
        return {"error": "NVIDIA_API_KEY is not configured on the server.", "session_id": session_id}

    raw = _call_omni_with_normalized_audio(
        _VOICE_TURN_PROMPT, audio_base64, audio_format, mode="voice_turn"
    )
    if isinstance(raw, dict):
        raw["session_id"] = session_id
        return raw

    parsed = _parse_turn_json(raw)
    if parsed is None:
        logger.warning("voice_handler: turn parse failed, attempting repair")
        parsed = _repair_turn_json(raw)

    if parsed is None:
        return {"error": "Could not parse voice turn response from Nemotron Omni.", "session_id": session_id}

    voice_turn_id = str(uuid.uuid4())
    transcript = parsed["transcript"]
    fillers = parsed["delivery_cues"].get("filler_words") or count_filler_words(transcript)
    filler_count = len(fillers)

    turn_record = {
        "voice_turn_id": voice_turn_id,
        "transcript": transcript,
        "delivery_note": parsed.get("delivery_note", ""),
        "word_count": parsed.get("word_count", estimate_word_count(transcript)),
        "delivery_cues": parsed.get("delivery_cues", {}),
        "filler_word_count": filler_count,
        "confirmed": False,
    }
    session_manager.store_pending_voice_turn(session_id, turn_record)

    return {
        "session_id": session_id,
        "voice_turn_id": voice_turn_id,
        "transcript": transcript,
        "delivery_note": turn_record["delivery_note"],
        "word_count": turn_record["word_count"],
        "delivery_cues": turn_record["delivery_cues"],
    }


def confirm_voice_turn(
    session_id: str,
    voice_turn_id: str,
    final_transcript: str,
) -> bool:
    """Mark a pending voice turn as confirmed with the user's final transcript."""
    return session_manager.confirm_voice_turn(session_id, voice_turn_id, final_transcript)


def _is_generic_delivery_note(note: str) -> bool:
    """Skip filler delivery notes that clutter the scorecard UI."""
    n = (note or "").strip().lower().rstrip(".")
    return n in ("clean delivery", "clean delivery.", "")


def build_voice_delivery_summary(session: dict) -> dict[str, Any] | None:
    """Aggregate confirmed voice turns into a scorecard delivery summary (local only)."""
    confirmed = session.get("confirmed_voice_turns") or []
    voice_pitch = session.get("voice_pitch")
    if not confirmed and not voice_pitch:
        return None

    all_fillers: list[str] = []
    delivery_notes: list[str] = []
    pace_counts: dict[str, int] = {}
    clarity_signals: list[str] = []
    confidence_signals: list[str] = []

    if isinstance(voice_pitch, dict):
        obs = voice_pitch.get("delivery_observations") or {}
        if isinstance(obs, dict):
            note = str(obs.get("delivery_note", "")).strip()
            if note and not _is_generic_delivery_note(note):
                delivery_notes.append(f"Opening pitch: {note}")
            for f in obs.get("filler_words") or []:
                if str(f).strip():
                    all_fillers.append(str(f).strip())
            pace = str(obs.get("pace", "")).strip()
            if pace:
                pace_counts[pace] = pace_counts.get(pace, 0) + 1
            clarity = str(obs.get("clarity", "")).strip()
            if clarity:
                clarity_signals.append(clarity)
            conf = str(obs.get("confidence_signal", "")).strip()
            if conf:
                confidence_signals.append(conf)

    for turn in confirmed:
        if not isinstance(turn, dict):
            continue
        note = str(turn.get("delivery_note", "")).strip()
        if note and not _is_generic_delivery_note(note):
            delivery_notes.append(note)
        cues = turn.get("delivery_cues") or {}
        if isinstance(cues, dict):
            for f in cues.get("filler_words") or []:
                if str(f).strip():
                    all_fillers.append(str(f).strip())
            pace = str(cues.get("pace", "")).strip()
            if pace:
                pace_counts[pace] = pace_counts.get(pace, 0) + 1
            clarity = str(cues.get("clarity", "")).strip()
            if clarity:
                clarity_signals.append(clarity)
            conf = str(cues.get("confidence_signal", "")).strip()
            if conf:
                confidence_signals.append(conf)

    filler_unique = list(dict.fromkeys(all_fillers))
    total_fillers = len(all_fillers)
    avg_pace = max(pace_counts, key=pace_counts.get) if pace_counts else "unclear"

    if total_fillers == 0 and len(confirmed) >= 2:
        overall = "Voice delivery was generally clear across your spoken answers."
    elif total_fillers > 5:
        overall = (
            f"Filler words appeared often ({total_fillers} total). "
            "Practice pausing briefly instead of using fillers before key claims."
        )
    elif delivery_notes:
        overall = "Review the delivery notes below and practice smoother pacing on your weakest round."
    else:
        overall = "Voice turns recorded — delivery was acceptable for a practice session."

    return {
        "total_voice_turns": len(confirmed),
        "total_filler_words": total_fillers,
        "filler_word_list": filler_unique[:12],
        "delivery_notes": list(dict.fromkeys(delivery_notes))[:4],
        "average_pace": avg_pace,
        "clarity_signal": clarity_signals[-1] if clarity_signals else "unclear",
        "confidence_signal": confidence_signals[-1] if confidence_signals else "unclear",
        "overall_delivery_feedback": overall,
    }
