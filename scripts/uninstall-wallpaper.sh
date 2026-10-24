#!/bin/bash
# Stop the live wallpaper and remove it (the collector and screensaver are untouched).
set -euo pipefail
LABEL="com.akshatkalra.ais-screensaver.wallpaper"
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
rm -f "$HOME/Library/LaunchAgents/$LABEL.plist"
rm -rf "$HOME/Applications/AIS Wallpaper.app"
echo "Wallpaper stopped and removed."
