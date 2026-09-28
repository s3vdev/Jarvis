#!/bin/bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
if ! command -v python3 >/dev/null 2>&1; then
  printf 'Python 3 fehlt. Bitte python3 installieren.\n'
  exit 1
fi
if [ ! -x "$ROOT/.venv/bin/python" ]; then
  python3 -m venv "$ROOT/.venv"
fi
"$ROOT/.venv/bin/python" -m pip install -q -r "$ROOT/requirements.txt"
if [ -d "$ROOT/.git/hooks" ] && [ -f "$ROOT/.githooks/commit-msg" ]; then
  cp "$ROOT/.githooks/commit-msg" "$ROOT/.git/hooks/commit-msg"
  chmod +x "$ROOT/.git/hooks/commit-msg"
fi
if [ ! -x /usr/bin/swiftc ]; then
  printf 'Xcode Command Line Tools fehlen (swiftc). xcode-select --install\n'
  exit 1
fi
HERMES="$("$ROOT/.venv/bin/python" -c 'import sys; sys.path.insert(0, "voice-line"); from jarvis_config import find_hermes; print(find_hermes() or "")')"
if [ -z "$HERMES" ]; then
  printf 'Hermes wurde nicht gefunden. Bitte Hermes installieren und anmelden, dann PATH prüfen.\n'
  exit 1
fi
printf 'Bereit. Hermes: %s\n' "$HERMES"
printf 'Start: Jarvis starten.command\n'
