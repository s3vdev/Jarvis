"""Local Jarvis skills that must not wait for Hermes.

Clock, timer, volume, repeat and a small allow-list of Mac opens.
Opens never run until the window writes an explicit yes. Hermes approvals
are never confirmed here.
"""

from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse
import re
import subprocess


APPS = {
    "safari": "Safari",
    "mail": "Mail",
    "musik": "Music",
    "music": "Music",
    "kalender": "Calendar",
    "notizen": "Notes",
    "finder": "Finder",
    "terminal": "Terminal",
    "einstellungen": "System Settings",
    "systemeinstellungen": "System Settings",
    "nachrichten": "Messages",
    "fotos": "Photos",
    "karten": "Maps",
}

_WEEKDAYS = (
    "Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag",
)
_MONTHS = (
    "Januar", "Februar", "März", "April", "Mai", "Juni",
    "Juli", "August", "September", "Oktober", "November", "Dezember",
)
_WORD_NUM = {
    "ein": 1, "eine": 1, "einen": 1, "eins": 1, "zwei": 2, "drei": 3,
    "vier": 4, "fuenf": 5, "fünf": 5, "sechs": 6, "sieben": 7, "acht": 8,
    "neun": 9, "zehn": 10, "elf": 11, "zwoelf": 12, "zwölf": 12,
    "fuenfzehn": 15, "fünfzehn": 15, "zwanzig": 20, "dreissig": 30,
    "dreißig": 30, "fuenfundvierzig": 45, "fünfundvierzig": 45, "sechzig": 60,
}
_VOL_ORDER = ("leise", "normal", "laut")
_REPEAT = re.compile(
    r"^(?:nochmal|noch\s+einmal|wiederhole(?:\s+das)?|sag\s+das\s+noch(?:\s*mal)?)$",
    re.I,
)
_CLOCK = re.compile(
    r"^(?:wie\s+spät(?:\s+ist\s+es)?|wie\s+viel\s+uhr(?:\s+ist\s+es)?|"
    r"welche\s+uhrzeit|wie\s+spaet(?:\s+ist\s+es)?|wie\s+spat(?:\s+ist\s+es)?)$",
    re.I,
)
_DATE = re.compile(
    r"^(?:welches?\s+datum|welcher\s+(?:tag|wochentag)|welcher\s+tag\s+ist\s+heute|"
    r"was\s+ist\s+heute)$",
    re.I,
)
_VOLUME = re.compile(
    r"^(?:lauter|leiser|lautstärke\s+(?:leise|normal|laut)|"
    r"(?:mach(?:e)?|stell(?:e)?)\s+(?:es\s+)?(?:lauter|leiser))$",
    re.I,
)
_TIMER_CANCEL = re.compile(
    r"^(?:timer\s+(?:aus|stopp|stoppen|abbrechen)|wecker\s+(?:aus|stopp))$",
    re.I,
)
_TIMER = re.compile(
    r"^(?:(?:stell(?:e)?|setze|mach(?:e)?)\s+)?"
    r"(?:einen\s+|den\s+)?"
    r"(?:timer|wecker)"
    r"(?:\s+(?:auf|fuer|für|in))?\s+"
    r"(?P<num>\d+|ein|eine|einen|eins|zwei|drei|vier|fuenf|fünf|sechs|sieben|"
    r"acht|neun|zehn|elf|zwoelf|zwölf|fuenfzehn|fünfzehn|zwanzig|dreissig|"
    r"dreißig|fuenfundvierzig|fünfundvierzig|sechzig)\s*"
    r"(?P<unit>sekunden|sekunde|minuten|minute|stunden|stunde)$",
    re.I,
)
_TIMER_IN = re.compile(
    r"^(?:erinner(?:e)?\s+mich\s+in|in)\s+"
    r"(?P<num>\d+|ein|eine|einen|eins|zwei|drei|vier|fuenf|fünf|sechs|sieben|"
    r"acht|neun|zehn|elf|zwoelf|zwölf)\s*"
    r"(?P<unit>sekunden|sekunde|minuten|minute|stunden|stunde)"
    r"(?:\s+(?:erinnern|timer|wecker))?$",
    re.I,
)
_APP = re.compile(
    r"^(?:öffne|oeffne|starte|zeig(?:e)?)\s+(?:bitte\s+)?(?:den\s+|die\s+|das\s+)?"
    r"(?P<name>safari|mail|musik|music|kalender|notizen|finder|terminal|"
    r"einstellungen|systemeinstellungen|nachrichten|fotos|karten)"
    r"(?:\s+bitte)?$",
    re.I,
)
_URL = re.compile(
    r"^(?:öffne|oeffne|zeig(?:e)?)\s+(?:bitte\s+)?"
    r"(?P<url>(?:https?://)?[a-z0-9][a-z0-9.-]*\.[a-z]{2,}(?:/[^\s]*)?)$",
    re.I,
)
_FILE_BARE = re.compile(
    r"^(?:öffne|oeffne|zeig(?:e)?(?:\s+mir)?|lies)\s+(?:bitte\s+)?"
    r"(?:die\s+|das\s+|den\s+)?(?:datei|dokument)s?$",
    re.I,
)
_FILE_NAMED = re.compile(
    r"^(?:(?:öffne|oeffne|zeig(?:e)?(?:\s+mir)?|lies)\s+(?:bitte\s+)?)?"
    r"(?:die\s+|das\s+|den\s+)?"
    r"(?:datei|dokument|ordner)\s+(?P<name>.+)$",
    re.I,
)
_FILE_TRAIL = re.compile(
    r"^(?:(?:öffne|oeffne|zeig(?:e)?(?:\s+mir)?|lies)\s+(?:bitte\s+)?)?"
    r"(?:die\s+|das\s+|den\s+)?"
    r"(?P<name>.+?)\s+(?:datei|dokument)s?$",
    re.I,
)
_FILE_EXT = re.compile(
    r"^(?:(?:öffne|oeffne|zeig(?:e)?(?:\s+mir)?)\s+(?:bitte\s+)?)?"
    r"(?:die\s+|das\s+|den\s+)?"
    r"(?P<name>[\w. äöüß-]{2,80}\.(?:pdf|txt|md|doc|docx|pages|png|jpg|jpeg|"
    r"gif|csv|xlsx|key|ppt|pptx))"
    r"(?:\s+(?:datei|dokument)s?)?$",
    re.I,
)
_FILE_READ = re.compile(
    r"^(?:was\s+steht\s+in\s+(?:der\s+|dem\s+)?(?:datei|dokument)\s+(?P<name>.+))$",
    re.I,
)
_REMEMBER = re.compile(
    r"^(?:merk(?:e)?\s+dir|erinnere\s+dich(?:\s+daran)?)\s+"
    r"(?:bitte\s+)?(?:dass\s+|an\s+)?(?P<note>.+)$",
    re.I,
)
_RECALL = re.compile(
    r"^(?:was\s+weißt\s+du\s+(?:über\s+mich|noch)|was\s+merkst\s+du\s+dir|"
    r"welche\s+erinnerungen|was\s+steht\s+in\s+den\s+erinnerungen)$",
    re.I,
)
MAX_TIMER_S = 2 * 60 * 60
_BLOCKED_PARTS = {".ssh", ".hermes", ".aws", ".gnupg", ".kube"}
_BLOCKED_NAMES = {"auth.json", ".env", "id_rsa", "id_ed25519", "credentials"}
_SKIP_DIRS = {".git", ".venv", "node_modules", "__pycache__", ".run", ".cursor"}
_FILE_ROOTS = []
_MAX_WALK = 3


