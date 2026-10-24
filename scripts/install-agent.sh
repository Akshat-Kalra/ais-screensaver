#!/bin/bash
# Install + start the collector as a LaunchAgent (runs at login, restarts if it dies).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LABEL="com.akshatkalra.ais-screensaver.collector"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOGS="$HOME/Library/Logs/ais-screensaver"
UV="$(command -v uv || echo /opt/homebrew/bin/uv)"

if [ ! -x "$UV" ]; then
  echo "uv not found (expected at /opt/homebrew/bin/uv). brew install uv" >&2
  exit 1
fi
if [ -z "${AISSTREAM_API_KEY:-}" ] && ! grep -qs '^AISSTREAM_API_KEY=.' "$HOME/.config/ais-screensaver/env"; then
  echo "No aisstream.io API key configured." >&2
  echo "Get a free key at https://aisstream.io, then run: scripts/set-key.sh <KEY>" >&2
  exit 1
fi

mkdir -p "$LOGS" "$HOME/Library/LaunchAgents"
(cd "$ROOT/collector" && "$UV" sync --quiet --no-dev)

cat > "$PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$UV</string><string>run</string><string>--no-dev</string><string>--project</string>
    <string>$ROOT/collector</string><string>aissaver-collector</string>
  </array>
  <key>WorkingDirectory</key><string>$ROOT/collector</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>30</integer>
  <key>ProcessType</key><string>Background</string>
  <key>LowPriorityIO</key><true/>
  <key>StandardOutPath</key><string>$LOGS/collector.log</string>
  <key>StandardErrorPath</key><string>$LOGS/collector.log</string>
</dict>
</plist>
PLIST

launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
echo "Collector running. Logs: $LOGS/collector.log"
echo "Check: curl -s http://127.0.0.1:47823/api/health"
