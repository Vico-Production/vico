#!/usr/bin/env bash
# Install the Vico Speech Server on a Linux machine you control.
#
# Tested target: Ubuntu 22.04/24.04. Works on x86-64 out of the box. On ARM (e.g. Oracle
# Cloud Always Free Ampere A1) fairseq2 has no pre-built package, so the script builds it
# from source; that step can take a long time and is the part most likely to fail.
#
#   sudo bash setup_linux.sh [--voice]
#
# Afterwards: put HTTPS in front (see README.md), then in Vico: tray > Settings > Speech
# server, with the URL and the token printed at the end.
set -euo pipefail

VOICE=0
[[ "${1:-}" == "--voice" ]] && VOICE=1
PREFIX=/opt/vico-speech
SRC_DIR="$(cd "$(dirname "$0")/.." && pwd)"
ARCH="$(uname -m)"

echo "== system packages"
apt-get update
apt-get install -y python3 python3-venv python3-dev build-essential cmake ninja-build git libsndfile1 libsndfile1-dev curl

id -u vico-speech >/dev/null 2>&1 || useradd --system --create-home --home-dir "$PREFIX" vico-speech
mkdir -p "$PREFIX/models"
cp -r "$SRC_DIR/vico_speech" "$PREFIX/"
python3 -m venv "$PREFIX/venv"
PIP="$PREFIX/venv/bin/pip"
"$PIP" install --upgrade pip wheel
"$PIP" install "fastapi>=0.115" "uvicorn>=0.32" "numpy>=1.26" "huggingface_hub>=0.26"

echo "== PyTorch (CPU)"
"$PIP" install torch torchaudio --index-url https://download.pytorch.org/whl/cpu

echo "== Meta Omnilingual ASR"
if [[ "$ARCH" == "x86_64" ]]; then
  "$PIP" install omnilingual-asr
else
  echo "fairseq2 has no pre-built package for $ARCH; building from source (this can take a long time)."
  git clone --depth 1 https://github.com/facebookresearch/fairseq2.git "$PREFIX/fairseq2-src"
  # Follow the official 'Install From Source' steps: build the native fairseq2n library, then fairseq2.
  "$PIP" install -r "$PREFIX/fairseq2-src/native/python/requirements-build.txt" || true
  (cd "$PREFIX/fairseq2-src/native" && cmake -GNinja -B build -DCMAKE_BUILD_TYPE=Release && cmake --build build) \
    || { echo "Building fairseq2n failed. See README.md > 'If the ARM build fails'."; exit 1; }
  "$PIP" install -e "$PREFIX/fairseq2-src/native/python" -e "$PREFIX/fairseq2-src"
  "$PIP" install --no-deps omnilingual-asr
fi

ENABLE=asr
if [[ $VOICE -eq 1 ]]; then
  echo "== YarnGPT voices"
  "$PIP" install transformers "outetts==0.2.3" uroman inflect
  git clone https://github.com/saheedniyi02/yarngpt.git "$PREFIX/yarngpt"
  git -C "$PREFIX/yarngpt" checkout 8bb0eb27d307f4b5903149e24ecc1bd3caa4af2d
  ENABLE=asr,voice
fi

TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
cat > /etc/vico-speech.env <<EOF
VICO_SPEECH_TOKEN=$TOKEN
VICO_SPEECH_MODELS=$PREFIX/models
VICO_SPEECH_ENABLE=$ENABLE
VICO_YARNGPT_CODE=$PREFIX/yarngpt
VICO_SPEECH_HOST=127.0.0.1
VICO_SPEECH_PORT=8088
EOF
chmod 600 /etc/vico-speech.env
chown -R vico-speech: "$PREFIX"

echo "== downloading and verifying models (official repositories, pinned commits, SHA-256)"
sudo -u vico-speech env $(cat /etc/vico-speech.env | xargs) PYTHONPATH="$PREFIX" "$PREFIX/venv/bin/python" - <<'PY'
import os
from pathlib import Path
from vico_speech.artifacts import ASR_ARTIFACTS, VOICE_ARTIFACTS, fetch
models = Path(os.environ["VICO_SPEECH_MODELS"])
wanted = list(ASR_ARTIFACTS) + (list(VOICE_ARTIFACTS) if "voice" in os.environ["VICO_SPEECH_ENABLE"] else [])
for artifact in wanted:
    print("verified", fetch(artifact, models))
PY

cp "$SRC_DIR/deploy/vico-speech.service" /etc/systemd/system/vico-speech.service
systemctl daemon-reload
systemctl enable --now vico-speech

echo
echo "Vico Speech Server is running on 127.0.0.1:8088 (enabled: $ENABLE)."
echo "Token (paste into Vico > Settings > Speech server): $TOKEN"
echo "Next: put HTTPS in front of it (README.md > HTTPS), then measure: "
echo "  sudo -u vico-speech env \$(cat /etc/vico-speech.env | xargs) PYTHONPATH=$PREFIX $PREFIX/venv/bin/python -m vico_speech.measure --wav sample.wav"
