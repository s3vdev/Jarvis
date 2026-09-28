#!/bin/bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="$ROOT/voice-visualizer/JarvisWindow.swift"
APP="$ROOT/.run/Jarvis.app"
CONTENTS="$APP/Contents"
MACOS="$CONTENTS/MacOS"
BIN="$MACOS/Jarvis"
mkdir -p "$MACOS"
ARCH="$(uname -m)"
case "$ARCH" in
  x86_64) TARGET="x86_64-apple-macos13.0" ;;
  *) TARGET="arm64-apple-macos13.0" ;;
esac
if [ ! -x "$BIN" ] || [ "$SRC" -nt "$BIN" ]; then
  /usr/bin/swiftc -O -target "$TARGET" -o "$BIN" "$SRC"
fi
cat > "$CONTENTS/Info.plist" <<'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>Jarvis</string>
  <key>CFBundleIdentifier</key><string>local.jarvis.window</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleExecutable</key><string>Jarvis</string>
  <key>LSMinimumSystemVersion</key><string>13.0</string>
  <key>NSHighResolutionCapable</key><true/>
</dict>
</plist>
EOF
printf '%s\n' "$APP"
