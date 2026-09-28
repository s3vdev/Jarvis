#!/usr/bin/env python3
"""Jarvis visualizer server.

Two jobs, nothing more:
  1. Serve the self-contained scene (index.html).
  2. Serve /state as JSON by READING the voice line's signal bus.

The window may write `.voice_pause`, `.voice_settings` and `.voice_preview`.
State, waveform and alert stay voice-line owned.

Run modes:
  python server.py            -> real bus, port 8777
  python server.py --mock     -> scripted state loop, port 8778 (never touches the real bus)

Stdlib only. No packages, no build step.
"""

import json
import os
import re
import subprocess
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

# --- Config (signal bus in ~/voice-line) ------------------------------------
BUS_DIR = os.path.join(os.path.expanduser("~"), "voice-line")
STATE_FILE = os.path.join(BUS_DIR, ".voice_state")
WAVEFORM_FILE = os.path.join(BUS_DIR, ".voice_waveform")
ALERT_FILE = os.path.join(BUS_DIR, ".voice_alert")
STATUS_FILE = os.path.join(BUS_DIR, ".voice_status")
PAUSE_FILE = os.path.join(BUS_DIR, ".voice_pause")
SETTINGS_FILE = os.path.join(BUS_DIR, ".voice_settings")
PREVIEW_FILE = os.path.join(BUS_DIR, ".voice_preview")
HERMES_FILE = os.path.join(BUS_DIR, ".voice_hermes")
CONFIRM_FILE = os.path.join(BUS_DIR, ".voice_confirm")
CONFIRM_REPLY_FILE = os.path.join(BUS_DIR, ".voice_confirm_reply")
CONFIRM_ID = re.compile(r"^[0-9a-fA-F]{8,24}$")
USAGE_FILE = os.path.join(BUS_DIR, ".voice_usage")
LOAD_FILE = os.path.join(BUS_DIR, ".voice_load")
CONFIRM_APPS = (
    "Safari", "Mail", "Music", "Calendar", "Notes", "Finder", "Terminal",
    "System Settings", "Messages", "Photos", "Maps",
)
VOICES = (
    ("de-DE-ConradNeural", "Conrad · klar"),
    ("de-DE-KillianNeural", "Killian · jünger"),
    ("de-DE-FlorianMultilingualNeural", "Florian · weicher"),
)
SENSITIVITY = ("leise", "normal", "fest")
WAKE_MODES = ("aus", "an")
VOLUMES = ("leise", "normal", "laut")
ANIMATIONS = ("kugel", "radar", "iris")
DEFAULT_SETTINGS = {
    "voice": "de-DE-ConradNeural",
    "sensitivity": "normal",
    "wake": "aus",
    "volume": "normal",
    "animation": "kugel",
}

HERE = os.path.dirname(os.path.abspath(__file__))
_VOICE = os.path.join(os.path.dirname(HERE), "voice-line")
if _VOICE not in sys.path:
    sys.path.insert(0, _VOICE)
from jarvis_config import data_root, find_hermes, load_config, public_hermes  # noqa: E402
from memory_store import public_memory, save_notes, set_memory_root  # noqa: E402

set_memory_root(str(data_root()))

REAL_PORT = 8777
MOCK_PORT = 8778

WAVEFORM_FRESH_SECS = 2.0   # a waveform newer than this counts as "live voice"
VALID_STATES = ("idle", "listening", "thinking", "speaking", "booting")

MOCK = "--mock" in sys.argv


# --- Bus reading ------------------------------------------------------------
def _read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return None


def _read_waveform():
    """Return (level, samples, fresh) from the waveform file, or (0.0, [], False)."""
    raw = _read_text(WAVEFORM_FILE)
    if not raw:
        return 0.0, [], False
    try:
        data = json.loads(raw)
        ts = float(data.get("ts", 0))
        samples = [float(s) for s in data.get("samples", [])]
    except (ValueError, TypeError):
        return 0.0, [], False
    fresh = (time.time() - ts) <= WAVEFORM_FRESH_SECS
    if not samples:
        return 0.0, [], fresh
    # level = scaled mean-abs of samples, clamped 0..1
    level = sum(abs(s) for s in samples) / len(samples)
    level = max(0.0, min(1.0, level))
    return level, samples, fresh


