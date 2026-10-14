# Task 07 — Desktop shell and Agent Mode user experience

## Goal
Build the accessible Windows desktop interface for onboarding, typed commands, action review, consent, and history.

## Scope
- Implement onboarding, language selection, demo workspace selection, and privacy disclosure.
- Build the Agent/Interpreter mode switch and Agent Mode layout.
- Add typed input, editable transcript, action preview, approval/rejection modal, cancellation, and result presentation.
- Render the timeline states: Heard, Understood, Proposed, Approved, Executing, Verifying, and Done/Failed/Cancelled.
- Show local/cloud/provider status and actionable error messages.
- Add history view and clear-history confirmation.
- Support keyboard-only operation, screen-reader labels, visible focus, reduced motion, and high contrast.
- Do not expose raw API keys or sidecar credentials in browser state.

## Deliverables
- React components, state management, API client, and routing/layout.
- UI tests for happy path, denial, cancellation, offline mode, sidecar failure, and history clearing.
- Stable selectors for end-to-end tests.

## Acceptance criteria
- A keyboard-only user can submit, edit, approve/reject, cancel, and inspect results.
- File paths and the exact effect are visible before approval.
- The UI never displays `Done` until the verifier reports success.
- Cloud transmission is visibly disclosed before the first request.
- The app launches to a usable typed/offline path with no provider configured.

## Dependencies and handoff
Depends on Tasks 01 and 04 contracts; full behavior integrates with Task 06. Keep Interpreter-specific panels in Task 09.
