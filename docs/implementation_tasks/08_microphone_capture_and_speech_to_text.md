# Task 08 — Push-to-talk capture and speech-to-text pipeline

## Goal
Add privacy-preserving short audio capture and verified speech transcription for Agent Mode.

## Scope
- Implement microphone permission handling and push-to-talk capture with a 15-second maximum.
- Show unmistakable listening, processing, cancellation, and error states.
- Produce the format required by the selected STT provider and clean up temporary audio after completion or failure.
- Send an explicit language hint (`en`, `yo`, `ha`, or `ig`) rather than relying on automatic detection.
- Display the returned transcript for editing before planning.
- Prevent recording during TTS playback and ensure recording stops on window/app close.
- Add fixtures and a repeatable benchmark runner for consented language samples.

## Deliverables
- Frontend capture component and audio utility.
- Sidecar transcription endpoint integration.
- Language-sample manifest and results template recording provider, latency, transcript, and intent correctness.
- Tests for missing mic, denied permission, silence, cancellation, timeout, oversized recording, and provider outage.

## Acceptance criteria
- Five English clips are visibly transcribed with honest error states.
- At least five attempts in one speaker-tested Nigerian language are measured; the app labels support according to results.
- Yoruba diacritics and all Unicode transcripts survive the complete pipeline.
- No temporary WAV remains after the operation completes.
- Failure always leaves typed input usable.

## Dependencies and handoff
Depends on Tasks 04, 05, and 07. Task 06 receives only the user-reviewed transcript, not unreviewed STT output.
