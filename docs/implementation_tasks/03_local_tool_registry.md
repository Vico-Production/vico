# Task 03 — Safe local tool registry and effect verification

## Goal
Implement the eight real laptop actions and verify their effects instead of returning mock success messages.

## Scope
- Implement `create_folder`, `find_files`, `open_file`, `open_app`, `save_note`, `read_text`, `summarize_document`, and `list_folder` handlers.
- Keep every file operation inside the approved demo workspace.
- Build an index that exposes opaque file IDs instead of arbitrary paths.
- Restrict `open_app` to fixed keys such as Notepad, Calculator, and VS Code when installed.
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
