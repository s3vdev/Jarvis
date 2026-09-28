#!/bin/bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
export TMPDIR="$ROOT/.run/tmp"
mkdir -p "$TMPDIR" "$ROOT/memory" "$ROOT/.run"
PY="$ROOT/.venv/bin/python"
if [ ! -x "$PY" ]; then
  printf 'Zuerst einmal Setup ausführen: setup.command\n'
  exit 1
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
  printf '%s\n' "$1" > "$ROOT/.run/visualizer.pid"
  printf '%s\n' "$2" > "$ROOT/.run/voice.pid"
  printf '%s\n' "$1" > "$BUS/.visualizer.pid"
  printf '%s\n' "$2" > "$BUS/.voice.pid"
  printf '%s\n%s\n' "$1" "$2" > "$BUS/.jarvis.pids"
}

clear_pids() {
  rm -f "$ROOT/.run/visualizer.pid" "$ROOT/.run/voice.pid" \
    "$BUS/.visualizer.pid" "$BUS/.voice.pid" "$BUS/.jarvis.pids"
}

export PATH="$HOME/.local/bin:$PATH"
HERMES="${JARVIS_HERMES:-}"
if [ -z "$HERMES" ]; then
  HERMES="$("$PY" -c 'import sys; sys.path.insert(0, "voice-line"); from jarvis_config import find_hermes; print(find_hermes() or "")')"
fi
if [ -z "$HERMES" ] || [ ! -x "$HERMES" ]; then
  printf 'Hermes wurde nicht gefunden. Bitte die eigene Hermes-Installation prüfen.\n'
  exit 1
fi
export JARVIS_HERMES="$HERMES"
"$PY" -c 'import sys; sys.path.insert(0, "voice-line"); from jarvis_config import load_config; c=load_config(); print("Hermes: Profil %s · %s · %s." % (c["profile"], c["model"], c["provider"]))'
printf 'Freigabepflichtige Aktionen werden hier verweigert; keine Sicherheitsumgehung.\n'

NO_WINDOW="${JARVIS_NO_WINDOW:-${JARVIS_NO_BROWSER:-0}}"
PACKAGED="$ROOT/dist/Jarvis.app"
if [ "$NO_WINDOW" != 1 ] && [ -d "$PACKAGED" ]; then
  open "$PACKAGED"
  printf 'Jarvis-App geöffnet. Beenden über die Menüleiste.\n'
  exit 0
fi
if [ "$NO_WINDOW" = 1 ]; then
  server_pid=""
  cleanup() {
    if [ -n "${server_pid:-}" ]; then
      kill "$server_pid" 2>/dev/null || true
      wait "$server_pid" 2>/dev/null || true
    fi
    rm -f "$ROOT/.run/visualizer.pid"
  }
  trap cleanup EXIT
  trap 'exit 130' INT
  trap 'exit 143' TERM HUP
  # Do not reuse or kill an unrelated service on this port.
  "$PY" -c 'import socket; s=socket.socket(); s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1); s.bind(("127.0.0.1",8777)); s.close()'
  "$PY" -u "$ROOT/voice-visualizer/server.py" > "$ROOT/.run/visualizer.log" 2>&1 &
  server_pid=$!
  printf '%s\n' "$server_pid" > "$ROOT/.run/visualizer.pid"
  "$PY" -c 'import urllib.request,time
for attempt in range(50):
    try:
        print(urllib.request.urlopen("http://127.0.0.1:8777/state",timeout=1).read().decode()); break
    except OSError: time.sleep(0.1)
else: raise SystemExit("Visualizer konnte nicht gestartet werden")'
  printf 'Einfach sprechen, eine Pause schickt die Frage. Kein Enter.\n'
  "$PY" "$ROOT/voice-line/voice_line.py"
  exit 0
fi

running_visualizer="$(read_pid "$ROOT/.run/visualizer.pid" || true)"
running_voice="$(read_pid "$ROOT/.run/voice.pid" || true)"
if pid_alive "$running_visualizer" && pid_alive "$running_voice"; then
  if "$PY" -c 'import urllib.request; urllib.request.urlopen("http://127.0.0.1:8777/state",timeout=1).read()' >/dev/null 2>&1; then
    window_app="$("$ROOT/voice-visualizer/build_window.sh")"
    open "$window_app"
    printf 'Jarvis läuft bereits im Hintergrund. Fenster geöffnet. Beenden über die Menüleiste.\n'
    exit 0
  fi
fi

# Do not reuse or kill an unrelated service on this port.
"$PY" -c 'import socket; s=socket.socket(); s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1); s.bind(("127.0.0.1",8777)); s.close()'

server_pid=""
voice_pid=""
startup_cleanup() {
  if [ -n "${server_pid:-}" ]; then
    kill "$server_pid" 2>/dev/null || true
  fi
  if [ -n "${voice_pid:-}" ]; then
    kill "$voice_pid" 2>/dev/null || true
  fi
  clear_pids
}
trap startup_cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM HUP

nohup "$PY" -u "$ROOT/voice-visualizer/server.py" >> "$ROOT/.run/visualizer.log" 2>&1 </dev/null &
server_pid=$!
"$PY" -c 'import urllib.request,time
for attempt in range(50):
    try:
        print(urllib.request.urlopen("http://127.0.0.1:8777/state",timeout=1).read().decode()); break
    except OSError: time.sleep(0.1)
else: raise SystemExit("Visualizer konnte nicht gestartet werden")'
nohup "$PY" -u "$ROOT/voice-line/voice_line.py" --daemon >> "$ROOT/.run/voice.log" 2>&1 </dev/null &
voice_pid=$!
write_pids "$server_pid" "$voice_pid"
disown -a 2>/dev/null || true

window_app="$("$ROOT/voice-visualizer/build_window.sh")"
open "$window_app"
printf 'Jarvis läuft im Hintergrund. Das Terminal kann geschlossen werden.\n'
printf 'Beenden über das Jarvis-Symbol in der Menüleiste.\n'
trap - EXIT INT TERM HUP
exit 0