def real_state():
    state = _read_text(STATE_FILE)
    if state not in VALID_STATES:
        state = "idle"
    level, samples, fresh = _read_waveform()
    # A fresh waveform during idle means playback even if the state file lagged.
    # Listening writes waveforms too, so an explicit listening or thinking turn stays put.
    if fresh and level > 0.0 and state == "idle":
        state = "speaking"
    if not fresh:
        level = 0.0
        samples = []
    alert = os.path.exists(ALERT_FILE)
    paused = os.path.exists(PAUSE_FILE)
    status = _read_text(STATUS_FILE) or ""
    if paused:
        state = "idle"
        level = 0.0
        samples = []
        status = status or "PAUSED"
    progress = None
    if state == "booting":
        raw_pct = _read_text(LOAD_FILE)
        try:
            progress = max(0, min(100, int(raw_pct)))
        except (TypeError, ValueError):
            progress = 0
    return {"state": state, "level": round(level, 4), "alert": alert,
            "paused": paused, "status": status, "samples": samples,
            "hermes": hermes_status(), "confirm": pending_confirm(),
            "progress": progress}


# --- Mock loop (never touches the real bus) ---------------------------------
# Scripted: idle -> listening -> thinking -> speaking (breathing) -> alert -> idle
_MOCK_SCRIPT = [
    ("idle", 3.0),
    ("listening", 2.5),
    ("thinking", 2.5),
    ("speaking", 5.0),
    ("alert", 2.0),
]
_MOCK_TOTAL = sum(d for _, d in _MOCK_SCRIPT)


def mock_state():
    t = time.time() % _MOCK_TOTAL
    acc = 0.0
    cur, elapsed = "idle", 0.0
    for name, dur in _MOCK_SCRIPT:
        if t < acc + dur:
            cur, elapsed = name, t - acc
            break
        acc += dur
    alert = cur == "alert"
    state = "speaking" if cur == "alert" else cur  # alert overlays speaking-ish activity
    if cur == "speaking":
        # synthetic breathing level
        level = 0.5 + 0.45 * abs(__import__("math").sin(elapsed * 3.2))
    elif cur == "listening":
        level = 0.25 + 0.1 * abs(__import__("math").sin(elapsed * 4.0))
    elif cur == "alert":
        level = 0.6
    else:
        level = 0.0
    status = {"listening": "Listening…", "thinking": "Thinking…",
              "speaking": "All systems nominal, Boss."}.get(cur, "")
    return {"state": state, "level": round(level, 4), "alert": alert,
            "paused": False, "status": status, "samples": [],
            "hermes": hermes_status(), "confirm": None}


def pending_confirm():
    """Safe window payload only. The server never executes the action."""
    raw = _read_text(CONFIRM_FILE)
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(parsed, dict):
        return None
    cid = parsed.get("id")
    if not isinstance(cid, str) or not CONFIRM_ID.match(cid):
        return None
    kind = parsed.get("kind")
    if kind == "notice":
        title = parsed.get("title") if isinstance(parsed.get("title"), str) else "Hinweis"
        detail = parsed.get("detail") if isinstance(parsed.get("detail"), str) else ""
        return {"id": cid, "kind": "notice", "title": title[:80], "detail": detail[:240]}
    if kind == "open_app":
        app = parsed.get("app")
        if app not in CONFIRM_APPS:
            return None
        return {"id": cid, "kind": "action", "title": "%s öffnen?" % app,
                "detail": "Nur wenn du im Fenster Ja drückst."}
    if kind == "open_url":
        url = parsed.get("url") if isinstance(parsed.get("url"), str) else ""
        if not url.startswith("https://") and not url.startswith("http://"):
            return None
        if len(url) > 180:
            return None
        return {"id": cid, "kind": "action", "title": "Diese Seite öffnen?", "detail": url}
    if kind == "open_file":
        name = parsed.get("name") if isinstance(parsed.get("name"), str) else ""
        if not name and isinstance(parsed.get("path"), str):
            name = os.path.basename(parsed.get("path") or "")
        if not name or "/" in name or "\\" in name or ".." in name or len(name) > 80:
            return None
        return {"id": cid, "kind": "action", "title": "Datei öffnen?", "detail": name}
    return None


def save_confirm_reply(incoming):
    pending = pending_confirm()
    if pending is None or not isinstance(incoming, dict):
        return None
    if incoming.get("id") != pending["id"]:
        return None
    if incoming.get("accepted") not in (True, False):
        return None
    data = {"id": pending["id"], "accepted": bool(incoming["accepted"])}
    os.makedirs(BUS_DIR, exist_ok=True)
    tmp = CONFIRM_REPLY_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(data, handle)
    os.replace(tmp, CONFIRM_REPLY_FILE)
    return data


