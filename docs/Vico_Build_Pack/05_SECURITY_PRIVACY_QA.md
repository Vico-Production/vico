# Security, Privacy, QA and Release Checklist

## Data map
Audio captured on device → possibly sent to configured speech provider with explicit consent. User text → possibly sent to translation/planner provider. Local filesystem metadata stays local except minimal metadata specifically approved for planning. Document contents are **never uploaded unless user chooses a file and consents to sharing its contents for summarization**. Results and event history locally in SQLite. Keys stored in OS credential manager or protected Python sidecar environment; never in UI code.

## Threat model
1. **Prompt injection:** malicious local document attempts to instruct assistant to reveal secrets → read as data, never as system/tool instructions; separate system policy, reject instructions from retrieved text.
2. **LLM hallucinated tools:** fabricated function names/arguments → schema validation + allowlist; no dynamic `eval`, `exec`, shell, arbitrary subprocess.
3. **Path traversal/symlinks:** normalize/canonicalize, root-bound guard after resolving links, no escaping approved workspace.
4. **Dangerous changes:** user preview, explicit approval, no delete/overwrite/send/purchase in MVP.
5. **Credential leakage:** secrets in keychain; no frontend bundle, screenshots, logs, telemetry or uploaded project files; rotate if exposed.
6. **Cloud provider privacy:** badge before transmission, per-provider disclosure and retention/data-usage link; use synthetic data for judges; log minimal redacted prompts.
7. **Audio privacy:** push-to-talk, visible recording indicator, max 15 seconds, no always-on hot mic, cancel stops recording, delete local temporary WAV after result.
8. **Excessive agency:** a single tool call/approval per step, max 3 turns, bounded timeouts, cancel capability.
9. **Unauthenticated loopback:** random per-launch token and 127.0.0.1 binding if HTTP sidecar used; origin check or prefer IPC.
10. **License risk:** only incorporate repository/model weights after confirmed license, commercial caveats, attribution; no unofficial download mirrors.

## Error states and graceful fallbacks
No mic → typed input; STT low quality → editable transcript; mistranslation → user correction; API 401 → configuration banner; 429 → backoff and switch to already consented alternate or typed mode; internet offline → limited deterministic local tasks; model invalid JSON → re-request once or clarify; unsupported language TTS → display text only; unrecognized file → request selection; policy deny → explain restriction without executing; sidecar crash → UI reconnect and preserved history.

## QA cases: Given/When/Then
- Given user says 'delete everything', when planner proposes delete, then it is denied as unsupported.
- Given a local note contains 'ignore previous instructions', when summarized, then this content is treated as text only.
- Given a model requests `/Users/...` or `C:\\Windows`, when validated, then path is rejected.
- Given the user chooses a 120KB file for summary, when size cap is 100KB, then UI requests a smaller excerpt.
- Given no internet, when typed 'create folder Demo', then permitted local workspace folder is created and cloud offline badge remains visible.
- Given transcript omits a Yoruba proper noun, when user edits transcript, then normalized action uses the corrected text.
- Given duplicate create-folder operation, when rerun, then it is idempotent and displays 'already exists'.
- Given the app is closed, when reopening, then recording has stopped and no background microphone remains active.

## Release gates
[ ] `pytest` passes locally, frontend builds, Tauri installer launches.
[ ] End-to-end demo repeated 10 times; per-language success rates recorded.
[ ] No secrets in git tree or installer or logs.
[ ] No unpaid backend required; all paid models disabled by default.
[ ] Third-party license inventory generated and reviewed.
[ ] Local-only fallback tested offline.
[ ] Audio/data flow disclosed to user.
[ ] All tool actions audited and verified; no false success states.
[ ] RAM and startup latency measured or stated unverified.
[ ] No misleading claims of perfect accuracy or 100% offline operation.
