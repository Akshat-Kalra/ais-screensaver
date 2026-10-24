#!/bin/bash
# Stop and remove the collector LaunchAgent (keeps collected data and your API key).
set -euo pipefail
LABEL="com.akshatkalra.ais-screensaver.collector"
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
rm -f "$HOME/Library/LaunchAgents/$LABEL.plist"
echo "Collector stopped and removed."
echo "Data remains in ~/Library/Application Support/ais-screensaver (delete it to free space)."
