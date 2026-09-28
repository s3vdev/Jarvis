"""User-owned notes in ./memory/MEMORY.md. Write only on an explicit save."""

from pathlib import Path
import re


MEMORY_NAME = "MEMORY.md"
MAX_CHARS = 2000
_EMPTY = "Noch keine persönlichen Informationen gespeichert."
_HEADING = "# Gedächtnis"
_SECRET = re.compile(
    r"(-----BEGIN [A-Z ]+PRIVATE KEY-----)|"
    r"\bsk-[A-Za-z0-9]{16,}\b|"
    r"(?i)\b(api[_-]?key|password|passwd|secret|token)\s*[:=]",
)
_ROOT = None


def set_memory_root(path):
    global _ROOT
    try:
        _ROOT = Path(path).expanduser().resolve()
    except (OSError, RuntimeError):
        _ROOT = None


def memory_dir():
    root = _ROOT or Path(__file__).resolve().parents[1]
    folder = (root / "memory").resolve()
    folder.relative_to(root.resolve())
    return folder


def memory_file():
    path = (memory_dir() / MEMORY_NAME).resolve()
    path.relative_to(memory_dir())
    if path.name != MEMORY_NAME:
        raise ValueError("invalid memory file")
    return path


def _clean(text):
    raw = (text or "").replace("\x00", "")
    raw = raw.replace("\r\n", "\n").replace("\r", "\n")
    raw = re.sub(r"[ \t]+\n", "\n", raw)
    raw = raw.strip()
    if len(raw) > MAX_CHARS:
        raw = raw[:MAX_CHARS].rstrip()
    return raw


def looks_secret(text):
    return bool(_SECRET.search(text or ""))


def _user_body(raw):
    text = _clean(raw)
    if not text:
        return ""
    lines = text.splitlines()
    if lines and lines[0].strip() == _HEADING:
        lines = lines[1:]
    body = "\n".join(lines).strip()
    if not body or body == _EMPTY:
        return ""
    return body


def load_notes():
    """Notes the user saved. Empty string means nothing stored."""
    try:
        raw = memory_file().read_text(encoding="utf-8")
    except OSError:
        return ""
    return _user_body(raw)


def save_notes(text):
    """Replace the notes. Returns the stored body or None if rejected."""
    body = _user_body(text)
    if looks_secret(body):
        return None
    folder = memory_dir()
    folder.mkdir(parents=True, exist_ok=True)
    path = memory_file()
    if body:
        content = _HEADING + "\n\n" + body + "\n"
    else:
        content = _HEADING + "\n\n" + _EMPTY + "\n"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)
    return body


def add_note(line):
    """Append one spoken note. Returns the new body or None if rejected."""
    piece = _clean(line)
    if not piece or looks_secret(piece):
        return None
    current = load_notes()
    if piece in current.splitlines():
        return current
    merged = (current + "\n" + piece).strip() if current else piece
    return save_notes(merged)


def public_memory():
    return {"text": load_notes(), "max": MAX_CHARS}
