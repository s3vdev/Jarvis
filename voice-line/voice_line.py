#!/usr/bin/env python3
"""Jarvis voice line.

Speech to Hermes and the only writer of the signal bus the visualizer reads.

    listen (mic + VAD) -> transcribe (Whisper) -> local skill or Hermes -> speak

Signal bus in ~/voice-line, written here, read-only elsewhere:
    .voice_state     text: idle | listening | thinking | speaking
    .voice_waveform  json: {"ts": <unix float>, "samples": [64 floats]}
    .voice_alert     exists only while an alert is active

Usage:
    python voice_line.py            speak, a pause sends the question
    python voice_line.py --daemon   same, without a Terminal (menu bar session)
    python voice_line.py --ptt      press-Enter-to-talk mode
    python voice_line.py --check    verify dependencies / mic / brain and exit
"""

import asyncio
import json
import os
import re
import signal
import subprocess
import sys
import tempfile
import threading
import time
import wave

try:
    sys.stdout.reconfigure(encoding="utf-8")   # avoid cp1252 mojibake in the console
except Exception:  # noqa: BLE001
    pass


def clean_text(s):
    """Normalize smart punctuation so the console and TTS don't choke (â€” etc.)."""
    for a, b in (("—", " - "), ("–", "-"), ("’", "'"), ("‘", "'"),
                 ("“", '"'), ("”", '"'), ("…", "..."), ("•", "-")):
        s = s.replace(a, b)
    return s


def strip_markdown(s):
    """Turn any markdown the brain emits into plain speech (TTS reads symbols aloud otherwise)."""
    s = re.sub(r"```.*?```", " ", s, flags=re.S)          # code fences
    s = s.replace("`", "")                                 # inline code
    s = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", s)         # [text](url) -> text
    s = re.sub(r"\*+", "", s)                              # **bold** *italic*
    out = []
    for ln in s.splitlines():
        ln = ln.strip()
        ln = re.sub(r"^#+\s*", "", ln)                     # headers
        ln = re.sub(r"^>\s*", "", ln)                      # quotes
        ln = re.sub(r"^[-•]\s+", "", ln)                   # bullets
        ln = re.sub(r"^\d+\.\s+", "", ln)                  # numbered list
        if ln:
            out.append(ln)
    s = ". ".join(out)
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r"\.\s*\.", ".", s)                         # collapse ". ."
    return s.replace(":.", ":")


def for_speech(s):
    return strip_markdown(clean_text(s))

# --- Config -----------------------------------------------------------------
BUS_DIR = os.path.join(os.path.expanduser("~"), "voice-line")
STATE_FILE = os.path.join(BUS_DIR, ".voice_state")
WAVEFORM_FILE = os.path.join(BUS_DIR, ".voice_waveform")
ALERT_FILE = os.path.join(BUS_DIR, ".voice_alert")
STATUS_FILE = os.path.join(BUS_DIR, ".voice_status")   # human-readable line shown in the visualizer
PAUSE_FILE = os.path.join(BUS_DIR, ".voice_pause")     # written by the Mac window; voice line is the only reader
LOAD_FILE = os.path.join(BUS_DIR, ".voice_load")

# repo root (this file lives in voice-line/) — Jarvis workspace
from jarvis_config import code_root, data_root, find_hermes, public_hermes
CODE_DIR = str(code_root())
BRAIN_DIR = str(data_root())
# Local memory folder. Hermes does not read or write it automatically.
VAULT_DIR = os.path.join(BRAIN_DIR, "memory")

WHISPER_SIZE = "large-v3-turbo"  # German names need more than base; turbo stays quick on Apple Silicon

SAMPLE_RATE = 16000
VAD_ON = 0.016          # ignore keyboard/room ticks; real speech on this mic was ~0.28
SILENCE_MS = 640        # keep the last name or city from being cut off
MIN_SPEECH_S = 0.40     # ignore clicks and short noise before transcription
MIN_PEAK = 0.028        # a whole clip quieter than this is room noise, not a question
START_FRAMES = 7        # ~210ms of energy before the orb leaves CONNECTED
START_TIMEOUT_S = 6     # if no speech starts within this, give up the turn
MAX_UTTER_S = 15        # hard cap on one utterance
MIC_GAIN = 5.0          # waveform liveliness while listening
TTS_GAIN = 3.5          # waveform liveliness while speaking
TTS_VOICE = "de-DE-ConradNeural"   # default; the settings panel can pick Killian or Florian
TTS_PLAY_RATE = 48000              # matches the Mac speakers; 16 kHz sounded thin and rough
TTS_FALLBACK_VOICE = "Anna (Deutsch (Deutschland))"
TTS_RATE = 170                     # words-per-minute for the offline fallback only
POST_SPEECH_GAP_S = 0.40 # let the speakers die before the mic opens again
WAVEFORM_EVERY_S = 0.08 # disk writes every 30ms made the orb hitch
SETTINGS_FILE = os.path.join(BUS_DIR, ".voice_settings")
PREVIEW_FILE = os.path.join(BUS_DIR, ".voice_preview")
HERMES_FILE = os.path.join(BUS_DIR, ".voice_hermes")
CONFIRM_FILE = os.path.join(BUS_DIR, ".voice_confirm")
CONFIRM_REPLY_FILE = os.path.join(BUS_DIR, ".voice_confirm_reply")
PREVIEW_MARK = "preview"
VOICES = (
    "de-DE-ConradNeural",
    "de-DE-KillianNeural",
    "de-DE-FlorianMultilingualNeural",
)
SENSITIVITY = {
    "leise": {"vad": 0.010, "peak": 0.018, "start": 5},
    "normal": {"vad": 0.016, "peak": 0.028, "start": 7},
    "fest": {"vad": 0.028, "peak": 0.045, "start": 9},
}
WAKE_MODES = ("aus", "an")
VOLUMES = {"leise": 0.40, "normal": 0.80, "laut": 1.0}
ANIMATIONS = ("kugel", "radar", "iris")
DEFAULT_SETTINGS = {
    "voice": TTS_VOICE,
    "sensitivity": "normal",
    "wake": "aus",
    "volume": "normal",
    "animation": "kugel",
}
STATUS_READY = "JARVIS CONNECTED"
STATUS_LISTEN = "Ich höre zu"
STATUS_THINK = "Einen Moment"
STATUS_PAUSED = "PAUSED"
_LOCAL_PAUSE = re.compile(
    r"^(?:(?:hey|hi|hallo|ok|okay)\s+)?"
    r"(?:(?:jarvis|javis|jarves|jarwis|dscharvis|tscharvis)\s+)?"
    r"(?:stopp|stop|pause|pausiere|ruhe|sei still)(?:\s+bitte)?$",
    re.IGNORECASE,
)

