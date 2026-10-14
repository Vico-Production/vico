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
Updated 2026-10-14 for total control with an approval switch (on by default):
- Metadata reads (`list_folder`, `find_files`, `list_apps`, `list_windows`): run without asking, inside allowed folders.
- Ordinary actions (`read_text`, `create_folder`, `save_note`, `move_path`, `open_file`, `open_app`, browser and desktop tools): ask when the switch is on, run when it is off.
- `delete_path` (to Recycle Bin/Trash), `run_command`, and `summarize_document` (content upload): always ask with an extra confirmation, even with the switch off.
- Sends, posts and form submissions: always ask unless the user allows them in Settings.
- Denied regardless of the switch: payments, typing passwords/PINs/card details, paths outside the allowed folders, writes into system folders, overwriting existing files, unknown tools.

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
