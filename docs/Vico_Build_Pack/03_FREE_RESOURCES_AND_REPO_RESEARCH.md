# Free resources, reusable infrastructure and verification checklist
Checked against publicly available project docs as of 2026-10-14. These are **candidates, not installed or performance-tested dependencies**. Check README/license/model cards/availability on implementation day. Free-tier quota is not unlimited free hosting; accounts and regional eligibility may matter. Maintain `THIRD_PARTY_NOTICES.md` in the codebase.

| Priority | Resource | Link | Use | Free/license caveat | Integration decision |
|---|---|---|---|---|---|
| P0 | Tauri | https://github.com/tauri-apps/tauri | lightweight native desktop shell | MIT/Apache-2.0 code, platform prerequisites | adopt if Windows build passes |
| P0 | React | https://github.com/facebook/react | UI | MIT | adopt |
| P0 | Vite | https://github.com/vitejs/vite | bundler | MIT | adopt |
| P0 | FastAPI | https://github.com/fastapi/fastapi | typed local Python service if needed | MIT | optional; Tauri IPC preferable |
| P0 | Pydantic | https://github.com/pydantic/pydantic | validate LLM plans | MIT | adopt |
| P0 | pywinauto | https://github.com/pywinauto/pywinauto | reliable Windows UI automation | BSD-3-Clause recent versions | adopt for targeted app operations only |
| P0 | PyAutoGUI | https://github.com/asweigart/pyautogui | optional keyboard/mouse fallback | BSD-3-Clause | avoid for core, fragile positions |
| P0 | Google Gemini API | https://ai.google.dev/gemini-api/docs/pricing | cloud translation/planning, potential audio | selected models have **limited free tier**; not every model/modal task | use ONLY model showing free tier for user's account, inspect quota beforehand |
| P0 | GroqCloud | https://console.groq.com/docs/rate-limits | hosted Whisper speech and/or LLM | free account has quotas, model/language quality unknown | primary STT candidate, test English/Yoruba/Hausa/Igbo |
| P0 | Groq SDK | https://github.com/groq/groq-python | API integration | permissive SDK; backend quotas | candidate |
| P0 | Gemini Python SDK | https://github.com/googleapis/python-genai | API integration | SDK open source; models quota-limited | candidate |
| P0 | SQLite | https://www.sqlite.org/ | local settings/action history | public domain SQLite | adopt |
| P0 | pytest | https://github.com/pytest-dev/pytest | unit/integration testing | MIT | adopt |
| P0 | Playwright | https://github.com/microsoft/playwright | UI end-to-end tests, future scoped web automation | Apache-2.0 | test automation; not core agent browser takeover |
| P1 | LangGraph | https://github.com/langchain-ai/langgraph | future durable state-machine tool orchestration | MIT, added complexity | research, use plain state machine for MVP |
| P1 | faster-whisper | https://github.com/SYSTRAN/faster-whisper | optional local STT, model quantization | MIT implementation; check weights | offline English fallback after CPU benchmark |
| P1 | whisper.cpp | https://github.com/ggml-org/whisper.cpp | alternative compact offline STT | MIT implementation; model weights vary | optional low-RAM benchmark |
| P1 | NaijaVox-2.0 | https://huggingface.co/Axiveri/NaijaVox-2.0 | Nigeria-specific ASR benchmark | model card says Apache-2.0, **large Whisper-v3 based**, unsuitable to assume 4GB local | evaluate accuracy; run only if free compute exists or later, not MVP dependency |
| P1 | NLLB-200 distilled 600M | https://huggingface.co/facebook/nllb-200-distilled-600M | multilingual text translation alternative | CC-BY-NC-4.0; research/noncommercial, sizable RAM requirement | research fallback; avoid core 4GB deployment |
| P1 | ggwave | https://github.com/ggerganov/ggwave | acoustic packet transmission | open-source; small payloads/slow | stretch demo only |
| P1 | Piper | https://github.com/OHF-Voice/piper1-gpl | offline TTS voice engine | GPL-3.0 implementation; voices individually licensed | optional; verify model voice language and licensing |
| P1 | Argos Translate | https://github.com/argosopentech/argos-translate | offline translation experimentation | check package licenses and actual yo/ha/ig packs | not assumed to cover Nigerian languages |
| P1 | AfriLingua | https://github.com/PrincessEC/AfriLingua | potential reference for African languages | unverified code health and weights; check actual LICENSE | inspect code, **do not assume plug-and-play** |
| P1 | naija-asr-backend | https://github.com/Prosper700/naija-asr-backend | reference pipeline | inspect license, model source, benchmarks | optional only |

## Provider selection and zero-cost policy
1. Create free-tier accounts only if they can be opened without payment/billing; verify available models by querying `/models` or console. **Do not hardcode an unverified model name** (previous speculative Gemini names are not a dependency).
2. Configure `PRIMARY_STT`, `FALLBACK_STT`, `PLANNER_MODEL`, `TRANSLATION_MODEL` in `.env` (no secrets in logs). Free-plan quotas vary by account and date.
3. Abort or fall back to typed mode if no confirmed free option. No automatic transition to pay-as-you-go.
4. Track requests/min, day, audio seconds, and HTTP 429. Respect `Retry-After`; add low configurable token/audio budget.
5. For pronunciation and non-English speech synthesis, *verify actual output*. If unsupported, show translated text and optionally device/system TTS with clear limitation.

## Repository due-diligence checklist (must complete before dependency accepted)
For each project: (a) exact repo and maintained branch (b) license and model weights/voice package license (c) last release, issues, OS support (d) installation instructions and available wheels (e) memory/disk requirement on Windows 4GB device (f) offline vs online claims (g) simple sample executed successfully (h) language pair test results (i) security/privacy exposure (j) binary provenance/SBOM. Record results in `resources-evaluation.csv` in repo. Fork/adapt only with attribution and compatible licensing.

## Language accuracy strategy
- English: establish reliable baseline first.
- Yoruba/Hausa/Igbo: assess sample words/commands from actual willing speakers. Use manual language hint and editable transcript; preserve diacritics in UI.
- Avoid translating filenames/proper nouns; extract literal quoted targets (`Hackathon`) before normalization.
- Keep language-specific examples, prompts, correction dictionaries for app names and terms, explicit uncertainty states.
- Never promise 'any language' support. Public-facing language labels distinguish **typed tested**, **speech beta**, **speech unsupported**.

## Research and verification references
- Gemini pricing: https://ai.google.dev/gemini-api/docs/pricing
- Groq free rate limits: https://console.groq.com/docs/rate-limits
- NaijaVox card & reported WER: https://huggingface.co/Axiveri/NaijaVox-2.0
- NLLB license/out-of-scope: https://huggingface.co/facebook/nllb-200-distilled-600M
- Tauri platform build: https://v2.tauri.app/start/prerequisites/
