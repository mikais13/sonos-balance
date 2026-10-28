#!/bin/zsh
# Builds SonosBalance.app (menu bar app) next to this script.
set -euo pipefail
cd "${0:a:h}"

app=SonosBalance.app
uv_path=$(command -v uv) || { echo "uv not found on PATH" >&2; exit 1; }

rm -rf "$app"
mkdir -p "$app/Contents/MacOS"
swiftc -O -parse-as-library -swift-version 5 -target arm64-apple-macos14 \
  SonosBalance.swift -o "$app/Contents/MacOS/SonosBalance"

cat > "$app/Contents/Info.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleIdentifier</key><string>com.mikaisomerville.sonos-balance</string>
  <key>CFBundleName</key><string>Sonos Balance</string>
  <key>CFBundleExecutable</key><string>SonosBalance</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
  <key>LSMinimumSystemVersion</key><string>14.0</string>
  <key>LSUIElement</key><true/>
  <key>NSLocalNetworkUsageDescription</key><string>Sonos Balance controls the volume of the Sonos speakers on your network.</string>
  <key>BackendScriptPath</key><string>$PWD/sonos_balance.py</string>
  <key>UvPath</key><string>$uv_path</string>
</dict>
</plist>
EOF

codesign --force --sign - "$app"
echo "Built $PWD/$app"