# --- Core deps (fail loudly with guidance) ----------------------------------
try:
    import numpy as np
    import sounddevice as sd
except Exception as e:  # noqa: BLE001
    print("[voice] missing core dependency:", e)
    print("        pip install -r requirements.txt")
    if "--check" not in sys.argv:
        sys.exit(1)


# --- Bus writer (atomic-ish, this process is the sole writer) ----------------
def ensure_bus():
    os.makedirs(BUS_DIR, exist_ok=True)


def write_state(state):
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            f.write(state)
    except OSError:
        pass


def write_status(msg):
    """A short human line the visualizer shows (boot progress, subtitles)."""
    try:
        with open(STATUS_FILE, "w", encoding="utf-8") as f:
            f.write(msg)
    except OSError:
        pass


_load_pct = 0


def write_load_progress(pct):
    """Boot bar in the window. Never decreases so the meter does not jump back."""
    global _load_pct
    try:
        value = max(0, min(100, int(pct)))
    except (TypeError, ValueError):
        return
    if value < _load_pct:
        return
    _load_pct = value
    try:
        with open(LOAD_FILE, "w", encoding="utf-8") as handle:
            handle.write(str(value))
    except OSError:
        pass
    write_status("Sprachmodell %d%%" % value)


def is_paused():
    """True when the Mac window or a spoken stop asked the mic to stay closed."""
    try:
        return os.path.exists(PAUSE_FILE)
    except OSError:
        return False


def request_pause():
    """Pause from a spoken stop. The window and voice line share this file."""
    try:
        with open(PAUSE_FILE, "w", encoding="utf-8") as handle:
            handle.write("1")
    except OSError:
        pass
    try:
        sd.stop()
    except Exception:  # noqa: BLE001
        pass
    write_state("idle")
    write_status(STATUS_PAUSED)


def local_action(text):
    """Spoken controls that must not go to Hermes. Empty means a normal sentence."""
    raw = re.sub(r"[,:;]+", " ", (text or "").strip())
    raw = re.sub(r"[\s.!?]+$", "", raw)
    raw = re.sub(r"\s+", " ", raw).strip()
    return "pause" if raw and _LOCAL_PAUSE.match(raw) else ""


def load_settings():
    """Voice, mic, wake and volume from the window. Unknown values fall back."""
    data = dict(DEFAULT_SETTINGS)
    try:
        with open(SETTINGS_FILE, encoding="utf-8") as handle:
            raw = json.loads(handle.read())
    except (OSError, ValueError, TypeError):
        return data
    if not isinstance(raw, dict):
        return data
    voice = raw.get("voice")
    if voice in VOICES:
        data["voice"] = voice
    if raw.get("sensitivity") in SENSITIVITY:
        data["sensitivity"] = raw["sensitivity"]
    if raw.get("wake") in WAKE_MODES:
        data["wake"] = raw["wake"]
    if raw.get("volume") in VOLUMES:
        data["volume"] = raw["volume"]
    if raw.get("animation") in ANIMATIONS:
        data["animation"] = raw["animation"]
    return data


def save_settings(updates=None):
    """Write known settings only. Used for spoken volume changes."""
    data = load_settings()
    if isinstance(updates, dict):
        if updates.get("voice") in VOICES:
            data["voice"] = updates["voice"]
        if updates.get("sensitivity") in SENSITIVITY:
            data["sensitivity"] = updates["sensitivity"]
        if updates.get("wake") in WAKE_MODES:
            data["wake"] = updates["wake"]
        if updates.get("volume") in VOLUMES:
            data["volume"] = updates["volume"]
        if updates.get("animation") in ANIMATIONS:
            data["animation"] = updates["animation"]
    try:
        os.makedirs(BUS_DIR, exist_ok=True)
        tmp = SETTINGS_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(data, handle)
        os.replace(tmp, SETTINGS_FILE)
    except OSError:
        pass
    return data


