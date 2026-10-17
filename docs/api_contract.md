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
| PUT / DELETE | `/secrets/{groq\|gemini\|speech_server}` | `{api_key}` | `{provider, configured}` |
| POST | `/reset` | | removes every saved code, setting and history entry |
| GET | `/providers/{name}/models` | | models the account can use (requires cloud consent) |
| POST | `/agent/runs` | `{text, language?}` | `Run` (409 if another task is active). Omit `language` to detect it |
| GET | `/agent/runs/current` | | the most recent `Run`, or null |
| GET | `/agent/runs/{id}` | | `Run` |
| GET | `/agent/runs/{id}/wait?after=N&timeout=15` | | `Run`, as soon as its `version` is no longer `N` (or after `timeout` s): the desktop app follows runs this way instead of polling |
| POST | `/agent/stop` | | `{stopped: [run ids]}`; every unfinished task stops now (a running command is killed). Also "Vico, stop" heard by the wake listener |
| POST | `/warm` | | `{warming}`; Vico was summoned or woken: checks the connection, opens the AI connection, refreshes the app list |
| POST | `/agent/runs/{id}/decision` | `{step_id, approved, confirm}` | `Run`; `confirm: true` required for `confirm_required` steps |
| POST | `/agent/runs/{id}/reply` | `{answer}` | `Run` (answers a clarification) |
| POST | `/agent/runs/{id}/cancel` | | `Run` |
| GET | `/agent/tools` | | tool names, categories, risk levels |
| POST | `/audio/start` | `{language?, auto_stop?}` | recorder status (omit `language` to detect it). With `auto_stop` the engine ends the recording when the user has finished speaking and transcribes at once |
| POST | `/audio/auto-stop` | `{patient?}` | end-of-speech detection for a recording already running (started by the wake word); `patient` (default true) waits for a 3.5 s pause |
| GET | `/audio/status` | | `{recording, elapsed_s, max_s, level, full, silent, device}`; `silent` = every microphone gives digital silence. With `auto_stop` also `{stage: recording\|transcribing\|ready, heard, result?, error?}` |
| POST | `/audio/stop` | `{transcribe}` | `{seconds, transcript}`; audio is discarded afterwards |
| POST | `/audio/cancel` | | stops and discards |
| GET | `/audio/wake` | | `{enabled, state, error, woke}`; `woke` is true once per "Hey Vico" (recording already started) |
| POST | `/voice/speak` | `{text, language}` | `{audio_b64, mime, provider, model, spoken, latency_ms}` when voice replies are on: Gemini 3.8 TTS for English, Hausa, Igbo and Pidgin (English voice); YarnGPT on the user's speech server for Yorùbá; the computer's own voice for English offline. `spoken` is the part read aloud (long answers: the first sentences). Played from memory |
| POST | `/system/microphone-settings` | | opens Windows' microphone privacy page (only opens it) |
| GET | `/speech-server/health` | | which engines the user's speech server has ready |
| GET / DELETE | `/history` | | entries / `{deleted}` |
| POST | `/browser/close` | | closes Vico's browser window |

## Run

`state` moves through `normalizing → planning → validating → awaiting_approval → executing → verifying → planning → … → completed | failed | cancelled`, with `awaiting_clarification` when the planner asks a question and `cooling_down` (with `cooldown_until`) while every free model is rate-limited; the task resumes by itself. Each `Step` carries the tool, redacted arguments, the human-readable `effect`, affected `targets`, the policy `outcome` (`allowed`, `approval_required`, `confirm_required`, `denied`), the user's `approval`, the execution `status` (`succeeded`, `unverified`, `failed`, `denied`, `rejected`) and the `verification` evidence.

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


## Run fields added for the avatar and speed

- `version`: increases on every change the desktop app shows; see `/agent/runs/{id}/wait`.
- `mode`: `cloud`, `offline`, or `local` (an exact simple command such as "open notepad" ran without the AI).
- `control`: set when the request was about Vico itself, never a task: `{action: stay|go|move|greet|settings|voice,
  where?, value?: on|off}`. `settings` opens Vico's settings (the only way back into them); `voice` switches spoken
  replies and is saved as `settings.voice_replies`.
- `steps[].stage`: where the step happens on screen (`{rect: {x, y, width, height}, kind}` in physical pixels) or
  null; found alongside the step, never before it.

## Settings fields

`look` (current look), `looks` (the picked looks), `rotate` (take turns: each new summon uses the next one),
`spots` (where each look was dragged or sent), `voice_replies` (off by default), `wake_word` (on by default).

## Tools added in this version

`set_volume`, `set_brightness`, `media_key`, `clipboard_get`, `clipboard_set`, `screenshot`, `compose_email`,
`click_at`, `scroll`, `look_at_screen`, `click_on_screen`, `browser_upload`, `web_lookup` (`{query, purpose?, deep?}`).
Secrets accepted by `/secrets/{name}`: `gemini`, `groq`, `mistral`, `openrouter`, `tinyfish`, `speech_server`.
Plans may be `{"kind":"unsupported", "never": true}` (payments, passwords, CAPTCHAs); any other unsupported plan
becomes a question to the user.