def hermes_status():
    raw = _read_text(HERMES_FILE)
    if not raw:
        return public_hermes()
    try:
        parsed = json.loads(raw)
    except ValueError:
        return public_hermes()
    if not isinstance(parsed, dict):
        return public_hermes()
    return public_hermes(parsed)


def load_settings():
    data = dict(DEFAULT_SETTINGS)
    raw = _read_text(SETTINGS_FILE)
    if not raw:
        return data
    try:
        parsed = json.loads(raw)
    except ValueError:
        return data
    if not isinstance(parsed, dict):
        return data
    allowed = {key for key, _label in VOICES}
    if parsed.get("voice") in allowed:
        data["voice"] = parsed["voice"]
    if parsed.get("sensitivity") in SENSITIVITY:
        data["sensitivity"] = parsed["sensitivity"]
    if parsed.get("wake") in WAKE_MODES:
        data["wake"] = parsed["wake"]
    if parsed.get("volume") in VOLUMES:
        data["volume"] = parsed["volume"]
    if parsed.get("animation") in ANIMATIONS:
        data["animation"] = parsed["animation"]
    return data


def save_settings(incoming):
    if not isinstance(incoming, dict):
        return None
    current = load_settings()
    allowed = {key for key, _label in VOICES}
    voice = incoming.get("voice", current["voice"])
    sensitivity = incoming.get("sensitivity", current["sensitivity"])
    wake = incoming.get("wake", current["wake"])
    volume = incoming.get("volume", current["volume"])
    animation = incoming.get("animation", current["animation"])
    if voice not in allowed or sensitivity not in SENSITIVITY:
        return None
    if wake not in WAKE_MODES or volume not in VOLUMES:
        return None
    if animation not in ANIMATIONS:
        return None
    data = {"voice": voice, "sensitivity": sensitivity, "wake": wake,
            "volume": volume, "animation": animation}
    os.makedirs(BUS_DIR, exist_ok=True)
    tmp = SETTINGS_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(data, handle)
    os.replace(tmp, SETTINGS_FILE)
    return data


def settings_payload():
    data = load_settings()
    data["voices"] = [{"id": key, "label": label} for key, label in VOICES]
    data["sensitivities"] = list(SENSITIVITY)
    data["hermes"] = hermes_status()
    data["usage"] = load_cached_usage()
    data["memory"] = public_memory()
    return data


def hermes_executable():
    return find_hermes()


def usage_argv(executable):
    """Fixed argv. Never includes -z, user text, or a shell."""
    cfg = load_config()
    return [executable, "-p", cfg["profile"], "usage", "--json", "--provider", cfg["provider"]]


def public_usage(raw):
    """Safe subset for the settings panel. No tokens, no reset action."""
    if not isinstance(raw, dict):
        return {"ok": False, "error": "Keine Nutzungsdaten."}
    if raw.get("unavailable_reason"):
        reason = raw.get("unavailable_reason")
        if not isinstance(reason, str) or not reason.strip():
            reason = "Nutzung nicht verfügbar."
        return {"ok": False, "error": reason[:160]}
    windows = []
    for item in raw.get("windows") or []:
        if not isinstance(item, dict):
            continue
        label = item.get("label")
        used = item.get("used_percent")
        if not isinstance(label, str) or not isinstance(used, (int, float)):
            continue
        used = max(0.0, min(100.0, float(used)))
        reset = item.get("resets_at")
        if not isinstance(reset, str) or len(reset) > 80:
            reset = ""
        windows.append({
            "label": label[:40],
            "used": round(used, 1),
            "left": round(100.0 - used, 1),
            "resets_at": reset,
        })
        if len(windows) >= 4:
            break
    plan = raw.get("plan") if isinstance(raw.get("plan"), str) else ""
    note = ""
    details = raw.get("details")
    if isinstance(details, list) and details and isinstance(details[0], str):
        note = details[0][:140]
    return {
        "ok": True,
        "plan": plan[:40],
        "provider": load_config()["provider"],
        "windows": windows,
        "note": note,
    }


def load_cached_usage():
    raw = _read_text(USAGE_FILE)
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(parsed, dict) or not parsed.get("ok"):
        return parsed if isinstance(parsed, dict) else None
    return parsed