def consume_preview():
    """True once when the settings panel asked for a short voice sample."""
    try:
        os.remove(PREVIEW_FILE)
        return True
    except OSError:
        return False


def is_preview(audio):
    """True only for the settings-probe marker, never for a microphone array."""
    return audio == PREVIEW_MARK if isinstance(audio, str) else False


def write_hermes_status(payload):
    """Tell the settings panel whether the Hermes agent was found and is warm."""
    data = public_hermes(payload)
    try:
        tmp = HERMES_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(data, handle)
        os.replace(tmp, HERMES_FILE)
    except OSError:
        pass


def publish_hermes():
    if _brain is None:
        write_hermes_status({"found": bool(_hermes), "connected": False})
        return
    write_hermes_status(_brain.status())


def wait_while_paused():
    """Leave the stream closed until the window clears the pause file."""
    if not is_paused():
        return
    write_state("idle")
    write_status(STATUS_PAUSED)
    print("[voice] Mikrofon pausiert.")
    while is_paused():
        time.sleep(0.12)
    write_status(STATUS_READY)
    print("[voice] Mikrofon wieder an.")


def _to64(samples, gain):
    """Decimate/scale a mono float array to 64 values in [-1, 1] for the waveform bus."""
    arr = np.asarray(samples, dtype=np.float32).ravel()
    if arr.size == 0:
        return [0.0] * 64
    if arr.size >= 64:
        idx = np.linspace(0, arr.size - 1, 64).astype(np.int32)
        arr = arr[idx]
    else:
        arr = np.pad(arr, (0, 64 - arr.size))
    arr = np.clip(arr * gain, -1.0, 1.0)
    return [round(float(v), 4) for v in arr]


def write_waveform(samples, gain):
    payload = {"ts": time.time(), "samples": _to64(samples, gain)}
    tmp = WAVEFORM_FILE + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f)
        os.replace(tmp, WAVEFORM_FILE)
    except OSError:
        pass


def set_alert():
    try:
        open(ALERT_FILE, "w").close()
    except OSError:
        pass


def clear_alert():
    try:
        os.remove(ALERT_FILE)
    except OSError:
        pass


# --- Wake ------------------------------------------------------------------
def wait_for_wake_ptt():
    write_state("idle")
    write_status("Press Enter to talk")
    try:
        input("\n[voice] Press Enter to talk to Jarvis (Ctrl+C to quit) ... ")
    except EOFError:
        raise KeyboardInterrupt


# --- Listen (mic capture + VAD, writes the listening waveform) --------------
def listen(start_timeout=START_TIMEOUT_S, arm_immediately=False, stream=None):
    """Record one utterance. start_timeout None waits until speech begins.

    arm_immediately marks the orb as listening up front (follow-up or Enter mode).
    Otherwise the orb stays on JARVIS CONNECTED until voice energy arrives.
    """
    if arm_immediately:
        write_state("listening")
        write_status(STATUS_LISTEN)
        print("[voice] listening — go ahead.")
    else:
        write_state("idle")
        write_status(STATUS_READY)
    sense = SENSITIVITY[load_settings()["sensitivity"]]
    vad_on = sense["vad"]
    min_peak = sense["peak"]
    start_frames = sense["start"]
    frame = int(SAMPLE_RATE * 0.03)  # 30ms
    silence_frames_needed = int(SILENCE_MS / 30)
    buf, preroll, silence, started, voiced_frames, pending, peak = [], [], 0, False, 0, 0, 0.0
    t0 = time.time()
    speech_t0 = t0
    last_wave = 0.0

    def _wave(mono):
        nonlocal last_wave
        now = time.time()
        if now - last_wave >= WAVEFORM_EVERY_S:
            last_wave = now
            write_waveform(mono, MIC_GAIN)

    def _loop(stream):
        nonlocal silence, started, voiced_frames, pending, peak, speech_t0
        while True:
            if is_paused():
                return None
            if consume_preview():
                return PREVIEW_MARK
            block, _ = stream.read(frame)
            mono = block[:, 0].copy()
            rms = float(np.sqrt(np.mean(mono ** 2)) + 1e-9)
            peak = max(peak, rms)
            if rms > vad_on:
                pending += 1
                if not started and (arm_immediately or pending >= start_frames):
                    started = True
                    speech_t0 = time.time()
                    buf.extend(preroll)
                    preroll.clear()
                    write_state("listening")
                    write_status(STATUS_LISTEN)
                    if not arm_immediately:
                        print("[voice] listening — go ahead.")
                if started:
                    silence, voiced_frames = 0, voiced_frames + 1
                    buf.append(mono)
                    _wave(mono)
                else:
                    preroll.append(mono)
                    if len(preroll) > 12:
                        del preroll[0]
            elif started:
                pending = 0
                silence += 1
                buf.append(mono)
                _wave(mono)
            else:
                pending = 0
                preroll.append(mono)
                if len(preroll) > 12:
                    del preroll[0]
            if started and silence >= silence_frames_needed:
                return True
            if start_timeout is not None and not started and time.time() - t0 > start_timeout:
                return False
            if started and time.time() - speech_t0 > MAX_UTTER_S:
                return True

    if stream is not None:
        ended = _loop(stream)
    else:
        with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="float32", blocksize=frame) as owned:
            ended = _loop(owned)
    if ended is None:
        return None
    if ended == PREVIEW_MARK:
        return PREVIEW_MARK
    audio = np.concatenate(buf) if buf else np.zeros(1, dtype=np.float32)
    voiced_s = voiced_frames * 0.03
    if voiced_s < MIN_SPEECH_S or peak < min_peak:
        return None
    print("[voice] captured %.1fs, %.2fs voiced, peak level %.3f (threshold %.3f)"
          % (len(audio) / SAMPLE_RATE, voiced_s, peak, vad_on))
    return audio


