# Task 03 — Safe local tool registry and effect verification

## Goal
Implement the eight real laptop actions and verify their effects instead of returning mock success messages.

## Scope
Updated 2026-10-14 for total control (see 07_DECISIONS_AND_RISKS.md):
- Implement the original eight handlers plus `move_path`, `delete_path`, `list_apps`, browser tools, desktop input tools and `run_command`.
- Keep every file operation inside the user's allowed folders (default: home folder); relative paths resolve inside the workspace.
- Tools take canonical paths checked by the path policy (opaque file IDs were dropped so multi-step plans can refer to files).
- `open_app` resolves installed apps by name (built-ins, Start Menu shortcuts, `.desktop` entries); never a model-supplied executable path.
- Make folder creation idempotent and prevent note overwrite in P0.
- Keep summarization execution split: safely read the approved excerpt, then pass it to the provider interface owned by Task 05.
- Add a verifier for directory/file existence, safe process launch status, and returned listings.

## Deliverables
- `services/agent/app/tools/` implementations and registry.
- Opaque file index with bounded lifetime or workspace invalidation.
- Tool result and verification result models.
- Unit and integration tests using temporary workspaces.

## Acceptance criteria
- Every P0 tool has a success, failure, denial, timeout, and idempotency test where applicable.
- Results are based on filesystem/process checks, not model prose.
- Executables and scripts cannot be opened through `open_file`.
- Search and listing are bounded and paginated.
- Note filenames preserve Unicode safely and cannot overwrite an existing note.

## Dependencies and handoff
Depends on Tasks 01 and 02. Use a stub summarizer until Task 05 lands. Do not implement UI, transport, or provider-specific code here.
