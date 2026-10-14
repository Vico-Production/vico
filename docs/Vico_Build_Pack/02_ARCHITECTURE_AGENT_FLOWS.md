# Architecture & Agentic Orchestration

## Architectural decision
**Windows-first Tauri 2 + React/Vite/TypeScript** desktop shell; **Python 3.12** sidecar for Windows file/application operations; hosted free-tier API adapters for speech/translation/reasoning. No hosted backend, server subscription, DB instance, or local LLM needed for MVP. Desktop UI talks ONLY to authenticated local sidecar via Tauri IPC or loopback with unpredictable startup token; prefer Tauri commands if practical. Sidecar may call cloud API *after user consent*, never proxy secret into JavaScript frontend.

```text
MIC / TEXT ──> Tauri UI ──> Orchestrator (local sidecar)
   |                    |         |
   |                    |         ├─ Local audio preprocessing / VAD (optional)
   |                    |         ├─ Speech adapter ───────────> free-quota cloud STT
   |                    |         ├─ Translation adapter ─────> cloud LLM/provider
   |                    |         ├─ Planner adapter ─────────> free-quota LLM with strict JSON
   |                    |         ├─ Policy gate / consent UI
   |                    |         ├─ Typed tool registry (local filesystem & apps)
   |                    |         ├─ Verifier / result formatter
   |                    |         ├─ TTS adapter ─────────────> optional free provider/local English voice
   |                    |         └─ SQLite activity + configuration
   └── NO hot mic or unsanctioned background capture
```

## Mode A: Agent flow (finite-state machine)
`IDLE -> CAPTURING -> TRANSCRIBING -> REVIEW_TRANSCRIPT -> NORMALIZING -> PLANNING -> VALIDATING -> AWAITING_APPROVAL -> EXECUTING -> VERIFYING -> COMPLETED | FAILED | CANCELLED`

1. Push-to-talk; max 15 s audio; opt-in online audio transfer.
2. STT returns `language, raw_text, provider, latency_ms, confidence?`. If confidence unavailable, don't invent one.
3. Show raw transcript. On uncertainty permit user correction. Normalize language to English using translation provider; preserve user original alongside canonical text.
4. LLM sees *only* task description, tool manifest, minimal workspace context; asked to emit exactly one tool invocation or `clarify/unsupported`. No shell commands or scripts.
5. Parse strictly with Pydantic; reject extra fields, invalid enum values, absolute paths outside demo workspace, URL schemes, and path traversal. Tool names must be registry keys.
6. Policy gate: safe read-only tool auto-approve only within nominated workspace; write operations require user approval by default; anything high risk denied by MVP policy.
7. Execute with OS APIs. Timeouts/exception handling; no elevated process.
8. Verify result via existence checks/file launch process status. Never declare success based only on model text.
9. Human-readable result + event log with redacted arguments; optionally translate status into user's selected language.
10. Local cancellation stops queued steps; no infinite autonomous action loops.

## Mode B: Interpreter flow
`SELECT_LANGS -> CAPTURE -> STT -> REVIEW -> TRANSLATE -> REVIEW -> SPEAK_IF_AVAILABLE -> READY_NEXT_TURN`.
- Typed text can bypass STT. Switch speaking direction; prevent feedback loops during TTS playback.
- Use language tags `en`, `yo`, `ha`, `ig`; optional `pcm`/Pidgin as experimental. Dialects and code-switching require explicit caveats.
- Default two-speaker turn-taking (not overlapping continuous speech).

## Tool registry (MVP)
Schemas require `additionalProperties=false`, allowlisted paths, parameter length bounds, canonical path checks, cooldowns.

```json
{"tool":"create_folder","args":{"relative_path":"Hackathon"}}
{"tool":"find_files","args":{"query":"attendance","scope":"demo_workspace"}}
{"tool":"open_file","args":{"file_id":"opaque-indexed-id"}}
{"tool":"open_app","args":{"app_key":"vscode"}}
{"tool":"save_note","args":{"title":"Project ideas","content":"..."}}
{"tool":"read_text","args":{"file_id":"opaque-indexed-id"}}
{"tool":"summarize_document","args":{"file_id":"opaque-indexed-id"}}
{"tool":"list_folder","args":{"relative_path":"."}}
```
- `create_folder`: idempotent within workspace; confirmation, verifies directory exists.
- `find_files`: casefold + filename search inside allowed folder; returns opaque IDs not arbitrary paths.
- `open_file`: opening only a user-selected indexed file with allowlisted extension; no executables/scripts.
- `open_app`: fixed mappings to `notepad`, `calculator`, `vscode` if installed; no user-controlled executable paths.
- `save_note`: safe filename, plain `.txt`/`.md`, prevent overwrite unless confirmed.
- `read_text`: only text/markdown under size cap e.g. 100KB; never automatically uploads content.
- `summarize_document`: explicit secondary *content upload* consent; send only selected text with max chars and no credential files.
- `list_folder`: bounded list / pagination.
- `play_audio_file` (P1 if time): only in workspace and user-approved files.

## Tool permissions
`LOW`: list, search, inspect metadata in nominated workspace; `MEDIUM`: create folder, save note, open safe file or app; `HIGH`: content sent to cloud, delete/move/overwrite, browser submission; prohibit destructive and external-send operations in MVP. Always display path and effect in approval UI.

## Reasoner output contract
```json
{"kind":"tool_call","tool":"create_folder","arguments":{"relative_path":"Demo"},"explanation":"Create Demo inside the permitted workspace"}
```
OR `{"kind":"clarify","question":"Which file?"}` OR `{"kind":"unsupported","reason":"This task is not in the approved tool set."}`. The model returns a proposal; it does **not** have operating-system execution permissions.

## Planner pseudocode
```python
async def handle(request):
    utterance = request.text or await speech.transcribe(request.audio)
    original = await user_review(utterance)
    canonical = await translator.to_english(original, request.language)
    proposed = await planner.propose(canonical, allowed_tool_manifest())
    validated = schema_and_policy_validate(proposed, request.workspace)
    if validated.requires_approval and not await ui.ask_approval(validated):
        return cancelled()
    result = await tool_registry.execute(validated)
    verified = await verify_effect(validated, result)
    log_redacted(original, validated.tool, verified)
    return verified
```

## Provider interfaces
```python
class SpeechProvider: async def transcribe(audio: bytes, language_hint: str) -> Transcript: ...
class Translator: async def translate(text: str, src: str, dst: str) -> Translation: ...
class Planner: async def plan(text: str, tools: list[ToolSpec]) -> Plan: ...
class TTS: async def synthesize(text: str, language: str) -> AudioOrUnavailable: ...
```
Each returns `source`, `duration_ms`, `quota_or_status`, `error_code`; prefer fallbacks and warn on language mismatches. Do not silently send data to a second provider.

## Offline behavior
When network unavailable, deterministic local parser supports typed commands such as `create folder X`, `find X`, `open notepad`, `show files` (English first). Offline speech is optional small `whisper.cpp` model if performance allows; do NOT quietly download multi-GB ASR models or assume Nigerian-language quality. Interpreter text translation offline is *not* guaranteed on 4GB hardware.

## Security architecture
Only loopback IPC; ephemeral local credential if socket; API keys stored in OS keychain/credential manager, not repository or browser localStorage. Prevent path traversal with `Path.resolve()`+`is_relative_to(approved_root)` including symlinks; allow extensions `.txt`, `.md`, `.pdf` (PDF requires real parser) and safe media. Reject executables. No wildcard GUI macros. Treat document content and provider messages as untrusted input, not instructions.
