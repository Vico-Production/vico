# Vico decision log, limitations and risk register

## Confirmed decisions from planning
- Working product name: **Vico** (brand/trademark availability not independently certified).
- Two modes: Interpreter and Agent.
- English, Yoruba, Hausa, Igbo targeted; additional Nigerian languages after MVP.
- Hybrid architecture; cloud heavy compute, local laptop actions.
- No 8–16 GB minimum requirement. **4GB is target, not proven guaranteed.**
- Free-only resources. Trial credits that require billing are NOT an acceptable mandatory dependency.
- Offline fallback remains limited; entire multilingual spoken agent not promised offline.
- Hackathon demo in 2–3 days, quality prioritized over breadth.
- **2026-10-14: Platforms** — Windows first, Linux second from the same codebase behind a platform adapter, macOS later. See `docs/PLATFORMS.md`.
- **2026-10-14: Implementation choices** — browser control drives the installed Edge/Chrome through Playwright with a separate Vico profile; audio is captured by the engine (PortAudio) and kept in memory only; speech output uses the operating system's voices; tools take checked paths instead of opaque file IDs; deletion goes to the Recycle Bin/Trash.
- **2026-10-14: Agent Mode has total control of the laptop and browser**, with an approval switch on by default. This supersedes the earlier 8-tool-only and no-browser-takeover limits. Hard limits stay: no payments, no typing passwords or card details, no deletion without separate confirmation. Risk: a web page or document could try to steer the agent (prompt injection), so the approval step is the main defence and should be tested with adversarial pages.

## Current risks (likelihood/impact/action)
| Risk | L | I | Mitigation |
|---|---|---|---|
| Nigerian speech recognition inaccurate | High | High | early real-speech spikes, select strongest language, editable transcript, no hidden demo recording |
| Free API quotas or availability change | Medium | High | account checks on day 0, adapter fallback, quota meter, offline typed demo |
| Tauri sidecar packaging Windows | Medium | High | spike build on day 0, test clean install; simplify Python bundling if necessary |
| Google/Groq data privacy | Medium | High | clear consent, synthetic demo data, no automatic document upload |
| 4GB RAM performance varies | Medium | Medium | no local large models, profiling, test real target machine |
| Nigerian TTS unavailable/free voice poor | High | Medium | translated text as baseline, English TTS; no false voice claims |
| Repo license incompatible | Medium | High | inspect license and weights before use, notices, avoid incompatible copy-paste |
| Arbitrary agent actions harm laptop | Medium | High | allowlisted tools, preview, consent, safe workspace, bounded autonomy |
| Real-time acoustic transfer latency | High | Low | remove from critical demo path |
| Product name Vico already trademarked | Unknown | Medium | formal name/domain/trademark search before launch |

## Day-0 research questions that do NOT block writing core app
- Which currently available free-tier cloud model accepts audio in English and targeted Nigerian languages at acceptable accuracy?
- Does the hackathon permit noncommercial CC-BY-NC model weights if used in a research demo?
- Can actual target 4GB Windows machine launch packaged Tauri/Python app smoothly?
- Are Yoruba, Hausa, and Igbo TTS voices both legally usable and reliably intelligible for the task?

## Validation truth statements
This documentation is a complete **implementation blueprint**, not proof that third-party repositories have been installed, that language claims work on physical devices, or that costs are guaranteed forever. Budget for internet usage. Internet outages remove cloud translation/reasoning. Any model claiming 100% accurate Nigerian dialect recognition is not credible without benchmark evidence.
