#!/bin/bash
# Build the live wallpaper app and run it at login (needs the collector: scripts/install-agent.sh).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LABEL="com.akshatkalra.ais-screensaver.wallpaper"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
APP="$HOME/Applications/AIS Wallpaper.app"
LOGS="$HOME/Library/Logs/ais-screensaver"

"$ROOT/wallpaper/build.sh"
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
mkdir -p "$HOME/Applications" "$HOME/Library/LaunchAgents" "$LOGS"
rm -rf "$APP"
cp -R "$ROOT/wallpaper/build/AIS Wallpaper.app" "$APP"

cat > "$PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array><string>$APP/Contents/MacOS/AISWallpaper</string></array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><dict><key>SuccessfulExit</key><false/></dict>
  <key>LimitLoadToSessionType</key><string>Aqua</string>
  <key>ProcessType</key><string>Interactive</string>
  <key>StandardOutPath</key><string>$LOGS/wallpaper.log</string>
  <key>StandardErrorPath</key><string>$LOGS/wallpaper.log</string>
</dict>
</plist>
PLIST

launchctl bootstrap "gui/$(id -u)" "$PLIST"
echo "Wallpaper running. Remove it with scripts/uninstall-wallpaper.sh"