def _norm(text):
    raw = re.sub(r"[,:;]+", " ", (text or "").strip())
    raw = re.sub(r"[\s.!?]+$", "", raw)
    return re.sub(r"\s+", " ", raw).strip()


def _number(token):
    token = (token or "").lower()
    if token.isdigit():
        return int(token)
    return _WORD_NUM.get(token)


def _seconds(num, unit):
    value = _number(num)
    if value is None or value < 1:
        return None
    unit = unit.lower()
    if unit.startswith("sekunde"):
        seconds = value
    elif unit.startswith("minute"):
        seconds = value * 60
    else:
        seconds = value * 3600
    if seconds > MAX_TIMER_S:
        return None
    return seconds


def _pretty_duration(seconds):
    if seconds < 60:
        return "eine Sekunde" if seconds == 1 else "%d Sekunden" % seconds
    if seconds % 3600 == 0:
        hours = seconds // 3600
        return "eine Stunde" if hours == 1 else "%d Stunden" % hours
    if seconds % 60 == 0:
        minutes = seconds // 60
        return "eine Minute" if minutes == 1 else "%d Minuten" % minutes
    return "%d Sekunden" % seconds


def timer_phrase(seconds):
    return _pretty_duration(seconds)


def clock_text(now=None, kind="time"):
    now = now or datetime.now()
    if kind == "date":
        return "Heute ist %s, der %d. %s." % (
            _WEEKDAYS[now.weekday()], now.day, _MONTHS[now.month - 1])
    return "Es ist %d Uhr %02d." % (now.hour, now.minute)


