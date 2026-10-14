# Build plan, repository structure, setup and demo operations

## Repository tree (single monorepo)
```text
vico/
  README.md, LICENSE, THIRD_PARTY_NOTICES.md, .gitignore
  .env.example                  # key names only, no secrets
  apps/desktop/                # React + Vite + Tauri source
    src/components/{ModeSwitch,MicControl,Transcript,ActionPreview,Timeline,InterpreterPanel}.tsx
    src/lib/api.ts
    src-tauri/                 # Tauri manifest/commands/permissions
  services/agent/
    app/main.py                # if using Python sidecar
    app/providers/{speech,translation,planner,tts,registry}.py
    app/agent/{states,policy,schemas,orchestrator}.py
    app/tools/{files,apps,notes,documents}.py
    app/store/{settings,history}.py
    app/security/{paths,secret_store,redaction}.py
  tests/{unit,integration,e2e,fixtures,language_samples}/
  scripts/{bootstrap_windows.ps1,doctor.ps1,seed_demo.py,run_demo.ps1}
  docs/                        # this build pack
```

## Prerequisites
Windows 10/11, ordinary laptop (4GB target), working mic and headphones/speakers, Python 3.12, Node.js supported LTS, Rust toolchain and Visual Studio C++ Build Tools + WebView2 for Tauri Windows builds, Git. Stable internet and one eligible **free-tier** cloud account for core spoken demo; API keys from own accounts. Optional second laptop for ggwave. A 4GB computer may struggle with Windows + development IDE; build on any available machine but **test distribution on target low-RAM hardware**.

## Phase 0 (first ~2 hours): feasibility spikes
1. Open official API consoles and check free quotas. Transcribe three real 8-second clips: English, Yoruba, Hausa, Igbo; save outputs + latency. Mark the best-performing *non-English* language as live-demo focus.
2. Ask selected LLM for typed JSON using three tool examples; validate schema and error handling.
3. Tauri sample build on Windows; Python sidecar executable and IPC.
4. If any critical spike fails, switch to **keyboard transcription fallback**, still build local action agent.

## Day 1: real agent
- Scaffold Tauri shell, Python command bridge, storage, free-tier provider adapters.
- Implement 8 safe local tools from architecture spec, unit tests, confirmation modal, effect verification.
- Implement text→planner→preview→approved action→verify UI.
- Add English push-to-talk if free STT endpoint works.
**Exit:** a typed instruction creates/opens/finds a real local artifact; one spoken English action works; test record exists.

## Day 2: language + interpreter
- Add language selector, normalization, speech provider language hints.
- Add translator with typed 4-language paths, show both texts and direction; test with speaker-checked sample prompts.
- Add one non-English live voice-to-agent path; improve transcript review and retry.
- Add TTS English, and optional verified Nigerian voice if free and reliably deployable.
- Build provider error view and offline typed command parser.
**Exit:** local action spoken in English and priority Nigerian language; interpreter text all four languages, at least one voice pair.

## Day 3: polish, robustness and deliver
- Rehearse end-to-end 10 times. Fix crashes, race conditions, encoding, mic permission, error recovery and 429 handling.
- Test 4 GB Windows hardware or clearly mark target unverified. Build distributable installer; ensure Python sidecar actually packaged.
- Prepare test folder: `Hackathon`, `attendance_notes.txt`, `demo_music.wav` (copyright-free), sample translator phrases and recording consent.
- Add shortcuts/help, status badge, high-contrast controls and simple product landing within app.
- Record a *clearly labeled* backup video of real live flow; never replace a failing demo with deceptive fake actions.
**Exit:** clean install + success metrics + offline fallback + demo rehearsed.

## Demo script (~2m 30s)
0:00–0:20: “Vico lets Nigerians talk to their computers in familiar languages, with real actions and translation.”
0:20–0:50: typed English command, propose/approve, real folder created.
0:50–1:20: English speech opens permitted test document.
1:20–1:55: Yoruba or Hausa spoken instruction creates note; show transcript/translation/verify effect. If real voice fails, honestly switch to editable transcript and typed input.
1:55–2:20: Interpreter English → Yoruba (or tested pair); see source/target, play speech only if reliable.
2:20–2:30: toggle internet off, show limited local typed action and explain cloud tradeoff.

## Test matrix
- OS: Windows 11 at minimum; Ubuntu marked later.
- Network: normal, intermittent, 429, timeout, absent, malformed provider output.
- Speech: quiet/noisy, accented, long silence, short utterance, cancellation, missing microphone.
- Language: 5 examples each English/Yoruba/Hausa/Igbo, code-switch; score task-intent accuracy.
- Agent: 8 allowed actions, path traversal `../`, symlink escape, malformed JSON, unsupported operations, prompt injection inside document.
- Safety: approve, reject, timeout, double click, task canceled, verify wrong result.
- App: install/start/quit/uninstall, key redaction, secrets out of package, recovery from Python sidecar failure.

## Deliverables at hackathon
Windows installation artifact; GitHub README and architecture diagram; screen recording; sample files; 1-page pitch; empirical latency and language results; documented licenses; no hardcoded credentials; truthful free-tier configuration guide.
