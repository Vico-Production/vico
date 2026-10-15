# Vico Speech Server (optional, free, self-hosted)

A small HTTP service you run on a Linux machine you control. It makes Vico better at Nigerian languages, using only free, openly licensed models:

| Job | Model | License | Size | Used for |
|---|---|---|---|---|
| Listen | Meta Omnilingual ASR `omniASR_CTC_300M` | Apache-2.0 | 1.3 GB | Yoruba, Hausa, Igbo (and English) speech when Gemini is resting or unavailable |
| Speak | YarnGPT2b + WavTokenizer | Apache-2.0 + MIT | 0.73 GB + 1.75 GB | Answers read aloud in Nigerian English, Yoruba, Igbo and Hausa voices |

Vico itself still runs on Windows or any Linux distro; only this server needs Linux. Vico calls it over HTTPS with a token. It is used only after you accepted Vico's cloud disclosure, and audio is processed in memory and never written to disk on either side.

Speech order in Vico: **Gemini → this server (Omnilingual) → Groq Whisper (English only)**. Switching is automatic and instant.

## Cost

Free: open models, no API fees. You need a machine. The suggested one is an [Oracle Cloud Always Free](https://www.oracle.com/cloud/free/) Ampere A1 instance (ARM CPU, no GPU; check Oracle's page for the current free allowance). Oracle asks for a card to verify sign-up but does not charge within the free limits.

## Install

```bash
git clone <your Vico repo> && cd vico/services/speech_server
sudo bash deploy/setup_linux.sh          # listening only
sudo bash deploy/setup_linux.sh --voice  # listening + voices
```

The script:

1. Installs system packages, Python, CPU PyTorch.
2. Installs Meta Omnilingual ASR. **On ARM this means building fairseq2 from source**: fairseq2 publishes packages only for Linux x86-64 and Apple-silicon Macs. The build commands in the script follow fairseq2's "Install From Source" guide, but they have **not been run on an Oracle ARM machine yet**. If they fail, follow the official guide at https://github.com/facebookresearch/fairseq2 (Installing from Source) and rerun.
3. Downloads models **only from the publishers' official Hugging Face repositories, at pinned commits**, and checks every file's SHA-256 (or git SHA-1 for small files) against `vico_speech/artifacts.py`. A file that doesn't match is deleted and the server refuses to start.
4. Creates a token, writes `/etc/vico-speech.env`, and starts a `systemd` service on `127.0.0.1:8088`.

## HTTPS

The server listens only on localhost. Put free automatic HTTPS in front with [Caddy](https://caddyserver.com) (see `deploy/Caddyfile`) and a free hostname (for example DuckDNS). Open port 443 in the Oracle security list. Vico refuses plain `http://` addresses except `127.0.0.1`/`localhost`.

## Connect Vico

Tray icon → Settings → **Your speech server**: paste the `https://` address and the token, switch on **Answer me aloud** if you installed voices, then **test connection**.

## Measure (please do this before trusting it)

```bash
sudo -u vico-speech env $(cat /etc/vico-speech.env | xargs) PYTHONPATH=/opt/vico-speech \
  /opt/vico-speech/venv/bin/python -m vico_speech.measure --wav sample.wav --runs 5 --voice
```

It prints load time, transcription time and real-time factor (RTF: processing time ÷ audio length; below 1 is faster than real time), and the voice's time per language. Then measure accuracy from a Vico checkout:

```bash
cd services/agent
VICO_SPEECH_SERVER_URL=https://your-host VICO_SPEECH_SERVER_TOKEN=... \
  uv run python ../../scripts/benchmark_languages.py --stt omnilingual --planner gemini
```

### Measured so far

| | Value |
|---|---|
| Omnilingual latency on Oracle Ampere A1 | **not measured** (no server available while building this) |
| YarnGPT latency on Oracle Ampere A1 | **not measured** |
| Word / character error rate, Yoruba / Hausa / Igbo | **not measured** (no consented recordings yet) |

Meta reports a real-time factor of 0.001 for `omniASR_CTC_300M` on an NVIDIA A100 GPU. That figure is for a GPU and says nothing about an ARM CPU. YarnGPT generates audio token by token with a 360M-parameter language model; on a CPU, expect it to be the slow part, and measure before switching voices on.

## If the ARM build fails or it is too slow

Next free options, in order:

1. **An x86-64 Linux machine you already own** (an old laptop or PC, or WSL on a Windows PC): fairseq2 installs from pip, no build needed. Expose it with a free Cloudflare Tunnel instead of opening ports.
2. **A free Hugging Face Space (CPU)**: x86-64, so `pip install omnilingual-asr` works; make the Space private and keep the token check. Free Spaces sleep when unused, so the first request after a pause is slow; check Hugging Face's current free-tier limits.
3. **Listening only**: run without `--voice`. Vico shows answers as text, which costs nothing.

Gemini remains the first choice for speech either way; this server is the free fallback for Nigerian languages.

## What was considered and not used

- **N-ATLaS** (Awarri / Federal Ministry of Communications, Nigeria): free only up to **1,000 active users a month**, with a commercial license above that, share-alike terms, and gated download. It is not a dependency. Its ASR models were not benchmarked: downloading them requires accepting the terms with your own Hugging Face account.
- **Spitch** and other paid APIs: excluded (paid).
