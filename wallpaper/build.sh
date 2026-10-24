#!/bin/bash
# Hand-assembles "AIS Wallpaper.app" with swiftc (no Xcode needed).
# Install it with scripts/install-wallpaper.sh.
set -euo pipefail
cd "$(dirname "$0")"

NAME=AISWallpaper
OUT="build/AIS Wallpaper.app"
rm -rf ./build
mkdir -p "$OUT/Contents/MacOS" build/obj

for arch in arm64 x86_64; do
  swiftc -swift-version 6 -O -parse-as-library -module-name $NAME \
    -target "$arch-apple-macos13.0" \
    -framework WebKit -framework AppKit \
    AISWallpaper.swift -o "build/obj/$NAME-$arch"
done
lipo -create build/obj/$NAME-arm64 build/obj/$NAME-x86_64 -output "$OUT/Contents/MacOS/$NAME"
cp Info.plist "$OUT/Contents/Info.plist"
rm -rf ./build/obj

codesign --force --deep --sign - "$OUT"
echo "Built $PWD/$OUT"
