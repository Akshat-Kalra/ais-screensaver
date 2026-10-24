#!/bin/bash
# Hand-assembles AISSaver.saver with swiftc (no Xcode needed).
# Usage: build.sh [--install]
set -euo pipefail
cd "$(dirname "$0")"

NAME=AISSaver
OUT=build/$NAME.saver
rm -rf ./build
mkdir -p "$OUT/Contents/MacOS" "$OUT/Contents/Resources" build/obj

for arch in arm64 x86_64; do
  swiftc -swift-version 6 -O -parse-as-library -module-name $NAME \
    -target "$arch-apple-macos13.0" \
    -emit-library -Xlinker -bundle \
    -framework ScreenSaver -framework WebKit -framework AppKit \
    AISSaverView.swift -o "build/obj/$NAME-$arch"
done
lipo -create build/obj/$NAME-arm64 build/obj/$NAME-x86_64 -output "$OUT/Contents/MacOS/$NAME"

cp Info.plist "$OUT/Contents/Info.plist"
for f in thumbnail.png thumbnail@2x.png; do
  if [ -f "$f" ]; then cp "$f" "$OUT/Contents/Resources/$f"; fi
done
rm -rf ./build/obj

codesign --force --deep --sign - "$OUT"
echo "Built $PWD/$OUT"

if [ "${1:-}" = "--install" ]; then
  DEST="$HOME/Library/Screen Savers"
  mkdir -p "$DEST"
  rm -rf "${DEST:?}/${NAME:?}.saver"
  cp -R "$OUT" "$DEST/$NAME.saver"
  killall legacyScreenSaver 2>/dev/null || true
  echo "Installed to $DEST/$NAME.saver"
fi
