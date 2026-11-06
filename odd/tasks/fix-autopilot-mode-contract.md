# Fix autopilot WebSocket mode contract

## Objective
Make the autopilot tool publish the `x-lumen-desktop v2` mode message and prove both activation and deactivation over an authenticated WebSocket client.

## Problem and why
`tools.autopilot` currently broadcasts `{ "type": "autopilot", "state": "on|off" }`, while the documented overlay protocol expects `{ "type": "mode", "autopilot": true|false }`. The overlay therefore does not receive the mode transition it understands.

## Scope and constraints
- Authorized: update the autopilot broadcast contract, add regression coverage, and correct the local protocol example if needed.
- Out of scope: remote PR edits/comments, push, merge, unrelated follow-ups, and native review (parent owns the review transaction).
- One task: `AP-1` — publish and verify the v2 mode contract for both state transitions.
- Acceptance: authenticated live WS client receives the exact `mode` payload on `on` and `off`; off's close event remains correctly ordered and tested if emitted; the focused and full test suite pass.
- Strict TDD: enabled by user AGENTS instructions. Required order is observed RED, minimal GREEN, then refactor only if needed.
- TDD source: user-provided AGENTS.md says `Strict TDD Mode: enabled`.
- Test runner: `python -m unittest discover -s tests -v` (from `tests/test_skeleton.py`).
- Dependency: existing `websockets>=15,<16`; use the discovered local Python environment and do not install unless required.
- Route: delegated direct; mandatory writer/preparation delegation was assigned by parent because source and test are both non-trivial and reading prepares the implementation.
- Forecast: approximately 50–100 authored changed lines, including this task record; default delivery strategy `ask-on-risk`.

## Checklist and evidence
- [x] `AP-1` Add a failing authenticated WS regression for both mode transitions, then update the broadcast and any local protocol example; run the focused test and full suite.
  - RED: `python -m unittest tests.test_skeleton.SkeletonTest.test_ws_handshake_and_broadcast -v` failed as expected at the activation assertion: actual `{"type": "autopilot", "state": "on"}`, expected `{"type": "mode", "autopilot": true}`.
  - GREEN: same focused test passed after changing the broadcast to `{ "type": "mode", "autopilot": active }`; the authenticated client observed exact payloads for both `true` and `false`.
  - Functional checks: `python -m unittest tests.test_skeleton.SkeletonTest.test_ws_handshake_and_broadcast -v` — passed; `python -m unittest discover -s tests -v` — 3 tests passed.
  - Local docs: `BRIEF.md` already had the correct v2 example `{ "type": "mode", "autopilot": true }`, so no doc edit was needed.
  - Rollback boundary: revert only the autopilot message change, its regression assertions, and the matching local protocol example; no unrelated behavior is involved.
  - Commit identity: pending; parent will coordinate commit after review.

## PR body example corrections for parent
- Replace the stale bullet `{ "type": "autopilot", "state": "on" | "off" }` with `{ "type": "mode", "autopilot": true | false }`.
- Replace the stale historical live-received line `{ "type": "autopilot", "state": "on" }` with a clearly labeled current expected/retested example `{ "type": "mode", "autopilot": true }`. Do not present the old line as a newly observed trace.

## Progress and persistence
- Progress: implementation and regression coverage complete; no source formatter or normalizer was run. Candidate remains uncommitted for parent review.
- Engram mirror: pending; parent reports host session registration blocks `mem_save`, and instructed not to retry.
- Next: parent performs native risk/review flow and coordinates commit. The two PR body examples above remain remote-update suggestions only.
