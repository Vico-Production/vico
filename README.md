# Vico

**Speak naturally. Get things done.** Vico is an agent that operates your computer for you. Press **Win + Alt + V** (Cmd + Option + V on Mac, later), then say or type what you want in English, Yorùbá, Hausa or Igbo: "open my browser and go to bbc.com", "open settings", "create a folder called Hackathon on my desktop", "open Claude and ask it to summarise my notes". Vico works out the language by itself, does the task, and answers in your language.

There is no app window and no settings page. When summoned, the edges of the screen darken and glow, liquid light drips from the top edge into a pool at the bottom, and your words rise out of it. While Vico works, light races around the screen border. When it finishes, the screen flashes warm white and everything evaporates. Vico lives in the system tray.

![Vico asking before it acts](docs/screenshots/06-approval.png)

Vico runs on Windows 10/11 and Linux (macOS later). Heavy AI work runs on Google Gemini's free tier, using one free key per user; everything that touches your computer runs locally. No paid service is required.

> **Status:** hackathon build (v0.1.0). Language accuracy, memory use on 4 GB machines, and speech quality for Yoruba, Hausa and Igbo have **not been measured yet**. See [What is verified](#what-is-verified).

## Using Vico

| | |
|---|---|
| Summon | Say **"Hey Vico"**, press **Win + Alt + V**, or click the tray icon. (If another app owns that shortcut, Vico uses Ctrl + Alt + V; the tray menu shows which.) "Hey Vico, open Notepad" works in one breath. |
| Talk | Just speak. Vico stops listening when you pause, shows what it heard, and goes on its own unless you start editing. |
| Type instead | Start typing at any moment (noisy room, quiet office). The microphone stops and your typing takes over. |
| Approve | **Enter** to allow, **Esc** to stop. Risky steps (delete, commands, uploads, sends) need **Enter held down**. |
| Leave | **Esc** at any time. A running task is cancelled. |
| Settings | Tray icon → Settings and access codes (or type "vico settings"): your Gemini code, an optional Groq backup code, "ask me before acting", "Hey Vico", and **Remove my codes and start over**. Vico starts when you sign in; untick it in the tray menu. |

## How it works

```mermaid
flowchart LR
    U[You: mic or keyboard] --> UI[Desktop UI<br/>React + Tauri]
    UI -- Tauri command --> RS[Rust shell<br/>holds launch token]
    RS -- HTTP 127.0.0.1 + token --> E[Python engine]
    E --> MIC[Push-to-talk capture<br/>in memory, max 15 s]
    E -- with your consent --> C[(Free cloud API<br/>Groq / Gemini)]
    E --> P[Policy + approval]
    P --> T[Tools: files, apps,<br/>windows, browser, shell]
    T --> V[Verify on disk / screen]
    V --> H[(SQLite history<br/>minimal, redacted)]
```

1. You speak (up to 15 s, ends on a pause) or type. Audio stays in memory and is sent to the speech provider only after you set up a code and accepted the one-line disclosure.
2. You see what Vico heard and can change it before anything happens.
3. Vico detects the language: plain English is recognised on the laptop; anything else is translated to English in one call, keeping names and quoted text exactly as you said them.
4. The planner (a free-tier LLM) proposes **one step at a time** as strict JSON. It cannot run anything itself.
5. Vico validates the step (schema, allowed folders, hard limits) and shows you the exact effect. You approve or reject.
6. The step runs locally and its result is **checked** (folder exists, file content matches, window appeared, page loaded). Vico never reports success from model text alone.
7. The result feeds the next step until the task is done. A short, redacted record goes to your local history.

### Safety model

| | Approval on (default) | Approval off |
|---|---|---|
| Looking (list folder, find files, list apps/windows) | runs | runs |
| Ordinary actions (create, save, move, open, type, click, browse) | asks | runs |
| Delete (to Recycle Bin/Trash), shell commands, uploading file text | **always asks with an extra confirmation** | **always asks** |
| Sends, posts, form submissions | **always asks** | asks unless you allow it in Settings |
| Payments, typing passwords/PINs/card numbers | **never** | **never** |

Other protections: paths are resolved and checked against the folders you allow (default: your home folder), system folders are write-protected, file and web text is passed to the AI as untrusted data, at most one step per approval, a step limit per task, and Cancel works at any point. The browser Vico controls uses its own profile, separate from your everyday browser.

## Free Gemini limits

Gemini's free tier limits requests per minute and per day (the daily limit resets at midnight Pacific time, about 8–9 am in Nigeria). Vico sends requests to Gemini 3.6 Flash first and, the moment it is rate-limited, moves the same request to Gemini 3.5 Flash-Lite, so a long task keeps going without the user noticing. If both are briefly limited, Vico shows a "key cooling" countdown and resumes the task by itself. If the daily limit is used up, it stops and says when it resets. Each user's key has its own limits.

## Better Nigerian-language speech (optional, free)

Run the free, self-hosted **Vico Speech Server** (`services/speech_server`, Linux) to add:

- **Meta Omnilingual ASR** (Apache-2.0) as the speech fallback for Yorùbá, Hausa and Igbo. Speech order: Gemini → Omnilingual → Groq Whisper, which Vico now uses for **English only**: it is weak on Yoruba and Hausa and does not support Igbo.
- **YarnGPT** Nigerian voices (Apache-2.0) so Vico answers aloud in your language.

Models download only from the publishers' official repositories at pinned commits, with checksums verified. Typed Yorùbá and Igbo without tone marks are restored automatically ("Se folda tuntun" → "Ṣe fóldà tuntun") in the same AI call that detects the language; Vico accepts the result only if nothing but the accents changed. Accuracy and speed on the free Oracle server are **not measured yet**; see the server's README for how to measure them.

## Install (users)

Download the installer for your system from the project's Releases page:

- **Windows:** `Vico_x.y.z_x64-setup.exe` (or `.msi`). WebView2 is installed automatically if missing.
- **Linux:** `.deb` (Debian/Ubuntu), `.rpm` (Fedora) or `.AppImage`. Desktop control (typing into other apps) needs an X11 session with `xdotool` and `wmctrl`; on Wayland, files, apps, browser and shell still work. The see-through overlay needs a compositing desktop (GNOME, KDE and most others).

On first launch Vico asks for one thing: a free [Gemini access code](https://aistudio.google.com/apikey) (no card required). An optional Groq code is used automatically whenever Gemini is busy. Without a key Vico still works offline for simple typed English commands: `create folder Demo`, `find notes`, `open notepad`, `show files`, `save note Ideas: text`.

Browser control uses Microsoft Edge or Google Chrome if installed. Unsigned installers will trigger a Windows SmartScreen warning until code signing is set up.

## Develop

People who only use Vico never compile anything: installers are built on GitHub's machines (push a tag like `v0.1.0`, see `.github/workflows/release.yml`) and appear on the Releases page.

To develop Vico, run the setup script for your system. On Windows it installs anything missing (Git, Node.js, uv, Rust, and Microsoft's C++ build tools) and pins Rust's MSVC toolchain for this repository. Tauri cannot be compiled with Rust's GNU toolchain or without the C++ build tools, and the script fixes both. On Linux it installs the WebKitGTK, audio and desktop-control packages.

```bash
# Windows
powershell -ExecutionPolicy Bypass -File scripts/bootstrap_windows.ps1
# Linux
bash scripts/bootstrap_linux.sh
```

Then:

```bash
npm run dev          # desktop app with hot reload; the Rust shell starts the engine from services/agent/.venv
# Browser preview of the whole experience with a scripted engine: npm --prefix apps/desktop run dev, then
# open http://localhost:1420/?demo=1 and press Ctrl + Alt + V
npm test             # Python, UI and Rust tests
npm run lint         # ruff
npm run typecheck    # mypy + tsc
npm run seed         # create ~/Documents/VicoDemo with synthetic demo files
npm run build        # package the engine and build installers for this OS
```

`scripts/doctor.ps1` checks a Windows machine and reports Vico's memory use while it runs.

### Repository layout

```text
apps/desktop/            React + Vite UI and the Tauri (Rust) shell
  src/views/             Aura (full-screen glow, liquid, narration), Prompt (words, approval, setup)
  src/lib/               session driver, API client, contracts (mirrors Python), window bus, demo engine
  src-tauri/             tray, global shortcut, two see-through windows, engine lifecycle, token proxy
services/agent/app/      Python engine
  agent/                 planner contract, policy, state machine, offline parser, prompts
  tools/                 files, apps, desktop, browser, system (shell)
  platform/              Windows / Linux / macOS adapters
  providers/             Groq, Gemini, mock; quotas, consent and fallback rules
  security/              path guards, payment/password guards, redaction, credential store
  store/                 SQLite settings and history
  audio/                 push-to-talk recorder
tests/                   unit, integration, contract fixtures, language samples
scripts/                 bootstrap, doctor, seed, build, benchmark
docs/                    build pack, implementation tasks, API contract, demo guide
```

## What is verified

| Claim | Status |
|---|---|
| Path traversal, symlink escape, reserved names, protected folders blocked | Automated tests |
| Unknown tools, extra arguments and malformed planner JSON never execute | Automated tests |
| Delete, shell and uploads always ask, even with approval off | Automated tests |
| Payment buttons, password and card fields refused | Automated tests (best-effort detection) |
| Offline typed commands work with no provider | Automated tests |
| Engine only on 127.0.0.1, token required, exits with the app | Tested on Windows 11 |
| Opening an app is verified by its window appearing | Tested on Windows 11 (Notepad) |
| UI end to end: onboarding, typed offline command, approval, verified folder | Tested in a browser against the real engine on Windows 11 |
| Packaged engine (PyInstaller folder) runs a real task | Tested on Windows 11: 22 s first start on a heavily loaded laptop, ~69 MB memory |
| Rust desktop shell compiles and launches | **Not yet on this machine** (missing MSVC Build Tools); compiled by CI |
| Speech recognition accuracy for each language | **Not measured** — run `scripts/benchmark_languages.py` with consenting speakers |
| Translation quality | **Not measured** |
| Overlay look and flow (glow, drips, approval, cooldown, finish) | Captured in a browser at 1366×768 with the scripted demo; the real see-through desktop windows are **not yet seen running** (Rust shell not compiled here) |
| Memory and startup time on a 4 GB laptop | **Not measured** |
| Linux build and desktop control | **Not tested on a Linux machine yet** (CI builds and tests it) |

Language labels in the app stay "untested" until benchmark results exist.

## Privacy

- "Hey Vico" is recognised **on this computer** (Vosk, offline). While waiting, Vico listens only for that phrase: each slice of sound is checked and dropped, never stored or sent. Windows shows its microphone-in-use icon while this is on; turn it off in Settings. After the phrase, or when you summon Vico, your request is recorded in memory (max 15 s), sent for transcription, and discarded.
- If your default microphone is muted or delivers pure silence, Vico tries your other microphones by itself.
- Uninstalling with "Delete the application data" ticked also removes your saved access codes and settings.
- Nothing goes to a cloud provider until you allow cloud processing. Each provider's terms are linked in Settings. Google's free tier may use data to improve its products.
- During a task, text from files or web pages that Vico reads is sent to the provider to plan the next step. With approval on, you see each read first.
- API keys live in Windows Credential Manager or your Linux keyring, never in Vico's files or the UI.
- History stores a short description, tool, approval and result — not audio, file contents or full transcripts — and can be cleared.

## License

Vico is licensed under the [Apache License 2.0](LICENSE) (see also [NOTICE](NOTICE)). Third-party components keep their own licenses; see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