def next_volume(current, spoken):
    spoken = _norm(spoken).lower()
    if "lautstärke leise" in spoken or spoken.endswith("lautstärke leise"):
        return "leise"
    if "lautstärke laut" in spoken:
        return "laut"
    if "lautstärke normal" in spoken:
        return "normal"
    index = _VOL_ORDER.index(current) if current in _VOL_ORDER else 1
    if "leiser" in spoken:
        return _VOL_ORDER[max(0, index - 1)]
    return _VOL_ORDER[min(len(_VOL_ORDER) - 1, index + 1)]


def set_file_roots(paths):
    """Folders Jarvis may look in. Resolve once; never follow a user path blindly."""
    global _FILE_ROOTS
    roots = []
    for raw in paths or []:
        try:
            path = Path(raw).expanduser().resolve()
        except (OSError, RuntimeError):
            continue
        if path.is_dir():
            roots.append(path)
    _FILE_ROOTS = roots


def file_roots():
    if _FILE_ROOTS:
        return list(_FILE_ROOTS)
    home = Path.home()
    return [item for item in (
        home / "Desktop", home / "Documents", home / "Downloads", home,
    ) if item.is_dir()]


def _clean_filename(name):
    text = re.sub(r"^(?:die|das|den|der)\s+", "", _norm(name), flags=re.I)
    text = text.strip(" .")
    if not text or "/" in text or "\\" in text or ".." in text:
        return ""
    if len(text) > 80:
        return ""
    return text


def _file_key(name):
    return re.sub(r"[\s_\-]+", "", (name or "").lower())


def _walk_files(root, depth=0):
    try:
        children = list(Path(root).iterdir())
    except OSError:
        return
    for child in children:
        if child.name.startswith(".") or child.name in _SKIP_DIRS:
            continue
        if any(part.lower() in _BLOCKED_PARTS for part in child.parts):
            continue
        if child.is_file():
            yield child
        elif child.is_dir() and depth < _MAX_WALK:
            yield from _walk_files(child, depth + 1)


def is_safe_file(path):
    try:
        resolved = Path(path).resolve()
    except (OSError, RuntimeError):
        return False
    if not resolved.exists():
        return False
    if resolved.name.lower() in _BLOCKED_NAMES:
        return False
    if any(part.lower() in _BLOCKED_PARTS for part in resolved.parts):
        return False
    for root in file_roots():
        try:
            resolved.relative_to(root)
            return True
        except ValueError:
            continue
    return False


def find_file(name):
    """Return one safe path if the spoken name matches exactly one file."""
    needle = _clean_filename(name)
    if not needle:
        return ""
    needle_l = needle.lower()
    needle_k = _file_key(needle)
    if len(needle_k) < 3:
        return ""
    matches = []
    for root in file_roots():
        for child in _walk_files(root):
            label = child.name.lower()
            stem = child.stem.lower()
            if (
                label == needle_l
                or stem == needle_l
                or _file_key(label) == needle_k
                or _file_key(stem) == needle_k
            ):
                if is_safe_file(child):
                    matches.append(child.resolve())
    unique = []
    seen = set()
    for item in matches:
        key = str(item)
        if key not in seen:
            seen.add(key)
            unique.append(item)
    if len(unique) != 1:
        return ""
    return str(unique[0])


def safe_url(raw):
    text = (raw or "").strip()
    if "://" not in text:
        text = "https://" + text
    parsed = urlparse(text)
    if parsed.scheme not in ("http", "https"):
        return ""
    if parsed.username or parsed.password:
        return ""
    host = (parsed.hostname or "").lower()
    if not host or host == "localhost" or host.endswith(".local"):
        return ""
    if re.fullmatch(r"\d{1,3}(?:\.\d{1,3}){3}", host):
        return ""
    if "." not in host:
        return ""
    return parsed.geturl()