# --- Transcribe -------------------------------------------------------------
_whisper = None


def load_whisper():
    global _whisper
    if _whisper is None:
        from faster_whisper import WhisperModel
        from faster_whisper.utils import download_model

        stop = threading.Event()

        def _pulse(start, end, wait):
            value = start
            while not stop.wait(wait):
                value = min(end, value + 1)
                write_load_progress(value)

        write_load_progress(3)
        downloading = threading.Thread(target=_pulse, args=(5, 85, 0.4), daemon=True)
        downloading.start()
        try:
            model_path = download_model(WHISPER_SIZE)
        finally:
            stop.set()
            downloading.join(timeout=1)
        write_load_progress(88)
        stop = threading.Event()
        pulsing = threading.Thread(target=_pulse, args=(88, 99, 0.28), daemon=True)
        pulsing.start()
        try:
            _whisper = WhisperModel(model_path, device="cpu", compute_type="int8")
        finally:
            stop.set()
        write_load_progress(100)
    return _whisper


# Whisper's stock hallucinations on near-silence — drop them.
_HALLUCINATIONS = {"you", "thank you", "thanks for watching", "bye", "thanks", "okay", "."}


def _clean_transcript(text):
    text = (text or "").strip()
    norm = text.lower().strip(" .,!?")
    return "" if norm in _HALLUCINATIONS or norm == "" else text


def transcribe(audio):
    t0 = time.time()
    kwargs = {
        "language": "de",
        "beam_size": 5,
        "temperature": 0.0,
        "vad_filter": False,
        "condition_on_previous_text": False,
        "no_speech_threshold": 0.7,
    }
    notes = load_notes()
    if notes:
        kwargs["initial_prompt"] = re.sub(r"\s+", " ", notes)[:200]
    segments, _info = load_whisper().transcribe(audio, **kwargs)
    parts = []
    for seg in segments:
        # Low-confidence pieces are how room noise and echo become fake commands.
        if getattr(seg, "no_speech_prob", 0) > 0.72:
            continue
        if getattr(seg, "avg_logprob", 0) < -1.25:
            continue
        piece = (seg.text or "").strip()
        if piece:
            parts.append(piece)
    text = _clean_transcript(" ".join(parts))
    if not isinstance(audio, str):
        print("[voice] stt %.2fs%s" % (time.time() - t0, (": " + text) if text else ""))
    return text


# Whisper often spells the name the way a German speaker says it.
_WAKE_WORD = re.compile(
    r"\b(?:jarvis|javis|jarves|jarwis|dscharvis|tscharvis|djarvis|charvis|scharvis|yarvis)\b",
    re.IGNORECASE,
)
_LEADING_HEY = re.compile(r"^(?:hey|hi|okay|ok|hallo|oh)\b[\s,;:!-]*", re.IGNORECASE)


def split_wake(text):
    """Return (heard_name, command_without_the_name)."""
    raw = (text or "").strip()
    match = _WAKE_WORD.search(raw)
    if not match:
        return False, ""
    rest = (raw[:match.start()] + " " + raw[match.end():]).strip()
    rest = _LEADING_HEY.sub("", rest)
    rest = re.sub(r"^[\s,;:.!?-]+", "", rest)
    rest = re.sub(r"\s+", " ", rest).strip()
    return True, rest


def is_echo(heard, spoken):
    """True when the mic picked up Jarvis's own last sentence."""
    heard_n = re.sub(r"[^a-z0-9äöüß ]+", "", (heard or "").lower()).strip()
    spoken_n = re.sub(r"[^a-z0-9äöüß ]+", "", (spoken or "").lower()).strip()
    return len(heard_n) >= 8 and bool(spoken_n) and heard_n in spoken_n


def command_from_utterance(utterance, last_reply=""):
    """Classify one transcript: pause, a question, or ignore."""
    if not utterance or is_echo(utterance, last_reply):
        return "ignore", ""
    if local_action(utterance) == "pause":
        return "pause", ""
    matched, rest = split_wake(utterance)
    if load_settings()["wake"] == "an":
        if not matched:
            return "ignore", ""
        return "ask", rest
    if matched and not rest:
        return "ignore", ""
    command = (rest or utterance).strip()
    if is_echo(command, last_reply):
        return "ignore", ""
    compact = re.sub(r"[^a-z0-9äöüß]", "", command.lower())
    if len(compact) < 5:
        return "ignore", ""
    return "ask", command


