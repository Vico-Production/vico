# Third-party notices

Vico uses the following open-source components. Each keeps its own license; full texts ship with the packages (`node_modules/*/LICENSE`, Python package metadata, Cargo registry sources). Versions are pinned in `services/agent/uv.lock`, `apps/desktop/package-lock.json` and `apps/desktop/src-tauri/Cargo.lock`.

Regenerate a complete inventory before each release:

```bash
cd services/agent && uv run pip-licenses --format=markdown      # needs: uv add --dev pip-licenses
cd apps/desktop && npx license-checker --summary
cd apps/desktop/src-tauri && cargo install cargo-about && cargo about generate about.hbs
```

## Direct dependencies

| Component | Use | License |
|---|---|---|
| Tauri 2 (+ tauri-build) | desktop shell | MIT OR Apache-2.0 |
| reqwest, serde, serde_json, getrandom | Rust shell HTTP, JSON, randomness | MIT OR Apache-2.0 |
| React, React DOM | UI | MIT |
| Vite, @vitejs/plugin-react | bundler | MIT |
| TypeScript | language | Apache-2.0 |
| Vitest, Testing Library, jsdom | UI tests (dev only) | MIT |
| FastAPI, Starlette | engine HTTP API | MIT / BSD-3-Clause |
| Uvicorn | engine server | BSD-3-Clause |
| Pydantic | strict validation | MIT |
| HTTPX | provider HTTP client | BSD-3-Clause |
| keyring | OS credential store | MIT |
| Send2Trash | recoverable deletion | BSD-3-Clause |
| python-sounddevice (bundles PortAudio) | microphone capture | MIT (PortAudio: MIT-style) |
| Vosk (vosk-api, bundles libvosk/Kaldi) | on-device "Hey Vico" wake phrase | Apache-2.0 |
| vosk-model-small-en-us-0.15 (model) | wake phrase recognition; downloaded once from alphacephei.com, SHA-256 checked | Apache-2.0 |
| tauri-plugin-autostart | start Vico at sign-in | MIT OR Apache-2.0 |
| Gemini 3.8 Flash / Flash-Lite TTS (cloud API, user's own key, free tier) | spoken replies in English, Hausa, Igbo | Google API terms |
| Windows SAPI / espeak-ng (system voices, not bundled) | offline English replies | part of Windows / GPL-3.0 (system package) |
| Windows Magnification API (part of Windows) | the Lens look | part of Windows |
| ddgs (deedy5/ddgs) | keyless web search | MIT |
| lxml | reading web pages | BSD-3-Clause |
| primp | HTTP client used by ddgs | MIT |
| Pillow | screenshots and cropping | MIT-CMU (HPND) |
| NumPy | cleaning recordings | BSD-3-Clause |
| pycaw | Windows volume control | MIT |
| Kokoro-82M (downloaded on first use, from the kokoro-onnx project's release) | offline English voice | Apache-2.0 |
| ONNX Runtime | running Kokoro | MIT |
| misaki (pronunciation dictionaries only; no espeak-ng) | Kokoro pronunciation | Apache-2.0 |
| Piper (only if the user installs it; not shipped) | optional offline voice | GPL-3.0 (separate program) |
| NaijaVox-2.0 (optional, on the user's speech server) | Nigerian speech recognition | Apache-2.0 |
| Mistral, OpenRouter, TinyFish (cloud APIs, user's own optional keys) | fallbacks and web search | each provider's terms |
| Playwright for Python (bundles a Node.js driver) | browser control | Apache-2.0 |
| pywinauto (+ comtypes, pywin32) | Windows desktop control | BSD-3-Clause / MIT / PSF |
| pytest, ruff, mypy, PyInstaller | development and packaging | MIT / MIT / MIT / GPL-2.0 with bootloader exception |

PyInstaller's bootloader exception allows distributing the packaged engine under any license.

## Optional Vico Speech Server (self-hosted, not bundled with the app)

Installed only on a server the user runs (`services/speech_server`). All free; nothing is paid.

| Component | Use | License | Where it runs |
|---|---|---|---|
| Meta Omnilingual ASR, `omniASR_CTC_300M` model and `omnilingual-asr` code | speech recognition for Yoruba, Hausa, Igbo, English | Apache-2.0 | user's Linux server |
| fairseq2 | runtime for Omnilingual ASR | MIT | user's Linux server |
| YarnGPT2b (model) / yarngpt (code) | Nigerian voices for spoken answers | Apache-2.0 / MIT | user's Linux server |
| WavTokenizer (large, speech 75 token) | audio decoder for YarnGPT | MIT | user's Linux server |
| OuteTTS 0.2.3 (code) | WavTokenizer decoder code used by YarnGPT | Apache-2.0 | user's Linux server |
| uroman | romanisation used by YarnGPT | MIT-style | user's Linux server |
| PyTorch, Transformers, Hugging Face Hub | model runtime and downloads | BSD-3-Clause / Apache-2.0 / Apache-2.0 | user's Linux server |
| Caddy (recommended) | HTTPS in front of the server | Apache-2.0 | user's Linux server |

Required acknowledgement: "This project uses the universal romanizer software 'uroman' written by Ulf Hermjakob, USC Information Sciences Institute (2015-2020)".

Not used: **N-ATLaS** (custom license, free only up to 1,000 active users a month, commercial license above that).

## Cloud services (optional, not bundled)

- **GroqCloud API** — used under the user's own free account and Groq's terms.
- **Google Gemini API** — used under the user's own account and Google's Gemini API terms. Free-tier data may be used by Google to improve its products.

No model weights are bundled. CC-BY-NC models (for example NLLB-200) are **not** used.
