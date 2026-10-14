# Task 04 — Python sidecar, authenticated IPC, settings, and history

## Goal
Provide a reliable local service boundary between the Tauri application and Python agent runtime.

## Scope
- Implement a FastAPI service bound only to `127.0.0.1` on an ephemeral port.
- Generate a random per-launch bearer token in the Tauri backend, pass it to the sidecar process, and require it on every request.
- Have Tauri own sidecar start, health check, shutdown, crash detection, and reconnect behavior.
- Prevent arbitrary web origins from using the service; validate origin where present.
- Store settings, provider metadata, and minimal action history in SQLite.
- Store secrets through the Windows Credential Manager/keyring abstraction, never SQLite, frontend storage, or logs.
- Add clear-history and health/status endpoints.

## History policy
Store timestamp, selected language, user-facing action summary, tool name, approval outcome, and verified result. Do not persist raw audio, document content, full provider prompts, or the raw transcript by default.

## Deliverables
- Service entry point, authenticated middleware, health endpoint, and lifecycle management.
- Settings/history repositories and migrations.
- Tauri commands that proxy UI requests so the bearer token is not exposed as a normal frontend setting.
- Integration tests for unauthorized access, startup, shutdown, crash, and database recovery.

## Acceptance criteria
- Requests without the launch token return 401.
- The service is never bound to a non-loopback address.
- Closing Vico terminates recording and the sidecar.
- Restart preserves settings/history without preserving sensitive temporary content.
- A sidecar failure produces a recoverable UI-facing error rather than a desktop crash.

## Dependencies and handoff
Depends on Task 01. Coordinate endpoint payloads with Tasks 06–09; security and tool execution must still pass through Tasks 02 and 03.
