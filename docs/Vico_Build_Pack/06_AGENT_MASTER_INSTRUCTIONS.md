# Master build instructions for an AI coding agent

You are a principal engineer implementing **Vico**, a **free-only** hybrid multilingual AI desktop assistant. Read every file in this documentation pack FIRST, and treat `00_READ_ME_FIRST.md` + `01_PRODUCT_REQUIREMENTS.md` as product truth. Build the actual app with tests, not just scaffolds or mock responses. Follow the sequence below without skipping verification.

## Outcomes
A 2–3-day hackathon demo on Windows with ordinary CPU and 4GB RAM target. Agent Mode performs real safe local actions with structured tool calls and approvals. Interpreter Mode translates between English, Yoruba, Hausa, and Igbo through verified free providers; speech-to-action works in English and at least one tested Nigerian language; other languages expose tested text and label beta voice accurately. No large local AI models as mandatory requirement; no paid subscriptions as required dependency.

## Research-first checklist
For each of the 20 candidate resources in `03_FREE_RESOURCES_AND_REPO_RESEARCH.md`, review the relevant README, latest release, license (including model weights), recent issues, integration complexity and actual implementation use; record a table and use only the strongest relevant pieces. Do not clone every repo blindly. Verify cloud model name and zero-cost tier live in the console before selecting. Reuse tested maintained libraries extensively, but avoid integrating heavyweight LangGraph/Playwright/browser-use if they expand MVP complexity without demonstrable benefit.

## Required implementation order
1. Inspect existing source repo and environment; write a concise baseline summary. If empty, scaffold monorepo.
2. Implement security controls, Pydantic tool schemas, root-bound file registry, permission/approval policy and deterministic local tools FIRST. Add tests for unauthorized commands/path escapes.
3. Build Tauri shell and local Python service with authenticated IPC; prove reliable launch/close/package.
4. Integrate freely available planner with JSON tool proposal; never execute unvalidated model prose, scripts, or arbitrary shell commands.
5. Integrate free cloud speech API with provider abstraction and quotas; benchmark English and three Nigerian speech samples with real humans before claiming support.
6. Add translation provider and human-editable transcript. Build Interpreter UI and one verified spoken language pair.
7. Add plain typed offline action parser, error handling, history, and obvious cloud/offline badges.
8. Add accessible high-quality UI, test on target low-RAM device, create deployable binary/installer.
9. Run tests and demo checklist, report remaining gaps honestly and show complete build evidence.

## Developer constraints
- Never embed API keys or token values in git or screenshots.
- Never perform destructive OS actions or unrestricted computer control.
- Never silently pay for API access; if free tier is unavailable, mark the integration blocked and use another verified free provider or graceful text-only fallback.
- No imaginary latency, model accuracy, native Nigerian TTS, or language coverage claims. Measure and report.
- Avoid broad filesystem access. Demo workspace only until explicitly widened.
- Document installation and predownload steps; no surprise first-run gigabytes.
- Use strict typed boundaries, feature flags and measured fallbacks.
- Prepare honest user-visible failure modes and accessibility controls.

## Acceptance format for coding agent
Respond with: (1) file tree; (2) implemented features vs unfinished; (3) exact dependencies with licenses and free-tier quotas; (4) tests run and outputs; (5) screenshots/demo instructions; (6) memory/latency/translation accuracy measurements; (7) security review; (8) next steps. Do not state 'everything done' until every acceptance check in PRD passes on real hardware.
