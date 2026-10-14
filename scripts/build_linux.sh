#!/usr/bin/env bash
# Build the Linux packages (.deb, .rpm, .AppImage) with the engine bundled.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

(cd "$ROOT/services/agent" && uv sync && uv run python ../../scripts/build_sidecar.py)
(cd "$ROOT/apps/desktop" && npm ci && npx tauri build --config src-tauri/tauri.release.conf.json)

echo "Packages:"
find "$ROOT/apps/desktop/src-tauri/target/release/bundle" -type f \( -name '*.deb' -o -name '*.rpm' -o -name '*.AppImage' \) -exec ls -lh {} \;
