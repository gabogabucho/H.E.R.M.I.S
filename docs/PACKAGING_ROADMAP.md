# Packaging readiness: from demo to first-time use

Deliver a Windows plugin that a new user can install, diagnose, recover and remove without a maintainer guiding the demo. Finish the existing product before adding features.

Audited baseline: `67925608936dfd74a67ad4b41b7dfc293e448a46` (`origin/main`), 2026-11-10. This is an implementation handoff, not a release approval. All work below is pending unless explicitly identified as existing.

## Release scope

- Core: install the plugin, enable Autopilot, draw real surfaces, arrange supported Windows applications, disable the mode and recover after restart.
- Optional: microphone, wake word, speech playback, camera gestures and account-backed Hermes skills. Their absence must not block core visual use.
- Preserve explicit consent for downloads, configuration changes, permissions, camera and account access. A copyable command is not automatic setup.
- Keep the prerequisite-based plugin delivery for this closure unless the team explicitly chooses a bundled installer. A standalone executable is a separate product decision, not a prerequisite for fixing onboarding.
- Gmail belongs to Hermes integrations; do not reintroduce credentials or a mail client into this interface plugin.

## What already exists — preserve it

| Existing behavior | Evidence at the audited baseline |
|---|---|
| First-use dependency install and detached Electron launch | `overlay_launcher.py:119–153` |
| Dependency refresh when the lockfile changes | `overlay_launcher.py:82–106` |
| Overlay reconnection after gateway token/port changes | `overlay/main.js:218–266` |
| Setup checklist, first-use welcome and replay commands | `setup_checks.py`, `welcome.py`, `commands.py` |
| Gateway voice event client and orb morph polish | commits `fa75bf4`, `1f00816` |
| Optional camera gestures and real-window actions | commits `525343f`, `6a0a272` |

These are implemented features, not evidence of a successful clean-machine release test. Do not rebuild them merely because an older roadmap lists them as pending.

## Execution order

`P1 runtime contract → P2 truthful readiness → P3 bootstrap recovery → P4 lifecycle and user guide → P5 clean Windows gate → P6 release pin and publication`

P2 can be developed after the P1 runtime decision is fixed. Each unit includes its own tests and documentation. No new gestures, providers, Spotify integration or visual redesign is needed for this closure.

### P1 — Align and enforce supported runtimes [P0]

**Evidence:** `README.md:26–31` advertises Node 20+, while `overlay/package.json:16–17` pins Electron 45.0.0 and its lockfile dependencies declare Node >=22.12.0 (`overlay/package-lock.json:26–27,44–45`). The launcher/checklist checks executable presence, not compatibility (`overlay_launcher.py:163–167`, `setup_checks.py:67–76`). This is a verified contract mismatch, not a reproduced Windows crash.

**Change:** establish one supported Node/npm contract consistent with the chosen Electron dependency; enforce it before installation and report the detected version with an actionable remedy. Verify the advertised Hermes minimum rather than assuming every 0.22 build supports current gateway tickets/events.

**Edit candidates:** `overlay_launcher.py`, `setup_checks.py`, `overlay/package.json`, `overlay/package-lock.json` only if dependency changes are necessary, corresponding tests, `README.md`, `docs/catalog/hermis.yaml`.

**Acceptance:** missing, incompatible, malformed-version and supported Node cases have deterministic tests; unsupported environments do not start npm; manifests, diagnostics and docs agree. A tested Hermes/Desktop version is recorded. Do not downgrade dependencies solely to retain an untested promise.

**Local progress (2026-11-10): Node subunit verified; P1 remains partial.** Stable Node >=22.12.0 is now declared in package/lock and checked by the launcher, setup and `/hermis check` before dependency installation. A five-second, shell-free `node --version` probe rejects missing, incompatible, prerelease, malformed, failed or timed-out results without starting the pipeline or writing a launch marker. Environment opt-out is preserved. Tests observed RED before implementation; runtime/commands/setup suites passed 5/6/11 tests. Independent isolated verification passed that subunit and Windows hidden-subprocess flag inspection; it found no candidate-caused blocker. A parent spot-check reran the runtime suite. A real tested Hermes/Desktop pair and clean Windows proof are still missing; the advertised Hermes >=0.22 minimum is not newly certified by this change.

