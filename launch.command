#!/bin/bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
export TMPDIR="$ROOT/.run/tmp"
mkdir -p "$TMPDIR" "$ROOT/memory"
PY="$ROOT/.venv/bin/python"
if [ ! -x "$PY" ]; then
  printf 'Zuerst einmal Setup ausführen: setup.command\n'
  exit 1
fi
server_pid=""
cleanup() {
  if [ -n "$server_pid" ]; then
    kill "$server_pid" 2>/dev/null || true
    wait "$server_pid" 2>/dev/null || true
    rm -f "$ROOT/.run/visualizer.pid"
  fi
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM HUP
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
if [ "${JARVIS_NO_WINDOW:-${JARVIS_NO_BROWSER:-0}}" != 1 ]; then
  window_app="$("$ROOT/voice-visualizer/build_window.sh")"
  open "$window_app"
fi
printf 'Einfach sprechen, eine Pause schickt die Frage. Kein Enter. Strg+C beendet Jarvis und das Fenster.\n'
printf 'PAUSE und ZUHÖREN stehen unten im kleinen Jarvis-Fenster.\n'
"$PY" "$ROOT/voice-line/voice_line.py"
