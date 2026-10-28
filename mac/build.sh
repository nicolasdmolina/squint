#!/usr/bin/env bash
# Builds Squint.app and Squint-mac.zip into mac/build/: Apple Silicon only, ad-hoc signed (no
# Apple developer account, so people open it once with System Settings > Open Anyway).
#
# The app is a Swift window (mac/Squint.swift) plus a relocatable Python 3.12 (uv's
# python-build-standalone) holding the server and its locked dependencies. llama.cpp is built
# from source with GGML_NATIVE=OFF so the build runs on every M-series chip, not only this one.
# Needs macOS 14: the numpy and torch wheels are built for it. Models are not bundled: squint.desktop downloads them on first launch.
#
#   mac/build.sh            build (reuses the llama.cpp wheel in mac/build/wheels)
#   VERSION=0.2.0 mac/build.sh
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT=$PWD
OUT=$ROOT/mac/build
APP=$OUT/Squint.app
RES=$APP/Contents/Resources
VERSION=${VERSION:-0.1.0}
LLAMA=llama-cpp-python==0.3.36  # keep in step with server/pyproject.toml

step() { printf '\n== %s\n' "$*"; }

step "web UI"
(cd web && npm run build >/dev/null)

step "python runtime"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$RES" "$OUT/wheels"
PYSRC=$(cd / && uv python find --managed-python 3.12)
PYROOT=$(cd "$(dirname "$PYSRC")/.." && pwd -P)
rsync -a "$PYROOT/" "$RES/python/"
PY=$RES/python/bin/python3.12
find "$RES/python/lib" -name EXTERNALLY-MANAGED -delete

step "llama.cpp (portable build, cached)"
if ! ls "$OUT"/wheels/llama_cpp_python-*.whl >/dev/null 2>&1; then
  MACOSX_DEPLOYMENT_TARGET=13.0 CMAKE_ARGS="-DGGML_NATIVE=OFF -DGGML_METAL=ON -DGGML_METAL_EMBED_LIBRARY=ON" \
    "$PY" -m pip wheel --no-deps --no-cache-dir -w "$OUT/wheels" "$LLAMA"
fi

step "server and dependencies"
(cd server && uv export --frozen --no-dev --no-emit-project --no-hashes --quiet -o "$OUT/requirements.txt")
grep -v '^llama-cpp-python' "$OUT/requirements.txt" > "$OUT/requirements-pypi.txt"
uv pip install --quiet --python "$PY" --no-deps -r "$OUT/requirements-pypi.txt"
uv pip install --quiet --python "$PY" --no-deps "$OUT"/wheels/llama_cpp_python-*.whl
uv pip install --quiet --python "$PY" --no-deps --reinstall-package squint-server ./server

step "prune"
LIB=$RES/python/lib/python3.12
SITE=$LIB/site-packages
rm -rf "$LIB"/{test,idlelib,tkinter,turtledemo,ensurepip,lib2to3} "$RES"/python/lib/{tcl,tk,itcl,thread}* \
  "$RES/python/include" "$RES/python/share" "$SITE"/{pip,pip-*} "$SITE/torch/include" "$SITE/torch/share"
find "$RES/python/bin" ! -type d ! -name 'python3.12' ! -name python3 -delete
rm -rf "$RES/python/lib/pkgconfig"
find "$SITE" -type d \( -name tests -o -name testing \) -path '*/numpy/*' -prune -exec rm -rf {} +
find "$SITE" -type d -name tests -path '*/sympy/*' -prune -exec rm -rf {} +
find "$RES/python" -name __pycache__ -prune -exec rm -rf {} +
# The app runs python -B (nothing written into the signed bundle), so compile everything now.
"$PY" -m compileall -q -j0 --invalidation-mode unchecked-hash "$LIB" >/dev/null || true

step "resources"
cp -R web/dist "$RES/web"
mkdir -p "$RES/calibration"
cp calibration/thresholds.json calibration/report.json "$RES/calibration/"
cp server/squint.toml mac/manifest.json LICENSE MODEL_LICENSE.md "$RES/"

step "icon"
ICONSET=$OUT/AppIcon.iconset
rm -rf "$ICONSET" && mkdir -p "$ICONSET"
for s in 16 32 128 256 512; do
  sips -s format png -z $s $s mac/icon.svg --out "$ICONSET/icon_${s}x${s}.png" >/dev/null
  sips -s format png -z $((s * 2)) $((s * 2)) mac/icon.svg --out "$ICONSET/icon_${s}x${s}@2x.png" >/dev/null
done
iconutil -c icns "$ICONSET" -o "$RES/AppIcon.icns"

step "app"
swiftc -O -target arm64-apple-macos14.0 -o "$APP/Contents/MacOS/Squint" mac/Squint.swift
cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>Squint</string>
  <key>CFBundleDisplayName</key><string>Squint</string>
  <key>CFBundleIdentifier</key><string>com.nickymolina.squint</string>
  <key>CFBundleExecutable</key><string>Squint</string>
  <key>CFBundleIconFile</key><string>AppIcon</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>$VERSION</string>
  <key>CFBundleVersion</key><string>$VERSION</string>
  <key>LSMinimumSystemVersion</key><string>14.0</string>
  <key>LSArchitecturePriority</key><array><string>arm64</string></array>
  <key>LSApplicationCategoryType</key><string>public.app-category.productivity</string>
  <key>NSHumanReadableCopyright</key><string>© 2026 Nicolas Molina. MIT licence; model weights CC BY-NC-SA 4.0.</string>
  <key>NSHighResolutionCapable</key><true/>
  <key>NSAppTransportSecurity</key><dict><key>NSAllowsLocalNetworking</key><true/></dict>
</dict>
</plist>
PLIST

step "sign (ad-hoc) and zip"
codesign --force --deep --sign - "$APP"
codesign --verify --deep --strict "$APP"
rm -f "$OUT/Squint-mac.zip"
ditto -c -k --keepParent "$APP" "$OUT/Squint-mac.zip"
du -sh "$APP" "$OUT/Squint-mac.zip"