Full candidate suite at this point: 90 tests, 2 failures and 1 skip. One failure was a stale old-runtime message expectation, updated and rechecked successfully; the other was the previously reproduced WebSocket handshake failure. The gateway Node client test remains skipped because overlay dependencies are absent. Independent launcher tests passed 14/16; both socket-bind failures reproduced on its baseline snapshot. These results do not constitute an all-green full suite or Windows release approval.

### P2 — Report readiness honestly [P0]

**Evidence:** any `cua:` allowlist entry currently produces a blanket computer-use success (`setup_checks.py:139–147`). `surface_data()` counts only warnings and can display “Todo listo.” despite unresolved informational checks (`:191–195`). Dependency readiness tests only for `node_modules`, unlike the launcher's lock fingerprint (`:72–76`).

**Change:** distinguish core readiness, optional capabilities and unverified checks. Check only permissions actually evidenced; configuration presence is not a live microphone, playback or gateway test. Reuse existing dependency freshness logic rather than adding another definition. Keep a machine-readable status and readable remedy aligned.

**Edit candidates:** `setup_checks.py`, the existing readiness/launcher helper boundary if needed, `commands.py`, existing setup surface renderer, corresponding tests and user docs.

**Acceptance:** partial allowlist, unreadable configuration, stale dependencies and unknown gateway state cannot produce an unqualified success. Disabled optional voice/camera does not mark core mode broken. No configuration or permission is changed by a check.

### P3 — Make bootstrap failures visible and recoverable [P0]

**Evidence:** npm install runs asynchronously with a 300-second timeout; failures primarily go to `overlay.log` (`overlay_launcher.py:119–153`). Launch markers are set before completion (`:170–193`). `autopilot` success means mode enabled, not overlay connected (`tools.py:213–229`). Preserve that distinction instead of silently redefining the existing tool contract.

**Change:** expose installing, starting, connected and failed states through the existing command/setup path; provide sanitized error details and an explicit retry path. Do not require the user to delete dependency directories or inspect a developer terminal.

**Edit candidates:** `overlay_launcher.py`, `tools.py`, `commands.py`, `setup_checks.py`, affected overlay status UI, corresponding tests and recovery docs.

**Acceptance:** deterministic tests simulate npm failure, timeout, missing binary, launch denial and retry. Mode enabled is never described as overlay connected without evidence. Retry does not duplicate processes or race an active install. Failure diagnostics contain no session tokens or credentials.

**Local recovery subunit (2026-11-10), not full P3 completion:** added read-only process-local startup snapshots and `/hermis retry`, which preserves Autopilot, welcome and surfaces. Failed installs release the local reservation/cooldown; launch failures expose fixed sanitized codes and can reinstall dependencies on explicit retry. A live npm wrapper or active worker blocks another attempt in the same host. The status distinguishes installation, startup, observed local connection and failure; a 30-second connection deadline is evaluated on diagnostic reads without killing processes. A connection in another process remains unverified.

Observed RED before implementation, then 8 focused recovery tests passed; command/setup suites passed 6/11. Full suite: 98 tests, 2 previously reproduced WebSocket failures (`test_broadcast_takes_over_dead_owner`, `test_ws_handshake_and_broadcast`) and 1 skipped gateway-client test because overlay dependencies are absent. Independent scratch verification passed recovery8/runtime5/commands6/setup11, a 17-input existing-command differential, authenticated overlay-vs-publisher accounting, and dead-wrapper retry without reinstalling valid dependencies. Its launcher suite passed 14/16; both socket-bound failures reproduced on the pre-change baseline. At that stage no OS install lock or process-tree termination had been added. The lock gap is addressed by the following subunit; descendant cleanup and real Windows proof remain pending.

