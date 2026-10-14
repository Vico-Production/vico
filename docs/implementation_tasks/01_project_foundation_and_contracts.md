# Task 01 — Project foundation and shared contracts

## Goal
Create the monorepo skeleton and the shared API contracts that every other workstream will use. This task owns structure and interfaces, not feature implementation.

## Scope
- Scaffold `apps/desktop` as React + Vite + TypeScript with Tauri 2.
- Scaffold `services/agent` as a Python 3.12 package.
- Create `tests/{unit,integration,e2e,fixtures,language_samples}` and `scripts/`.
- Add root development commands, `.gitignore`, `.env.example`, license placeholders, and `THIRD_PARTY_NOTICES.md`.
- Define the versioned request/response and error envelopes shared by the UI, Tauri layer, and Python service.
- Define language tags (`en`, `yo`, `ha`, `ig`), operation states, provider status values, and public error codes.
- Add formatting, linting, type-checking, and basic CI configuration.

## Decisions fixed by this task
- P0 starts with the eight tools `create_folder`, `find_files`, `open_file`, `open_app`, `save_note`, `read_text`, `summarize_document`, and `list_folder`, and is extended to total control of the laptop and browser under the approval switch (decided 2026-10-14). Tool contracts must allow new action types, with the hard limits (no payments, no typing passwords or card details, no deletion without separate confirmation) enforced in the policy layer.
- `play_audio_file` is a P1 stretch feature and must not block P0.
- No PDF content reading in P0; PDF files may be found but not opened or summarized until a parser is approved.
- Shared contracts are versioned under `/api/v1` and reject unknown fields.

## Deliverables
- Bootable placeholder desktop window and importable Python package.
- Shared contract documentation in `docs/api_contract.md`.
- TypeScript types and matching Pydantic envelope models.
- Root commands for install, development, lint, type-check, and test.

## Acceptance criteria
- Frontend build and TypeScript check pass.
- Python package imports and its empty test suite runs.
- Contract fixture examples validate in both TypeScript and Python.
- No API keys, generated binaries, virtual environments, or `node_modules` are committed.

## Dependencies and handoff
This is the first merge target. All other tasks should consume these contracts and must not independently redefine public enums or response shapes.
