# Task 02 — Security policy, approval rules, and path guards

## Goal
Build the security boundary before any model or operating-system operation can execute.

## Scope
- Implement strict Pydantic models for the eight P0 tool calls with unknown fields rejected.
- Implement canonical workspace resolution, traversal prevention, symlink escape prevention, filename sanitization, extension checks, and size limits.
- Build the tool permission registry and preflight policy evaluator.
- Return a structured decision: `allowed`, `approval_required`, or `denied`, with a user-facing reason.
- Add argument redaction utilities for logs and UI-safe summaries.
- Establish operation timeouts, maximum input lengths, and one-tool-call-per-plan enforcement.

## Approval matrix
- `find_files` and `list_folder`: automatic only inside the nominated workspace.
- `read_text`: requires explicit selection of an indexed file, but no cloud-upload approval.
- `create_folder`, `save_note`, `open_file`, and `open_app`: require action approval.
- `summarize_document`: requires action approval plus a separate content-upload approval.
- Delete, move, overwrite, arbitrary executable paths, scripts, shell commands, URLs, and paths outside the workspace are denied in P0.

## Deliverables
- `services/agent/app/agent/schemas.py`
- `services/agent/app/agent/policy.py`
- `services/agent/app/security/paths.py`
- `services/agent/app/security/redaction.py`
- Unit tests for each control and decision.

## Acceptance criteria
- Tests reject `../`, absolute outside paths, symlink escapes, alternate separators, reserved Windows names, unsupported extensions, oversized content, and extra JSON fields.
- A fabricated tool name can never reach execution.
- Cloud document content is unavailable to providers without the secondary approval flag.
- Tests run on Linux CI and include Windows-specific path fixtures.

## Dependencies and handoff
Depends on Task 01 contracts. Tasks 03, 05, and 06 must call this policy layer rather than duplicate validation.