**Cooperative host exclusion follow-up:** `bootstrap_lock.py` supplies a nonblocking held OS lock for the shared installation directory (`flock` on POSIX, byte zero with `msvcrt.locking` on Windows). Acquisition precedes worker/marker creation; open failures are distinct from contention and sanitized. Ownership spans npm installation and waiting for the owned startup wrapper; unknown live wrappers retain the guard. Competing hosts see `busy`. Never unlink the lock identity file, including after owner exit. Six deterministic tests cover real separate-process contention/reacquisition, install and wrapper lifetime, read-only/opt-out behavior, sanitized failure and the mocked Windows adapter contract. Windows execution and descendant cleanup are not established by those tests; broader P3 remains partial.

Independent isolated verification passed lock6/recovery8/runtime5/commands6/setup11, nine additional probe groups (failure-path release, unknown-process exclusion, actual owner crash recovery, 200 descriptor-stable lock cycles and Windows unlock-error closure), and a 17-input command/state differential against the pre-lock snapshot. Parent full suite: 104 tests, 2 known WebSocket failures and 1 dependency-related gateway skip. Independent launcher tests passed 14/16; both failures reproduced on its baseline. These results verify this cooperative-lock subunit, not Windows or full P3 release readiness.

### P4 — Close lifecycle and separate user setup from demo [P0/P1]

**Evidence:** update detection and gateway reconnect already exist. The detached overlay does not exit merely because Autopilot is off (`overlay_launcher.py:146–148`, `tools.py:176–219`). There is no documented clean stop/uninstall/data-retention workflow. `overlay/README.md` retains Day 1/2 statements inconsistent with the current implementation.

**Change:** document and verify install, first run, restart, update, explicit stop and uninstall. Define an intentional supported shutdown path if existing Hermes/plugin lifecycle cannot provide it; do not redefine `/hermis off` as process termination without an explicit decision. Preserve user state by default. Separate developer mocks from real-user instructions.

**Edit candidates:** `README.md`, `overlay/README.md`, `docs/` user guide; only lifecycle files demonstrated necessary by tests (`__init__.py`, `overlay_launcher.py`, `overlay/main.js`, `commands.py` and corresponding tests).

**Acceptance:** restart with new token/port reconnects; changed lockfile refreshes dependencies; repeated activation creates no duplicate overlay; intentional shutdown leaves no owned orphan process; uninstall instructions explain retained state and optional explicit cleanup. No automatic state deletion. Core operation needs no mock server, edited source path or demo account.

Optional voice setup must explain install/configure/restart/test separately and identify Desktop-only toggles the plugin cannot inspect. Camera and cloud accounts remain opt-in. Do not promise that a plugin can remove those consent steps.

### P5 — Run a clean Windows release gate [P0]

**Depends on:** P1–P4. This Linux server can prepare tests and artifacts, but cannot certify Windows focus, Electron click-through, physical audio or camera behavior.

**Deliverable:** a checked-in test report under `docs/` recording candidate SHA, Windows/Node/npm/Hermes/Desktop versions, exact installation route, observed results and sanitized failure evidence. Never include credentials or account contents.

- Fresh Hermes profile: follow only the published install instructions; confirm plugin registration/enabling, `/hermis check`, `/hermis on` and a real rendered surface.
- Core: launch/arrange supported real apps, leave mode, restart gateway, update/relaunch and follow stop/uninstall instructions.
- Failure: no network during bootstrap, incompatible Node and restart during disconnection; confirm actionable recovery without developer intervention.
- Optional, reported separately: live wake/listening and actual playback, camera permission denial/on/off, and one authorized Hermes account-backed surface/reference interaction.

**Acceptance:** every core case has observed evidence, not a mock substitution. Optional failures have an honest unavailable/failed result and do not prevent core use. For each failure, name the blocker and owner before calling the package ready.

### P6 — Pin and publish the verified candidate [release action]

**Evidence:** `docs/catalog/hermis.yaml:1–8` still has a zero SHA. README advertises `hermes plugins install hermis`; the audited tree alone cannot establish upstream catalog availability. The source fallback documents clone + validate without proving registration/enabling.

**Change:** verify the actual upstream install contract, finish the tested source path, then pin the exact validated 40-character candidate SHA. Revalidate that pinned candidate after any release-relevant change. Add a supported CI gate for repeatable unit/validation checks if feasible; it does not replace P5.

