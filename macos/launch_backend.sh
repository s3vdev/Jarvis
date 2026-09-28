#!/bin/bash
set -euo pipefail
ROOT="${JARVIS_ROOT:-}"
if [ -z "$ROOT" ] || [ ! -d "$ROOT" ]; then
  printf 'JARVIS_ROOT fehlt.\n' >&2
  exit 1
fi
cd "$ROOT"
HOME_DATA="${JARVIS_HOME:-$HOME/Library/Application Support/Jarvis}"
mkdir -p "$HOME_DATA/.run/tmp" "$HOME_DATA/memory"
export TMPDIR="$HOME_DATA/.run/tmp"
export JARVIS_ROOT="$ROOT"
export JARVIS_HOME="$HOME_DATA"
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"

PY="${JARVIS_PYTHON:-}"
if [ -z "$PY" ] || [ ! -x "$PY" ]; then
  if [ -x "$ROOT/../venv/bin/python3" ]; then
    PY="$ROOT/../venv/bin/python3"
  elif [ -x "$ROOT/.venv/bin/python3" ]; then
    PY="$ROOT/.venv/bin/python3"
  elif [ -x "$ROOT/.venv/bin/python" ]; then
    PY="$ROOT/.venv/bin/python"
  fi
fi
if [ ! -x "$PY" ]; then
  printf 'Python in der App fehlt. Bitte Setup ausführen.\n' >&2
  exit 1
fi
if [ -f "$ROOT/jarvis.local.json" ] && [ ! -f "$HOME_DATA/jarvis.local.json" ]; then
  cp "$ROOT/jarvis.local.json" "$HOME_DATA/jarvis.local.json"
fi

BUS="${HOME}/voice-line"
mkdir -p "$BUS"

read_pid() {
  [ -f "$1" ] || return 0
  tr -cd '0-9' < "$1"
}

pid_alive() {
  [ -n "${1:-}" ] && kill -0 "$1" 2>/dev/null
}

write_pids() {
  printf '%s\n' "$1" > "$HOME_DATA/.run/visualizer.pid"
  printf '%s\n' "$2" > "$HOME_DATA/.run/voice.pid"
  printf '%s\n' "$1" > "$BUS/.visualizer.pid"
  printf '%s\n' "$2" > "$BUS/.voice.pid"
  printf '%s\n%s\n' "$1" "$2" > "$BUS/.jarvis.pids"
}

HERMES="${JARVIS_HERMES:-}"
if [ -z "$HERMES" ]; then
  HERMES="$("$PY" -c 'import sys; sys.path.insert(0, "voice-line"); from jarvis_config import find_hermes; print(find_hermes() or "")')"
fi
if [ -z "$HERMES" ] || [ ! -x "$HERMES" ]; then
  printf 'Hermes wurde nicht gefunden. Bitte die eigene Hermes-Installation prüfen.\n' >&2
  exit 1
fi
export JARVIS_HERMES="$HERMES"

running_visualizer="$(read_pid "$HOME_DATA/.run/visualizer.pid" || true)"
running_voice="$(read_pid "$HOME_DATA/.run/voice.pid" || true)"
if pid_alive "$running_visualizer" && pid_alive "$running_voice"; then
  if "$PY" -c 'import urllib.request; urllib.request.urlopen("http://127.0.0.1:8777/state",timeout=1).read()' >/dev/null 2>&1; then
    exit 0
  fi
fi

"$PY" -c 'import socket; s=socket.socket(); s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1); s.bind(("127.0.0.1",8777)); s.close()'

nohup "$PY" -u "$ROOT/voice-visualizer/server.py" >> "$HOME_DATA/.run/visualizer.log" 2>&1 </dev/null &
server_pid=$!
"$PY" -c 'import urllib.request,time
for attempt in range(50):
    try:
        urllib.request.urlopen("http://127.0.0.1:8777/state",timeout=1).read(); break
    except OSError: time.sleep(0.1)
else: raise SystemExit("Visualizer konnte nicht gestartet werden")'
nohup "$PY" -u "$ROOT/voice-line/voice_line.py" --daemon >> "$HOME_DATA/.run/voice.log" 2>&1 </dev/null &
voice_pid=$!
write_pids "$server_pid" "$voice_pid"
exit 0
