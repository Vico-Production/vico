# Task 05 — Cloud provider adapters, quotas, and privacy controls

## Goal
Implement replaceable speech, translation, planning, summarization, and TTS provider interfaces without making a paid service mandatory.

## Scope
- Implement provider protocols and normalized results for speech, translation, planning, summarization, and TTS.
- Add one verified free-tier planner/translation provider and one verified free-tier STT provider, configurable through environment/settings.
- Query or document the actual available model names; do not hardcode speculative model IDs.
- Add timeouts, retry-after handling, quota/rate-limit status, request budgets, health checks, and stable error mapping.
- Require a transmission-consent flag for audio/text and a separate content-upload flag for document summarization.
- Ensure fallback to a second provider occurs only when it was configured and consented to.
- Keep API secrets outside frontend bundles and redact provider errors.

## Research record
Create `resources-evaluation.csv` for dependencies actually considered on the P0 path. Record repository, version, license, free-tier constraints, Windows support, security exposure, and a sample result. The remaining P1 candidates do not block the build.

## Deliverables
- Provider modules under `services/agent/app/providers/`.
- Mock providers for deterministic tests.
- Configuration guide with exact free-tier caveats and no paid fallback.
- Contract tests for malformed responses, 401, 429, timeout, outage, and unsupported language/TTS.

## Acceptance criteria
- Invalid planner JSON is never converted into an executable action.
- Provider unavailability returns a typed error that enables offline/typed fallback.
- No secret or submitted document text appears in logs.
- The configured core path can be set up without billing details, or is clearly marked blocked and disabled.

## Dependencies and handoff
Depends on Tasks 01 and 02. Task 06 consumes planning; Task 08 consumes speech; Task 09 consumes translation and TTS.
