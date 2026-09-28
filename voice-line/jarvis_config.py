"""Portable Jarvis settings. No machine paths and no secrets."""

import json
import os
from pathlib import Path
import re
import shutil


ROOT = Path(__file__).resolve().parents[1]
_TOKEN = re.compile(r"^[A-Za-z0-9._:-]{1,64}$")
_DEFAULTS = {
    "profile": "default",
    "model": "gpt-6-astra",
    "provider": "openai-codex",
}
_ENV = {
    "profile": "JARVIS_HERMES_PROFILE",
    "model": "JARVIS_HERMES_MODEL",
    "provider": "JARVIS_HERMES_PROVIDER",
}


def _clean(value):
    text = (value or "").strip()
    if not _TOKEN.fullmatch(text):
        return ""
    return text


def _from_file(path):
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    if not isinstance(raw, dict):
        return {}
    data = {}
    for key in _DEFAULTS:
        cleaned = _clean(raw.get(key))
        if cleaned:
            data[key] = cleaned
    return data


def load_config():
    """Env, then jarvis.local.json, then jarvis.json, then built-in defaults."""
    data = dict(_DEFAULTS)
    data.update(_from_file(ROOT / "jarvis.json"))
    data.update(_from_file(ROOT / "jarvis.local.json"))
    for key, name in _ENV.items():
        cleaned = _clean(os.environ.get(name))
        if cleaned:
            data[key] = cleaned
    return data


def public_hermes(payload=None):
    cfg = load_config()
    extra = payload if isinstance(payload, dict) else {}
    data = {
        "found": bool(extra.get("found")),
        "connected": bool(extra.get("connected")),
        "profile": cfg["profile"],
        "model": cfg["model"],
        "provider": cfg["provider"],
    }
    for key in ("profile", "model", "provider"):
        cleaned = _clean(extra.get(key))
        if cleaned:
            data[key] = cleaned
    return data


def find_hermes():
    """Use JARVIS_HERMES, PATH, ~/.local/bin, or the newest Hermes install. No fixed user path."""
    explicit = os.environ.get("JARVIS_HERMES") or ""
    if explicit and os.path.isfile(explicit) and os.access(explicit, os.X_OK):
        return explicit
    found = shutil.which("hermes")
    if found:
        return found
    local = Path.home() / ".local" / "bin" / "hermes"
    if local.is_file() and os.access(local, os.X_OK):
        return str(local)
    installs = Path.home() / ".hermes" / "installs"
    if not installs.is_dir():
        return ""
    newest = ""
    newest_mtime = -1.0
    for candidate in installs.glob("*/environments/*/venv/bin/hermes"):
        try:
            if not candidate.is_file() or not os.access(candidate, os.X_OK):
                continue
            mtime = candidate.stat().st_mtime
        except OSError:
            continue
        if mtime > newest_mtime:
            newest = str(candidate)
            newest_mtime = mtime
    return newest
