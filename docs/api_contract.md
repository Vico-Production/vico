# Engine API contract (v1)

The Python engine (`services/agent`) serves this API on `127.0.0.1` at a random port. The Tauri shell starts it with a random 64-hex-character token in `VICO_TOKEN`, reads `VICO_READY port=<n>` from its stdout, and adds `Authorization: Bearer <token>` to every request. The web UI never sees the token: it calls the Tauri command `api_request(method, path, body)`.

Types are defined in `services/agent/app/contracts.py` and mirrored in `apps/desktop/src/lib/contracts.ts`. Example payloads in `tests/fixtures/contracts/` are validated by both the Python and TypeScript test suites, so the two sides cannot drift silently.

## Envelope

Every response, success or failure:

```json
{ "api_version": "1", "ok": true, "data": { }, "error": null }
{ "api_version": "1", "ok": false, "data": null,
  "error": { "code": "policy_denied", "message": "…", "retryable": false, "retry_after_s": null } }
```

Request bodies reject unknown fields (`422 validation_error`).

Error codes: `unauthorized`, `validation_error`, `not_found`, `policy_denied`, `consent_required`, `provider_unavailable`, `provider_auth`, `rate_limited`, `timeout`, `offline`, `invalid_plan`, `cancelled`, `mic_unavailable`, `unsupported`, `conflict`, `internal`. The shell adds `sidecar_unavailable` when the engine cannot be reached.

Language tags: `en`, `yo`, `ha`, `ig`, `pcm` (experimental).

## Endpoints (prefix `/api/v1`)

| Method | Path | Body | Returns |
|---|---|---|---|
| GET | `/health` | | version, platform, adapter, online, cloud_ready, speech_ready, cloud_consent, per-provider status and quota use, recording, browser_open |
| GET / PUT | `/settings` | partial `Settings` | full `Settings` |
| GET | `/languages` | | per-language capability labels (`untested` until measured) |
| GET | `/secrets` | | `{groq: bool, gemini: bool}` (never the key) |
| PUT / DELETE | `/secrets/{groq\|gemini}` | `{api_key}` | `{provider, configured}` |
| GET | `/providers/{name}/models` | | models the account can use (requires cloud consent) |
| POST | `/agent/runs` | `{text, language, original?}` | `Run` (409 if another task is active) |
| GET | `/agent/runs/{id}` | | `Run` |
| POST | `/agent/runs/{id}/decision` | `{step_id, approved, confirm}` | `Run`; `confirm: true` required for `confirm_required` steps |
| POST | `/agent/runs/{id}/reply` | `{answer}` | `Run` (answers a clarification) |
| POST | `/agent/runs/{id}/cancel` | | `Run` |
| GET | `/agent/tools` | | tool names, categories, risk levels |
| POST | `/audio/start` | `{language}` | recorder status |
| GET | `/audio/status` | | `{recording, elapsed_s, max_s, level, full}` |
| POST | `/audio/stop` | `{transcribe}` | `{seconds, transcript}`; audio is discarded afterwards |
| POST | `/audio/cancel` | | stops and discards |
| POST | `/interpreter/translate` | `{text, source, target}` | `{original, text, provider, model, latency_ms}` |
| GET / DELETE | `/history` | | entries / `{deleted}` |
| POST | `/browser/close` | | closes Vico's browser window |

## Run

`state` moves through `normalizing → planning → validating → awaiting_approval → executing → verifying → planning → … → completed | failed | cancelled`, with `awaiting_clarification` when the planner asks a question. Each `Step` carries the tool, redacted arguments, the human-readable `effect`, affected `targets`, the policy `outcome` (`allowed`, `approval_required`, `confirm_required`, `denied`), the user's `approval`, the execution `status` (`succeeded`, `unverified`, `failed`, `denied`, `rejected`) and the `verification` evidence.

## Planner contract

The planner must return exactly one of:

```json
{"kind":"tool_call","tool":"create_folder","arguments":{"path":"Demo"},"explanation":"…"}
{"kind":"clarify","question":"Which file?"}
{"kind":"unsupported","reason":"…"}
{"kind":"done","message":"…"}
```

Anything else is rejected; one retry is allowed, then the run fails with `invalid_plan` and nothing runs.

## Tools

| Category | Tools |
|---|---|
| Files | `list_folder`, `find_files`, `read_text`, `create_folder`, `save_note`, `move_path`, `delete_path`, `open_file`, `summarize_document` |
| Apps | `open_app`, `list_apps` |
| Web | `open_url` (default browser), `browser_open`, `browser_read`, `browser_click`, `browser_type`, `browser_press`, `browser_scroll`, `browser_back` |
| Desktop | `list_windows`, `focus_window`, `type_text`, `press_keys`, `click_element` (Windows) |
| System | `run_command` |

Risk levels: `auto` (metadata reads), `standard` (asks when approval is on), `confirm` (always asks: `delete_path`, `run_command`, `summarize_document`). Sends/posts/submissions are raised to confirm unless the user allows them. Payments and password/card entry are denied.