**Acceptance:** the documented installation route works in the clean profile; catalog URL, capabilities and SHA match the tested artifact; required validator succeeds on that candidate. No placeholder SHA remains in the release entry.

**Authorization:** public visibility changes, remote push, release publication, catalog PR, video upload and submission require explicit authorization. Do not perform them as part of a local packaging fix. Keep hackathon video/form work separate from product readiness.

## Verification instructions for the implementing agent

Start from the audited `main` baseline or reconcile newer commits first. Preserve unrelated `.atl/` contents. Read the existing helpers/tests before changing shared state. Write a failing deterministic regression before each behavior fix, then observe green and run the full suite. Existing behavior through shared helpers must remain covered. Security, concurrency, dependency and environment changes require independent verification under repository policy.

Available commands (not executed as a suite during this audit):

```sh
python3 -m unittest discover -s tests -p test_setup_checks.py -v
python3 -m unittest discover -s tests -p test_commands.py -v
python3 -m unittest discover -s tests -v
```

Use an isolated environment with declared dependencies; this audit host did not have `websockets` installed. After dependency-install authorization, run `hermes plugins validate . --install-deps` on the candidate. Electron's existing renderer probe is `cd overlay && npx electron dev/artifact-security-test.js`; inspect prerequisites before running it. The interactive gesture probe downloads a model and is not an unattended CI gate. Mock-server demonstrations are developer smoke tests, never P5 evidence.

For each completed unit report: commit/diff, acceptance cases exercised, exact check outcomes, failed/skipped checks and remaining platform proof. Do not inherit historical test counts as current results.

## Audit status

Local polish follow-up (not a release gate): opening/refreshing setup no longer consumes the first Autopilot welcome, and the checklist summary distinguishes informational steps from detected missing prerequisites. Its remedy no longer suggests running every command in PowerShell. P2 remains open: permission coverage, dependency freshness and first-run visibility still need the broader work described above.

Initial audit: read-only inspection of baseline sources/manifests; explorer reproduced the partial-allowlist and optimistic-readiness cases directly from baseline Python source; parent spot-checked those branches and the lockfile engine constraints. No full suite, dependency install, Windows session, account access or publication occurred during that audit.

### Product polish follow-up — 2026-11-10

Implemented locally: setup no longer writes the welcome-completion flag; the summary avoids an unqualified ready claim and directs users to each step rather than treating every remedy as a PowerShell command. No permission, credential, state format or dependency manifest changes.

Verification: both regression tests failed before the fix; command/setup focused suites passed 17 tests afterward. Eleven existing command inputs matched baseline stdout, stderr, exit code and persisted state for an already-onboarded user. Full candidate suite: 85 tests, 83 passed, one failure (`test_ws_handshake_and_broadcast`), one skipped gateway-client test because overlay dependencies are absent. Full baseline: 83 tests, one failure (`test_broadcast_takes_over_dead_owner`), same skip. A bounded reproduction of both named WebSocket tests failed on both baseline and candidate; those failures are pre-existing and unresolved, not a release pass. Native assessment: medium, under budget, review not due; no reviewer approval claimed. No Windows/Electron/audio E2E performed.

Next review findings to address in separate bounded units:

- `tools.py:199–201`: first-run setup is shown only for warnings, so manual Desktop instructions may remain hidden when all items are informational. Keep optional features non-blocking while making their setup discoverable.
- `setup_checks.py:139–147`: a partial `cua:` allowlist must not imply all keyboard permissions are configured; never widen permissions automatically.
- `setup_checks.py:67–76`: reuse the launcher's existing dependency freshness check rather than trusting directory presence.
- `overlay/renderer/shell.js:696–702`, `overlay/main.js:141–151,355`: a refresh can resolve `false` while disconnected, leaving the button on its waiting label. Handle false as well as rejected promises.
- `setup_checks.py:110–116`: the offered `voice.auto_tts` command cannot itself repair the Desktop-local speaker toggle. Scope remediation to the setting it actually changes.
