# Task 10 — Integration, QA, Windows packaging, and demo release

## Goal
Turn the merged workstreams into a reproducible, installable, measured hackathon release.

## Scope
- Resolve integration issues across contracts, sidecar lifecycle, providers, tools, UI, speech, and interpreter flows.
- Package the Python service as a Tauri external binary so end users do not install Python separately.
- Produce a Windows installer and test install, first launch, quit, relaunch, and uninstall on a clean Windows 10/11 environment.
- Add demo-workspace seeding with synthetic files and rollbackable actions.
- Run unit, integration, frontend, end-to-end, security, outage, and adversarial tests.
- Exercise path traversal, symlink escape, malicious document instructions, malformed planner output, double approval, cancellation, and provider outages.
- Measure startup time, memory, action latency, provider latency, and language results; never invent unavailable measurements.
- Complete README, setup, privacy disclosure, architecture diagram, dependency/license notices, and the two-and-a-half-minute demo guide.

## Deliverables
- Reproducible build scripts and versioned installer artifact.
- Seed and doctor scripts.
- Test and measurement report with environment details.
- Release checklist showing pass, fail, or unverified for every PRD acceptance item.
- Clearly labeled backup recording of the real workflow if the team chooses to make one.

## Acceptance criteria
- Fresh launch supports typed offline folder creation without cloud configuration.
- The approved English and Nigerian-language demo paths create or open real artifacts and verify them.
- Provider outage does not crash the app and leaves local typed commands available.
- No secrets exist in Git history, frontend bundle, installer, screenshots, or logs.
- The complete staged demo succeeds at least 8 of 10 rehearsals.
- 4 GB Windows behavior is measured on physical hardware or explicitly marked unverified.

## Dependencies and handoff
Begins integration after Tasks 01–07 are stable and completes after Tasks 08–09. This owner may fix cross-cutting integration defects but should return component-specific defects to the relevant task owner when practical.