def public_confirm(action):
    """What the window may show. Never includes a shell command."""
    if not isinstance(action, dict):
        return None
    kind = action.get("kind")
    if kind == "notice":
        title = action.get("title") or "Hinweis"
        detail = action.get("detail") or ""
        if not isinstance(title, str) or not isinstance(detail, str):
            return None
        return {
            "id": action.get("id", ""),
            "kind": "notice",
            "title": title[:80],
            "detail": detail[:240],
        }
    if kind == "open_app":
        app = action.get("app")
        if app not in APPS.values():
            return None
        return {
            "id": action.get("id", ""),
            "kind": "action",
            "title": "%s öffnen?" % app,
            "detail": "Nur wenn du im Fenster Ja drückst.",
        }
    if kind == "open_url":
        url = safe_url(action.get("url"))
        if not url:
            return None
        return {
            "id": action.get("id", ""),
            "kind": "action",
            "title": "Diese Seite öffnen?",
            "detail": url,
        }
    if kind == "open_file":
        path = action.get("path")
        if not is_safe_file(path):
            return None
        return {
            "id": action.get("id", ""),
            "kind": "action",
            "title": "Datei öffnen?",
            "detail": Path(path).name[:80],
        }
    return None


def execute_action(action):
    """Run one already-confirmed allow-listed action. Returns spoken German."""
    shown = public_confirm(action)
    if not shown or shown["kind"] != "action":
        return ""
    if action.get("kind") == "open_app":
        app = action["app"]
        completed = subprocess.run(
            ["/usr/bin/open", "-a", app],
            capture_output=True, text=True, timeout=10)
        if completed.returncode:
            return "Ich konnte %s nicht öffnen." % app
        return "%s ist offen." % app
    if action.get("kind") == "open_url":
        url = safe_url(action.get("url"))
        if not url:
            return ""
        completed = subprocess.run(
            ["/usr/bin/open", url],
            capture_output=True, text=True, timeout=10)
        if completed.returncode:
            return "Ich konnte die Seite nicht öffnen."
        return "Die Seite ist offen."
    path = action.get("path")
    if not is_safe_file(path):
        return ""
    completed = subprocess.run(
        ["/usr/bin/open", path],
        capture_output=True, text=True, timeout=10)
    if completed.returncode:
        return "Ich konnte die Datei nicht öffnen."
    return "Die Datei ist offen."


def match_skill(text):
    """Return a local action dict, or None so Hermes can take the sentence."""
    raw = _norm(text)
    if not raw:
        return None
    if _REPEAT.match(raw):
        return {"kind": "repeat"}
    if _RECALL.match(raw):
        return {"kind": "memory_recall"}
    remembered = _REMEMBER.match(raw)
    if remembered:
        note = remembered.group("note").strip()
        if note:
            return {"kind": "memory_add", "note": note}
    if _CLOCK.match(raw):
        return {"kind": "clock", "what": "time"}
    if _DATE.match(raw):
        return {"kind": "clock", "what": "date"}
    if _VOLUME.match(raw):
        return {"kind": "volume", "spoken": raw}
    if _TIMER_CANCEL.match(raw):
        return {"kind": "timer_cancel"}
    timer = _TIMER.match(raw) or _TIMER_IN.match(raw)
    if timer:
        seconds = _seconds(timer.group("num"), timer.group("unit"))
        if seconds:
            return {"kind": "timer", "seconds": seconds}
    app = _APP.match(raw)
    if app:
        key = app.group("name").lower()
        return {"kind": "open_app", "app": APPS[key]}
    url = _URL.match(raw)
    if url:
        cleaned = safe_url(url.group("url"))
        if cleaned:
            return {"kind": "open_url", "url": cleaned}
    if _FILE_BARE.match(raw):
        return {"kind": "open_file_missing"}
    named = (
        _FILE_NAMED.match(raw)
        or _FILE_EXT.match(raw)
        or _FILE_TRAIL.match(raw)
        or _FILE_READ.match(raw)
    )
    if named:
        path = find_file(named.group("name"))
        if not path:
            return {"kind": "open_file_missing"}
        return {"kind": "open_file", "path": path, "name": Path(path).name}
    return None