# --- Brain bridge (Hermes default profile, explicit Jarvis session) ----------
from hermes_bridge import HermesBridge, BridgeError
from memory_store import add_note, load_notes, set_memory_root
from local_skills import (
    clock_text, execute_action, next_volume, public_confirm,
    set_file_roots, timer_phrase,
)
set_file_roots((
    os.path.join(os.path.expanduser("~"), "Desktop"),
    os.path.join(os.path.expanduser("~"), "Documents"),
    os.path.join(os.path.expanduser("~"), "Downloads"),
    BRAIN_DIR,
    CODE_DIR,
))
set_memory_root(BRAIN_DIR)
_hermes = find_hermes()
_brain = None
_last_brain_error = ""
_speak_lock = threading.Lock()
_timer_cancel = threading.Event()
_timer_lock = threading.Lock()
_barge_hit = False
BARGE_GRACE_S = 0.35
BARGE_FLOOR = 0.10
BARGE_COUPLING = 0.40
BARGE_VOICE = 0.06


def ask_brain(text, first_turn=False):
    global _brain, _last_brain_error
    _last_brain_error = ""
    try:
        if _brain is None:
            _brain = HermesBridge(BRAIN_DIR, executable=_hermes, reuse_session=False)
        reply = _brain.ask(text)
        publish_hermes()
        return reply
    except BridgeError as exc:
        _last_brain_error = str(exc)
        publish_hermes()
        set_alert()
        write_status(str(exc))
        print("[Hermes]", exc)
        return ""  # never send diagnostic logs to TTS


# --- Speak (TTS -> WAV -> play while writing the speaking waveform) ----------
_last_tts = "none"


async def _edge_save(text, path):
    import edge_tts
    # Native pace and pitch. Slowing or lowering the neural voice makes it buzz.
    communicate = edge_tts.Communicate(text, load_settings()["voice"])
    await communicate.save(path)


def _synth_wav_say(text):
    """Offline fallback. Anna is a compact German voice, not the cartoon Eddy voice."""
    tmpdir = os.path.join(BRAIN_DIR, ".run", "tmp")
    os.makedirs(tmpdir, exist_ok=True)
    fd, path = tempfile.mkstemp(prefix="jarvis-", suffix=".wav", dir=tmpdir)
    os.close(fd)
    try:
        subprocess.run(["/usr/bin/say", "-v", TTS_FALLBACK_VOICE,
                        "-r", str(TTS_RATE), "-o", path,
                        "--file-format=WAVE", "--data-format=LEI16@%d" % TTS_PLAY_RATE,
                        "--channels=1"], input=text, text=True, check=True, timeout=60)
    except Exception:
        os.unlink(path)
        raise
    return path


def _synth_wav(text):
    """Neural German male voice, then a local fallback if the network voice fails."""
    global _last_tts
    tmpdir = os.path.join(BRAIN_DIR, ".run", "tmp")
    os.makedirs(tmpdir, exist_ok=True)
    fd, mp3 = tempfile.mkstemp(prefix="jarvis-", suffix=".mp3", dir=tmpdir)
    os.close(fd)
    path = mp3[:-4] + ".wav"
    try:
        asyncio.run(_edge_save(text, mp3))
        subprocess.run(
            ["/usr/bin/afconvert", "-f", "WAVE", "-d", "LEI16@%d" % TTS_PLAY_RATE, "-c", "1", mp3, path],
            check=True, timeout=60)
        _last_tts = "edge"
        return path
    except Exception as exc:
        print("[voice] neural TTS unavailable (%s) — local voice." % exc)
        try:
            os.remove(path)
        except OSError:
            pass
        _last_tts = "say"
        return _synth_wav_say(text)
    finally:
        try:
            os.remove(mp3)
        except OSError:
            pass


def _read_wav(path):
    with wave.open(path, "rb") as w:
        sr = w.getframerate()
        n = w.getnframes()
        ch = w.getnchannels()
        raw = w.readframes(n)
    data = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    if ch > 1:
        data = data.reshape(-1, ch).mean(axis=1)
    return data, sr


