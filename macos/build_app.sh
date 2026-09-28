#!/bin/bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
if [ ! -x "$ROOT/.venv/bin/python3" ]; then
  printf 'Zuerst einmal Setup ausführen: setup.command\n' >&2
  exit 1
fi
if [ ! -x /usr/bin/swiftc ]; then
  printf 'Xcode Command Line Tools fehlen (swiftc). xcode-select --install\n' >&2
  exit 1
fi

DIST="$ROOT/dist"
APP="$DIST/Jarvis.app"
CONTENTS="$APP/Contents"
MACOS="$CONTENTS/MacOS"
RES="$CONTENTS/Resources"
ICONSET="$ROOT/macos/AppIcon.iconset"
PNG="$ROOT/macos/jarvis-app-icon.png"

rm -rf "$APP" "$ICONSET"
mkdir -p "$MACOS" "$RES" "$ICONSET"

if [ -f "$PNG" ]; then
  for size in 16 32 128 256 512; do
    /usr/bin/sips -z "$size" "$size" "$PNG" --out "$ICONSET/icon_${size}x${size}.png" >/dev/null
  done
  /usr/bin/sips -z 32 32 "$PNG" --out "$ICONSET/icon_16x16@2x.png" >/dev/null
  /usr/bin/sips -z 64 64 "$PNG" --out "$ICONSET/icon_32x32@2x.png" >/dev/null
  /usr/bin/sips -z 256 256 "$PNG" --out "$ICONSET/icon_128x128@2x.png" >/dev/null
  /usr/bin/sips -z 512 512 "$PNG" --out "$ICONSET/icon_256x256@2x.png" >/dev/null
  /usr/bin/sips -z 1024 1024 "$PNG" --out "$ICONSET/icon_512x512@2x.png" >/dev/null
  /usr/bin/iconutil -c icns -o "$RES/AppIcon.icns" "$ICONSET"
  rm -rf "$ICONSET"
fi

ARCH="$(uname -m)"
case "$ARCH" in
  x86_64) TARGET="x86_64-apple-macos13.0" ;;
  *) TARGET="arm64-apple-macos13.0" ;;
esac
/usr/bin/swiftc -O -target "$TARGET" -o "$MACOS/Jarvis" "$ROOT/voice-visualizer/JarvisWindow.swift"
cp "$ROOT/macos/Info.plist" "$CONTENTS/Info.plist"
cp "$ROOT/macos/launch_backend.sh" "$RES/launch_backend.sh"
chmod +x "$RES/launch_backend.sh" "$MACOS/Jarvis"

mkdir -p "$RES/app/voice-line" "$RES/app/voice-visualizer" "$RES/app/memory"
rsync -a --delete --exclude '__pycache__' --exclude '*.pyc' "$ROOT/voice-line/" "$RES/app/voice-line/"
rsync -a "$ROOT/voice-visualizer/server.py" "$ROOT/voice-visualizer/index.html" "$RES/app/voice-visualizer/"
cp "$ROOT/jarvis.json" "$ROOT/requirements.txt" "$ROOT/NOTICE" "$RES/app/"
[ -f "$ROOT/AGENTS.md" ] && cp "$ROOT/AGENTS.md" "$RES/app/"
[ -f "$ROOT/memory/VAULT-INDEX.md" ] && cp "$ROOT/memory/VAULT-INDEX.md" "$RES/app/memory/"
rsync -a --delete --exclude '__pycache__' --exclude '*.pyc' "$ROOT/.venv/" "$RES/venv/"
chmod +x "$MACOS/Jarvis" "$RES/launch_backend.sh" "$RES/venv/bin/"* 2>/dev/null || true
/usr/bin/codesign --force --sign - "$MACOS/Jarvis" >/dev/null 2>&1 || true

printf 'App: %s\n' "$APP"
printf 'Nach Programme ziehen und wie eine normale App öffnen.\n'
