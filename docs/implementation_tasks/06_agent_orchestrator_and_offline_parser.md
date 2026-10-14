# Task 06 — Agent state machine, planner flow, and offline parser

## Goal
Connect text input to a safe, observable, cancellable action lifecycle.

## Scope
- Implement the Agent Mode finite-state machine from input through verification.
- Preserve the original utterance and canonical English intent in memory for review, without persisting them by default.
- Call the planner with only the task, approved tool manifest, and minimal workspace context.
- Strictly parse `tool_call`, `clarify`, and `unsupported` results.
- Run every proposed call through policy preflight and approval before the registry.
- Support rejection, approval timeout, cancellation, provider errors, invalid JSON, and verification failure.
- Implement a deterministic offline English parser for `create folder X`, `find X`, `open notepad`, and `show files`.
- Limit execution to one tool call per approval and at most three clarification turns.

## Deliverables
- State, orchestrator, cancellation, and deterministic parser modules.
- Event stream/status payloads for the desktop timeline.
- Unit tests plus integration tests with mocked providers and real temporary-workspace tools.

## Acceptance criteria
- No state transition can skip validation or required approval.
- Cancel prevents queued execution and produces a terminal `cancelled` state.
- Offline typed commands work with all cloud providers disabled.
- Unsupported or dangerous commands explain the denial and perform no side effect.
- Verification failure is reported as failure, never success.

## Dependencies and handoff
Depends on Tasks 01–05. Task 07 renders its states and sends approval/cancellation decisions.