def _smooth_edges(data, sr):
    """Short fades so playback does not click at the start or the cut-off."""
    n = min(int(sr * 0.012), max(0, len(data) // 4))
    if n < 2:
        return data
    out = np.array(data, dtype=np.float32, copy=True)
    ramp = np.linspace(0.0, 1.0, n, dtype=np.float32)
    out[:n] *= ramp
    out[-n:] *= ramp[::-1]
    return out


def split_spoken(text):
    """Break an answer so the first sentence can start while the next is built."""
    text = for_speech(text)
    if not text:
        return []
    parts = [piece.strip() for piece in re.split(r"(?<=[.!?])\s+", text) if piece.strip()]
    return parts or [text]


def barge_threshold(play_rms, vad=0.016):
    """Mic level that counts as a person talking over the speakers."""
    floor = max(float(vad) * 6.0, BARGE_FLOOR)
    echo = max(0.0, float(play_rms)) * BARGE_COUPLING
    return max(floor, echo + BARGE_VOICE)


def consume_barge():
    """True once after the user talked over Jarvis."""
    global _barge_hit
    hit = _barge_hit
    _barge_hit = False
    return hit


def barged():
    return _barge_hit


def finish_speech():
    """Skip the echo gap when the user already cut in."""
    if barged():
        return
    time.sleep(POST_SPEECH_GAP_S)


def _play_wav(path):
    global _barge_hit
    data, sr = _read_wav(path)
    data = _smooth_edges(data, sr)
    gain = VOLUMES.get(load_settings()["volume"], VOLUMES["normal"])
    data = np.clip(data * gain, -1.0, 1.0)
    write_state("speaking")
    sd.play(data, sr)
    win = max(1, int(sr * 0.04))
    start = time.time()
    duration = len(data) / float(sr)
    frame = int(SAMPLE_RATE * 0.03)
    sense = SENSITIVITY[load_settings()["sensitivity"]]
    need = int(sense["start"]) + 4
    voiced = 0
    mic = None
    try:
        mic = sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="float32",
                             blocksize=frame)
        mic.start()
    except Exception:  # noqa: BLE001
        mic = None
    try:
        while True:
            if is_paused():
                try:
                    sd.stop()
                except Exception:  # noqa: BLE001
                    pass
                break
            elapsed = time.time() - start
            if elapsed >= duration:
                break
            pos = min(len(data) - 1, int(elapsed * sr))
            if mic is not None and elapsed >= BARGE_GRACE_S:
                try:
                    block, _overflowed = mic.read(frame)
                    mono = block[:, 0]
                    rms = float(np.sqrt(np.mean(mono ** 2)) + 1e-9)
                    n_play = max(frame * 4, int(sr * 0.08))
                    play_chunk = data[pos:pos + n_play]
                    play_rms = float(np.sqrt(np.mean(play_chunk ** 2)) + 1e-9) if len(play_chunk) else 0.0
                    if rms > barge_threshold(play_rms, sense["vad"]):
                        voiced += 1
                        if voiced >= need:
                            _barge_hit = True
                            print("[voice] barge-in")
                            try:
                                sd.stop()
                            except Exception:  # noqa: BLE001
                                pass
                            break
                    else:
                        voiced = 0
                except Exception:  # noqa: BLE001
                    pass
            write_waveform(data[pos:pos + win], TTS_GAIN)
            time.sleep(0.02)
    finally:
        if mic is not None:
            try:
                mic.stop()
                mic.close()
            except Exception:  # noqa: BLE001
                pass
    try:
        sd.wait()
    except Exception:  # noqa: BLE001
        pass


def speak(text):
    global _barge_hit
    parts = split_spoken(text)
    if not parts:
        return
    _barge_hit = False
    with _speak_lock:
        pending = None
        for index, part in enumerate(parts):
            if is_paused() or _barge_hit:
                break
            path = pending
            pending = None
            if path is None:
                try:
                    path = _synth_wav(part)
                except Exception as exc:  # noqa: BLE001
                    print("[voice] TTS failed:", exc)
                    write_state("idle")
                    return
            holder = {}

            def _next(sentence=parts[index + 1] if index + 1 < len(parts) else ""):
                try:
                    holder["path"] = _synth_wav(sentence)
                except Exception as exc:  # noqa: BLE001
                    holder["error"] = exc

            worker = None
            if index + 1 < len(parts) and not is_paused() and not _barge_hit:
                worker = threading.Thread(target=_next, daemon=True)
                worker.start()
            try:
                _play_wav(path)
            finally:
                try:
                    os.remove(path)
                except OSError:
                    pass
            if worker:
                worker.join()
                pending = holder.get("path")
        if pending:
            try:
                os.remove(pending)
            except OSError:
                pass
        write_state("idle")


# --- Self-check -------------------------------------------------------------
def check():
    ok = True
    print("Jarvis voice line — dependency check\n")
    for mod in ("numpy", "sounddevice", "faster_whisper", "edge_tts"):
        try:
            __import__(mod)
            print("  [ok]  %s" % mod)
        except Exception as e:  # noqa: BLE001
            ok = False
            print("  [--]  %s  (%s)" % (mod, e))
    print("  [%s]  Hermes on PATH  (%s)" % ("ok" if _hermes else "--", _hermes or "not found"))
    ok = ok and bool(_hermes)
    try:
        devs = [d["name"] for d in sd.query_devices() if d["max_input_channels"] > 0]
        print("  [%s]  microphone  (%s)" % ("ok" if devs else "--", devs[0] if devs else "none"))
    except Exception as e:  # noqa: BLE001
        ok = False
        print("  [--]  microphone  (%s)" % e)
    print("\nBus dir:", BUS_DIR)
    print("Brain dir:", BRAIN_DIR)
    print("\n%s" % ("All good." if ok else "Some deps missing — pip install -r requirements.txt"))
    return ok


def _remove_bus(path):
    try:
        os.remove(path)
    except OSError:
        pass


def write_confirm(action):
    """Ask the window for a yes. The window cannot execute the action itself."""
    payload = dict(action)
    payload["id"] = "%d%x" % (int(time.time()), os.getpid() & 0xFFFF)
    shown = public_confirm(payload)
    if not shown:
        return None
    _remove_bus(CONFIRM_REPLY_FILE)
    try:
        tmp = CONFIRM_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)
        os.replace(tmp, CONFIRM_FILE)
    except OSError:
        return None
    return payload["id"]


