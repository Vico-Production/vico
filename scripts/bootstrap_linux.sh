#!/usr/bin/env bash
# Install Vico's development dependencies on Debian/Ubuntu.
# Needs: git, curl, Node.js LTS, Rust (rustup) and uv (https://docs.astral.sh/uv/).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

echo "Installing system libraries for Tauri, audio and desktop control (sudo)..."
sudo apt-get update
sudo apt-get install -y libwebkit2gtk-4.1-dev build-essential curl wget file libxdo-dev libssl-dev \
  libayatana-appindicator3-dev librsvg2-dev libportaudio2 xdotool wmctrl

for tool in node npm cargo uv; do
  command -v "$tool" >/dev/null || { echo "$tool is not installed. See README.md > Prerequisites."; exit 1; }
done

(cd "$ROOT/services/agent" && uv sync)
(cd "$ROOT/apps/desktop" && npm ci)
uv run --project "$ROOT/services/agent" python "$ROOT/scripts/seed_demo.py"

echo
echo "Browser control uses Google Chrome if installed. Without Chrome, download Chromium once with:"
echo "  (cd services/agent && uv run playwright install chromium)"
echo "Done. Start Vico in development with:  npm run dev"