def fetch_usage():
    exe = hermes_executable()
    if not exe:
        return {"ok": False, "error": "Hermes wurde nicht gefunden."}
    try:
        completed = subprocess.run(
            usage_argv(exe), capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired):
        return {"ok": False, "error": "Nutzung konnte nicht geladen werden."}
    try:
        parsed = json.loads(completed.stdout or "{}")
    except ValueError:
        return {"ok": False, "error": "Nutzung konnte nicht gelesen werden."}
    data = public_usage(parsed)
    if completed.returncode and not data.get("ok"):
        return data
    if completed.returncode and data.get("ok"):
        return {"ok": False, "error": "Nutzung konnte nicht geladen werden."}
    try:
        os.makedirs(BUS_DIR, exist_ok=True)
        tmp = USAGE_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(data, handle)
        os.replace(tmp, USAGE_FILE)
    except OSError:
        pass
    return data


# --- HTTP handler -----------------------------------------------------------
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass  # quiet

    def _send(self, code, body, ctype):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self):
        length = 0
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        raw = self.rfile.read(length) if length else b""
        try:
            return json.loads(raw.decode("utf-8") or "{}")
        except ValueError:
            return None

    def do_POST(self):
        path = urlparse(self.path).path
        if MOCK:
            self._send(404, b"not found", "text/plain")
            return
        if path == "/pause":
            body = self._read_json()
            if body is None:
                self._send(400, b"bad json", "text/plain")
                return
            os.makedirs(BUS_DIR, exist_ok=True)
            if body.get("paused"):
                with open(PAUSE_FILE, "w", encoding="utf-8") as handle:
                    handle.write("1")
            else:
                try:
                    os.remove(PAUSE_FILE)
                except OSError:
                    pass
            self._send(200, json.dumps(real_state()).encode("utf-8"), "application/json")
            return
        if path == "/settings":
            saved = save_settings(self._read_json())
            if saved is None:
                self._send(400, b"bad settings", "text/plain")
                return
            self._send(200, json.dumps(settings_payload()).encode("utf-8"), "application/json")
            return
        if path == "/memory":
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                length = 0
            if length > 8000:
                self._send(400, b"bad memory", "text/plain")
                return
            body = self._read_json()
            if not isinstance(body, dict) or "text" not in body:
                self._send(400, b"bad memory", "text/plain")
                return
            if not isinstance(body.get("text"), str):
                self._send(400, b"bad memory", "text/plain")
                return
            stored = save_notes(body["text"])
            if stored is None:
                self._send(400, json.dumps({"ok": False, "error": "Das speichere ich nicht."}).encode("utf-8"), "application/json")
                return
            self._send(200, json.dumps({"ok": True, "memory": public_memory()}).encode("utf-8"), "application/json")
            return
        if path == "/preview":
            os.makedirs(BUS_DIR, exist_ok=True)
            with open(PREVIEW_FILE, "w", encoding="utf-8") as handle:
                handle.write("1")
            self._send(200, json.dumps({"ok": True}).encode("utf-8"), "application/json")
            return
        if path == "/confirm":
            saved = save_confirm_reply(self._read_json())
            if saved is None:
                self._send(400, b"bad confirm", "text/plain")
                return
            self._send(200, json.dumps(real_state()).encode("utf-8"), "application/json")
            return
        self._send(404, b"not found", "text/plain")

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/state":
            payload = mock_state() if MOCK else real_state()
            self._send(200, json.dumps(payload).encode("utf-8"), "application/json")
            return
        if path == "/settings":
            self._send(200, json.dumps(settings_payload()).encode("utf-8"), "application/json")
            return
        if path == "/usage":
            self._send(200, json.dumps(fetch_usage()).encode("utf-8"), "application/json")
            return
        # static files
        if path in ("/", "/index.html"):
            fname = "index.html"
        else:
            fname = path.lstrip("/")
        safe = os.path.normpath(os.path.join(HERE, fname))
        if not safe.startswith(HERE) or not os.path.isfile(safe):
            self._send(404, b"not found", "text/plain")
            return
        ctype = {
            ".html": "text/html", ".js": "text/javascript", ".css": "text/css",
            ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
            ".svg": "image/svg+xml", ".ico": "image/x-icon",
        }.get(os.path.splitext(safe)[1].lower(), "application/octet-stream")
        with open(safe, "rb") as f:
            self._send(200, f.read(), ctype)


def main():
    port = MOCK_PORT if MOCK else REAL_PORT
    if not MOCK:
        os.makedirs(BUS_DIR, exist_ok=True)  # ensure dir exists to read from; we never write bus files
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    mode = "MOCK" if MOCK else "LIVE"
    print(f"[jarvis-visualizer] {mode} server on http://127.0.0.1:{port}  (bus: {BUS_DIR})")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    main()