def clear_confirm():
    _remove_bus(CONFIRM_FILE)
    _remove_bus(CONFIRM_REPLY_FILE)


def read_confirm_reply(expected_id):
    try:
        with open(CONFIRM_REPLY_FILE, encoding="utf-8") as handle:
            raw = json.loads(handle.read())
    except (OSError, ValueError, TypeError):
        return None
    if not isinstance(raw, dict) or raw.get("id") != expected_id:
        return None
    if raw.get("accepted") not in (True, False):
        return None
    return bool(raw["accepted"])


def wait_for_confirm(confirm_id, timeout=45):
    write_status("Bitte im Fenster bestätigen")
    deadline = time.time() + timeout
    while time.time() < deadline:
        if is_paused():
            clear_confirm()
            return False
        answered = read_confirm_reply(confirm_id)
        if answered is not None:
            clear_confirm()
            return answered
        time.sleep(0.12)
    clear_confirm()
    return False


def needs_hermes_notice(message):
    text = (message or "").lower()
    return "freigabe" in text or "bestätigt" in text or "hermes-terminal" in text


def scrub_voice(text):
    """Never send the user to a Hermes terminal they do not see."""
    raw = text or ""
    if re.search(r"hermes[- ]?terminal|interaktiv(?:en)? hermes|im terminal bestätigen", raw, re.I):
        return "Das geht von hier aus nicht."
    return raw


def cancel_timer():
    _timer_cancel.set()


def start_timer(seconds):
    global _timer_cancel
    with _timer_lock:
        _timer_cancel.set()
        flag = threading.Event()
        _timer_cancel = flag

        def _run():
            end = time.time() + seconds
            while time.time() < end:
                if flag.wait(0.25):
                    return
            if flag.is_set():
                return
            set_alert()
            write_status("Timer fertig")
            speak("Der Timer ist fertig.")
            finish_speech()
            show_connected()

        threading.Thread(target=_run, daemon=True).start()


def run_skill(skill, last_reply):
    """Handle a local skill. Returns the text that was spoken, if any."""
    kind = skill.get("kind")
    if kind == "repeat":
        if not last_reply:
            spoken = "Da gibt es nichts zu wiederholen."
            write_status(spoken)
            speak(spoken)
            finish_speech()
            return last_reply
        write_status(last_reply)
        speak(last_reply)
        finish_speech()
        return last_reply
    if kind == "clock":
        spoken = clock_text(kind=skill.get("what") or "time")
        write_status(spoken)
        speak(spoken)
        finish_speech()
        return spoken
    if kind == "volume":
        current = load_settings()["volume"]
        nxt = next_volume(current, skill.get("spoken") or "")
        save_settings({"volume": nxt})
        spoken = "Lautstärke %s." % nxt
        write_status(spoken)
        speak(spoken)
        finish_speech()
        return spoken
    if kind == "timer_cancel":
        cancel_timer()
        spoken = "Timer ist aus."
        write_status(spoken)
        speak(spoken)
        finish_speech()
        return spoken
    if kind == "timer":
        start_timer(int(skill["seconds"]))
        spoken = "Timer, %s. Ich sage Bescheid." % timer_phrase(int(skill["seconds"]))
        write_status(spoken)
        speak(spoken)
        finish_speech()
        return spoken
    if kind == "open_file_missing":
        spoken = "Welche Datei? Nenn den Namen."
        write_status(spoken)
        speak(spoken)
        finish_speech()
        return spoken
    if kind in ("open_app", "open_url", "open_file"):
        confirm_id = write_confirm(skill)
        if not confirm_id:
            spoken = "Das öffne ich nicht."
            write_status(spoken)
            speak(spoken)
            finish_speech()
            return spoken
        speak("Bitte im Fenster mit Ja oder Nein bestätigen.")
        accepted = wait_for_confirm(confirm_id)
        if not accepted:
            spoken = "Alles klar, ich lasse es."
            write_status(spoken)
            speak(spoken)
            finish_speech()
            return spoken
        spoken = execute_action(skill)
        write_status(spoken or STATUS_READY)
        if spoken:
            speak(spoken)
            finish_speech()
        return spoken
    if kind == "memory_add":
        stored = add_note(skill.get("note") or "")
        spoken = "Ist notiert." if stored else "Das speichere ich nicht."
        write_status(spoken)
        speak(spoken)
        finish_speech()
        return spoken
    if kind == "memory_recall":
        notes = load_notes()
        spoken = notes if notes else "Ich habe noch keine Erinnerungen."
        write_status(spoken)
        speak(spoken)
        finish_speech()
        return spoken
    return last_reply


def take_command(audio):
    """Transcribe one recording. Empty string means silence or a recognizer error."""
    if audio is None:
        return ""
    write_state("thinking")
    write_status(STATUS_THINK)
    try:
        return transcribe(audio)
    except Exception as e:  # noqa: BLE001
        print("[voice] STT failed:", e)
        write_state("idle")
        write_status(STATUS_READY)
        return ""


def show_hermes_notice(message):
    """Refuse a blocked tool without pointing at another app."""
    spoken = "Das geht von hier aus nicht."
    write_status(spoken)
    speak(spoken)
    finish_speech()
    write_status(STATUS_READY)


