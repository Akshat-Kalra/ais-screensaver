#!/bin/bash
# Store your aisstream.io API key for the collector. Usage: scripts/set-key.sh <KEY>
set -euo pipefail
if [ $# -ne 1 ] || [ -z "$1" ]; then
  echo "usage: $0 <AISSTREAM_API_KEY>   (free key at https://aisstream.io)" >&2
  exit 1
fi
DIR="$HOME/.config/ais-screensaver"
mkdir -p "$DIR"
umask 077
printf 'AISSTREAM_API_KEY=%s\n' "$1" > "$DIR/env"
chmod 600 "$DIR/env"
echo "Saved key to $DIR/env"
