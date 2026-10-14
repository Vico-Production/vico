# Vico — Product Requirements Document

## 1. Summary
**Product:** Vico | **Category:** hybrid multilingual voice-first desktop assistant | **Positioning:** “Speak naturally. Get things done.” | **Form:** downloadable lightweight Windows desktop app. **Initial users:** speakers of English, Yoruba, Hausa, and Igbo who prefer speech to navigating software; students, professionals, accessibility users, and people working across languages. **Status:** hackathon concept, not a shipped product.

### Core promise
User says, in their preferred supported language, “Create a folder called Demo on my desktop”; the app converts speech → normalized intent → structured, permission-checked local tool execution → visible confirmation. Separately, two people can speak across languages and see/hear a translation.

### Problem
Popular desktop assistants inadequately serve local languages and may rely on English-only commands or cloud-hosted workflows with no local agency. Building an assistant from scratch often demands expensive infrastructure and high RAM. Vico combines flexible natural-language understanding, selective cloud assistance, and small local execution to make a captivating demonstration possible on modest hardware.

### Product pillars
1. **Understand me:** speak or type; language selector rather than magic auto-detect; transcript visible/editable.
2. **Act responsibly:** plan action with typed arguments, show proposed action, execute allowlisted tool, verify outcome.
3. **Interpret conversations:** source/target language selector, transcript, translation, optional generated audio; no claim of professional translation accuracy.
4. **Fail gracefully:** remote dependency offline -> explicit indicator, still allow local deterministic commands and keyboard entry.
5. **Respect privacy:** per-operation local file approval and obvious online transmission.

## 2. Personas and jobs
- Nigerian student: “Find my Computer Science project and open it.”
- Office worker: “Write these meeting notes and save them.”
- Bilingual speaker: translate a short Yoruba statement to English for an English speaker.
- Beginner user: use voice to launch an app and create organized folders.

## 3. MVP features (P0)
- Windows desktop UI; microphone push-to-talk, language picker (English/Yoruba/Hausa/Igbo), editable transcript, keyboard fallback, operation status.
- Agent Mode: total control of the laptop and browser. The agent can open apps and files, create, move and save files, open the browser, navigate, click, type and read page content, and run multi-step tasks. Every step shows its exact effect and waits for approval while the approval switch is on (default). Hard limits stay on regardless: no payments, no typing passwords or card details, no deletion without a separate explicit confirmation.
- Interpreter Mode: translate typed texts among four languages using a validated provider; speak one English↔Nigerian-language example; show original + translated text and per-language confidence caveat; English TTS + browser/device speech only if supported; never fake audio support.
- Cloud adapters: `SpeechProvider`, `TranslationProvider`, `ReasoningProvider`, `TTSProvider`, with health/status and explicit cost-free configuration. Secrets stored server-side or OS secure storage, not frontend bundles.
- Agent engine: constrained JSON action plan, strict schema, no arbitrary code generation for execution, preflight, consent, act, verify, log.
- Small deterministic offline commands (create folder in approved demo workspace, search demo workspace, open known app), *using typed text*. Offline English voice is a stretch.
- Demo seed folder with nonprivate test documents and a rollbackable set of demo actions.

## 4. P1 stretch features
- Native Nigerian-language TTS only after verifying quality, licensing, and deployment cost.
- Microphone/translation conversation alternating turns; no full-duplex simultaneous interpretation.
- ggwave acoustic short-message text transfer between two machines (separate from core translation).
- Customizable quick-action macros and local simple document summarization if remote quota available.
- Browser control is moved into P0 under total control (see Agent Mode above). Passwords and payments remain blocked.

## 5. Explicit non-goals
Perfect multilingual ASR, real-time zero-delay interpretation, full offline complex AI on 4 GB RAM, unattended automation, full OS administrative privileges, processing private files without consent, unsupported phone versions.

## 6. User experiences
### Onboarding
Startup → privacy explanation → choose mode/language → mic permission → connect a free API provider or use typed/offline demo → set workspace `~/Documents/VicoDemo` → run demo self-check.
### Agent Mode
Push-to-talk → locally capture short WAV → choose cloud provider *only with disclosure* → view transcript + edit option → convert/translate to canonical English command → get strict tool proposal `{tool, arguments, summary, confidence}` → validate against permission registry → user approval for external/file changes → run tool → check system outcome → respond in user's language where feasible → store minimal local audit.
### Interpreter Mode
Choose source/target → record 3–10s clip → transcribe → editable correction → translate → render side-by-side + copy + TTS play if supported → swap direction → next speaker; if translation fails offer text-only fallback and clear warning.
### Offline
Detect connection loss in <5 seconds → show 'Cloud unavailable; limited local commands only' → allow typed allowlisted command grammar and file operations, do not pretend that Nigerian-language speech processing works offline.

## 7. Functional requirements and acceptance
| ID | Requirement | Pass |
|---|---|---|
| F01 | Tauri desktop opens offline | launch without localhost web dependency |
| F02 | push-to-talk and transcription | English 5 clips transcribe visibly with error states |
| F03 | four languages typed | send 5 samples per language, label output honestly |
| F04 | Nigerian speech-to-action | 5 live attempts for chosen priority language, record success count |
| F05 | executable tools | 8 tools individually validated, no mock results |
| F06 | typed action schema | invalid/missing params rejected; no raw shell execution |
| F07 | consent control | destructive, external, or file-content export requires explicit approval |
| F08 | translator | 4 language pairs in text and at least one spoken pair |
| F09 | provider outage | no crash, text/local fallback |
| F10 | history | records timestamp, user-facing action, outcome; clear-history button |
| F11 | 4GB target | measured app memory and responsiveness on physical 4GB Windows hardware or clearly unverified |
| F12 | no paid dependency | initial setup accepts free API plan, disabled optional steps |

## 8. Quality targets (not promises)
- Happy path English action: target 3–8 seconds end-to-end on stable internet; instrument actual p50/p95.
- Transcription: assess separately by language with a small locally consented sample set; report actual correct-intent rate and word error rate where annotated.
- Agent 0 unauthorized tool executions across adversarial test set.
- Reliable staged demo: at least 8/10 successful repeats for preselected tasks on demo machine.
- Low-memory: UI + sidecar incremental memory instrumentation, target acceptable on 4GB OS device; benchmark unknown until tested.

## 9. Product/UI design
Professional flat brand, no gradients/3D required. Home segmented `Agent` and `Interpreter`. Large orb mic control with explicit listening/processing states. Language chips, editable transcript card, proposed action preview, status timeline (Heard → Understood → Proposed → Approved → Done), visible local/cloud badge. Translation layout two-pane with source/target and speaker turn. Keyboard shortcuts, screen-reader labels, errors actionable, keyboard-only access. Avoid implying Vico itself can hear continuously.

## 10. Future milestones
More languages (including Nigerian Pidgin), model-agnostic provider marketplace, local-first encrypted profile, signed first-party plugins, non-Windows adapters, multilingual code-switch recognition, offline model packs for machines with sufficient resources, expanded document/browser integrations with least privilege.

## 11. Demo story
Judge speaks English: create `VicoDemo/Hackathon` folder. Judge speaks Yoruba: ask to find project notes. Vico displays transcript, understandable translated intent, checks tool, finds test note, opens it. Interpreter: English ↔ Yoruba short prepared *but live* phrases; optionally Hausa/Igbo text and voice only if validated. Cut internet; show typed local folder operations still work. Do not use pre-recorded actions disguised as live AI.