def handle_command(utterance, first_turn):
    """Send one user sentence to Hermes and speak the answer. Returns (first_turn, reply)."""
    print("\n  You: %s" % utterance)
    write_status('“%s”' % utterance)
    t0 = time.time()
    reply = scrub_voice(for_speech(ask_brain(utterance, first_turn)))
    print("[voice] hermes %.2fs" % (time.time() - t0))
    if not reply:
        write_state("idle")
        if needs_hermes_notice(_last_brain_error):
            show_hermes_notice(_last_brain_error)
        else:
            write_status(STATUS_READY)
        return False, ""
    print("  Jarvis: %s\n" % reply)
    write_status(reply)
    speak(reply)
    finish_speech()
    return False, reply


def handle_turn(command, first_turn, last_reply):
    return handle_command(command, first_turn)


def show_connected():
    write_state("idle")
    write_status(STATUS_READY)


# --- Main -------------------------------------------------------------------
def main():
    if "--check" in sys.argv:
        check()
        return
    ensure_bus()
    clear_alert()
    write_state("idle")
    ptt = "--ptt" in sys.argv
    daemon = "--daemon" in sys.argv
    greet = "--no-greeting" not in sys.argv
    print("=" * 48)
    print(" Jarvis voice line starting.  Ctrl+C to quit.")
    print(" Mode:", "press-Enter" if ptt else "speak, then pause")
    print("=" * 48)

    def _term(_signum, _frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, _term)

    # Warm up speech and Hermes together. Hermes stays loaded for later sentences.
    write_state("booting")
    t0 = time.time()
    interactive = sys.stdin.isatty()
    session = interactive or daemon
    if session:
        global _brain
        _brain = HermesBridge(BRAIN_DIR, executable=_hermes, reuse_session=False)
        write_hermes_status({"found": bool(_hermes), "connected": False})

        def _warm():
            _brain.warmup()
            publish_hermes()

        threading.Thread(target=_warm, daemon=True).start()
        print("[voice] Hermes wird geladen …")
    else:
        write_hermes_status({"found": bool(_hermes), "connected": False})
    write_load_progress(1)
    print("[voice] loading Whisper (%s) ..." % WHISPER_SIZE)
    load_whisper()
    print("\n" + "#" * 48)
    print("#   JARVIS CONNECTED  ({:.1f}s)".format(time.time() - t0))
    print("#   " + ("press Enter to talk" if ptt else "einfach sprechen, eine Pause schickt die Frage"))
    print("#" * 48 + "\n")
    show_connected()
    if session and greet:
        write_status(STATUS_READY)
        speak("Jarvis verbunden.")
        finish_speech()
        show_connected()
    # A closed stdin is the launcher test unless --daemon keeps the session up.
    first_turn = True
    last_reply = ""
    barge_now = consume_barge()
    try:
        if not ptt and not session:
            print("[voice] kein Terminal — Mikrofon bleibt aus.")
            return
        while True:
            clear_alert()
            if ptt:
                if not barge_now:
                    wait_for_wake_ptt()
                utterance = take_command(listen(arm_immediately=True, start_timeout=8 if barge_now else START_TIMEOUT_S))
                barge_now = False
                kind, command = command_from_utterance(utterance, last_reply)
                if kind == "pause":
                    request_pause()
                    continue
                if kind != "ask" or not command:
                    print("[voice] (heard nothing — speak a bit louder or closer to the mic)")
                    show_connected()
                    continue
                first_turn, last_reply = handle_turn(command, first_turn, last_reply)
                barge_now = consume_barge()
                continue

            # Close the mic before TTS so barge-in can open it while he speaks.
            wait_while_paused()
            frame = int(SAMPLE_RATE * 0.03)
            command = None
            with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="float32",
                                blocksize=frame) as stream:
                while True:
                    if is_paused():
                        break
                    audio = listen(
                        start_timeout=8 if barge_now else None,
                        arm_immediately=barge_now, stream=stream)
                    barge_now = False
                    if is_preview(audio):
                        speak("So klinge ich jetzt.")
                        show_connected()
                        barge_now = consume_barge()
                        continue
                    if is_paused():
                        break
                    utterance = take_command(audio)
                    kind, command = command_from_utterance(utterance, last_reply)
                    if kind == "pause":
                        request_pause()
                        command = None
                        break
                    if kind == "ask" and not command:
                        follow = listen(start_timeout=8, arm_immediately=True, stream=stream)
                        if is_preview(follow):
                            speak("So klinge ich jetzt.")
                            show_connected()
                            barge_now = consume_barge()
                            continue
                        follow_text = take_command(follow)
                        kind, command = command_from_utterance(follow_text, last_reply)
                        if kind == "pause":
                            request_pause()
                            command = None
                            break
                    if kind != "ask" or not command:
                        show_connected()
                        command = None
                        continue
                    break
            if command:
                first_turn, last_reply = handle_turn(command, first_turn, last_reply)
                barge_now = consume_barge()
    except KeyboardInterrupt:
        pass
    finally:
        brain = _brain
        if brain is not None:
            try:
                brain._drop_client()
            except Exception:  # noqa: BLE001
                pass
        write_state("idle")
        clear_alert()
        print("\n[voice] offline.")


if __name__ == "__main__":
    main()
