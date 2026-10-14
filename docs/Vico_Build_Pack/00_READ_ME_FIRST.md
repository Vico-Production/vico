# VICO — Master Build Pack
Version 1.0 | 14 October 2026 | Hackathon target: 48–72 hours

## Single source of truth
Vico is a **lightweight multilingual desktop voice assistant** combining (A) Interpreter Mode for conversation translation and (B) Agent Mode for executing *approved* computer tasks. Languages prioritized: English, Yoruba, Hausa, Igbo; optional Nigerian Pidgin. The differentiator is an actual laptop action triggered by a Nigerian-language voice request, not a generic chatbot.

## Non-negotiables
1. Build a genuine **desktop** app, not a hosted web page. Windows first; future Linux/macOS adapters.
2. Target 4 GB RAM, ordinary CPU, no GPU; validate rather than guaranteeing performance. **Avoid locally hosting large speech/LLM models**.
3. Hybrid by default: speech/translations/reasoning on cloud *free quotas* when available; file and application actions locally. No paid service or credit card prerequisite in the core acceptance path.
4. **Free-to-use only**: open-source libraries with compatible licenses; optional free-tier APIs with explicit quotas, no hidden paid fallback. Internet/data and hardware aren't free. Preserve notices. Some translation model weights are noncommercial: no commercial production claims.
5. All external requests are opt-in and clearly marked; never upload full documents by default.
6. Critical actions require confirmation. No arbitrary model-generated shell commands, unrestricted browser takeover, payments, credential access, or silent deletion.
7. Scope success: English and *at least one* Nigerian-language speech-to-action path; all four via text, with spoken capability marked experimental until independently tested.
8. Treat repository and model suitability as candidates, **not prevalidated integrations**. Run the repository evaluation checklist before adoption.

## Package map
- `01_PRODUCT_REQUIREMENTS.md` — detailed PRD, UX, scope, metrics, acceptance criteria.
- `02_ARCHITECTURE_AGENT_FLOWS.md` — architecture, states, agent routing, tool contracts, permissions.
- `03_FREE_RESOURCES_AND_REPO_RESEARCH.md` — verified references, alternatives, license/cost caveats, evaluation tasks.
- `04_IMPLEMENTATION_PLAN.md` — architecture tree, day-by-day implementation, tests, setup, demo.
- `05_SECURITY_PRIVACY_QA.md` — threat model, privacy, security, QA matrix, failure modes.
- `06_AGENT_MASTER_INSTRUCTIONS.md` — end-to-end instructions for a coding agent.
- `07_DECISIONS_AND_RISKS.md` — decision log, unresolved issues, truth claims.

## Definition of done for hackathon
From a fresh launch on a low-end Windows laptop: grant mic permission → choose language → speak or type → inspect recognized words → approve proposed action if needed → observe a **real change** on the computer → view result in activity history. In interpreter mode: input utterance → transcript → translated text → speech if supported. Demo remains usable when a provider fails (text input and fallback commands).

## Explicit exclusions in 72h
Unlimited open-ended GUI control; guaranteed accurate voice translation for all three Nigerian languages; always-on microphone/wake-word; full offline multilingual AI; anonymous zero-latency peer-to-peer acoustic streaming; autonomous sending of emails/messages; filesystem-wide reads by default; background execution without consent.
