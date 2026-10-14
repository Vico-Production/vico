# Task 09 — Interpreter Mode, translation, and optional speech playback

## Goal
Deliver turn-based interpretation among English, Yoruba, Hausa, and Igbo with truthful speech capability labels.

## Scope
- Build source/target selectors, direction swap, two-speaker turn handling, typed input, and microphone reuse.
- Display original transcript and translated text side by side with editable review stages.
- Integrate the translation provider for all directed language pairs required by the demo test set.
- Add copy, retry, next-turn, and clear-conversation controls.
- Integrate TTS only for language/provider combinations that were actually validated.
- Prevent microphone feedback while TTS is playing.
- Show text-only output and an explicit unsupported notice when TTS is unavailable.
- Keep translation turns ephemeral by default; do not silently add them to action history.

## Deliverables
- Interpreter React panel and state machine.
- Translation/TTS sidecar endpoints and UI integration.
- Five reviewed sample phrases per language with expected meaning notes.
- Tests for direction switching, Unicode, provider errors, correction, unsupported TTS, and audio feedback prevention.

## Acceptance criteria
- Typed test samples run for English, Yoruba, Hausa, and Igbo and are labeled with measured/unknown quality honestly.
- At least one live spoken translation pair completes from capture through output.
- Translated text remains available when audio synthesis fails.
- The UI makes no claim of professional, perfect, simultaneous, or fully offline translation.

## Dependencies and handoff
Depends on Tasks 04, 05, 07, and 08. It must reuse the shared audio/provider contracts rather than introduce a parallel stack.
