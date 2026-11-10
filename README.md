# H.E.R.M.I.S

**Autopilot Mode for Hermes Agent: your Windows desktop becomes an OS for agents.**

Say *"Hey Hermes, autopilot mode"* and Hermes changes shape: a bar morphs into an orb, it answers by voice in short sentences, **draws** what you need to see as floating surfaces over your real desktop, and **drives** your real windows. Say *"exit autopilot"* and it goes back to the Hermes you know.

The agent never sends HTML for its own surfaces, only data. The overlay decides how to draw it.

> Built for the Nous Research Hermes hackathon (November 2026). Concept and design notes (Spanish): [`BRIEF.md`](BRIEF.md) · plan: [`ROADMAP.md`](ROADMAP.md) · technical research: [`docs/RESEARCH.md`](docs/RESEARCH.md).

## What it does

| | |
|---|---|
| **Autopilot Mode** | `autopilot(on\|off)` switches the mode. While it is on, the plugin adds mode instructions to each turn (short spoken answers, data goes to surfaces) plus a cached summary of what is on screen. |
| **Surfaces** | `render_surface` draws `notification`, `document`, `email_list`, `table`, `cards`, `web`, `image` or `artifact` surfaces. `close_surface` and `list_surfaces` manage them. State persists between turns and restarts. |
| **Artifacts** | With Autopilot on, ```` ```html ```` and ```` ```svg ```` blocks in Hermes' replies are copied to the overlay as sandboxed artifact surfaces. |
| **Windows** | `layout_windows` splits, tiles (`grid`), maximizes, focuses or minimizes others on real Windows windows through Win32. `launch_app` finds and opens desktop apps. |
| **Living orb** | The orb shows listening from Hermes' voice events (`voice.status`, `wake.detected` on the local gateway) and thinking / acting from Hermes' own turn and tool hooks. |
| **`/hermis`** | `/hermis status`, `/hermis on`, `/hermis off`, `/hermis check` (read-only installation check), `/hermis setup` (setup checklist), `/hermis retry` (retry overlay startup without changing mode or surfaces), `/hermis tour` (replay the welcome), `/hermis gestures on|off`. |
| **Welcome** | The first time Autopilot turns on, Hermes introduces the mode by voice in a couple of sentences and the overlay shows a **quick guide**: example requests and what each camera gesture does. It happens once; replay it with `/hermis tour`. |
| **Onboarding** | If something is missing, the first run also shows a setup checklist (overlay, speech-to-text, its language, text-to-speech, wake word, computer-use approvals, camera gestures). Every missing step comes with the exact command and a **Copy** button; nothing is installed or changed for you. Open it any time with `/hermis setup`. |

Voice, the "hey hermes" wake word and computer use all come from Hermes itself. This plugin does not reimplement them.

## Requirements

- **Windows 10/11** (the window manager uses Win32; other platforms load the plugin but `layout_windows` / `launch_app` return `unsupported_platform`).
- **Hermes Agent ≥ 0.22**.
- **Stable Node.js 22.12.0+ and npm** on `PATH`, for the pinned overlay dependencies.
- Optional, for the full experience: Hermes voice mode (`/voice on`) and wake word (`/wake on`).

## Install

```bash
hermes plugins install hermis
```

Or from source:

```bash
git clone https://github.com/gabogabucho/H.E.R.M.I.S
hermes plugins validate ./H.E.R.M.I.S --install-deps
```

Then, inside Hermes:

```
/hermis check
/hermis on
```

The first time Autopilot turns on, the plugin runs `npm ci` in `overlay/` (this downloads Electron, about 100 MB) and then starts the overlay. Later starts are instant. If something fails, look at `overlay.log` in the plugin data directory.

`/hermis check`, the setup checklist and automatic launch use the same runtime check: Node and npm must be on `PATH`, and `node --version` must report a compatible stable version within five seconds. An unsupported or unverifiable version prevents automatic installation/launch; it does not install or upgrade Node for you. After installing Node, restart the Hermes gateway so it sees the updated `PATH`. A compatible runtime is not proof that Electron or voice is connected.

## Configuration

### Recovering overlay startup

Use `/hermis status` or `/hermis check` to inspect local bootstrap progress: `installing`, `starting`, `failed` or `connected`. Starting a process is not a successful connection. After 30 seconds without an observed local overlay connection, diagnostics report `startup_timeout`; they do not kill the process. Setup also displays active startup or failure details. Diagnostics are snapshots: refresh setup or run the command again to update them.

If startup failed, run `/hermis retry`. This retries the overlay without toggling Autopilot, clearing surfaces or consuming the welcome. An active install or live npm wrapper in this Hermes process blocks duplicate retries. A failed install releases its local cooldown; a failed launch can reinstall pinned dependencies on explicit retry. No dependency folders need to be deleted manually. `HERMIS_OVERLAY_AUTOSTART=0` also disables retry.

Failure details use fixed error codes and numeric exit codes, not raw npm output, exception messages or session tokens. `overlay.log` remains a separate troubleshooting log; review it privately before sharing it.

**Scope:** connection status remains process-local. Cooperating Hermes hosts sharing the same overlay installation now use a nonblocking native lock for installation and the owned npm startup wrapper's lifetime. A competing host reports `busy` instead of starting another worker; retry after the owner finishes. The lock identity file, `overlay/.hermis-bootstrap.lock`, must not be deleted to force a retry. It is not a PID/timestamp lock: ownership is a held OS handle, not file presence.

This does not certify cleanup of npm descendants after timeout or host termination, network-filesystem locking, manual npm commands, or the real Windows lifecycle. A connection owned by another host remains unverified here. A live wrapper with no connection is deliberately not killed or duplicated; close it intentionally before retrying. Do not repeat `/hermis on` to recover startup: reactivating an already active mode retains its existing surface-clearing behavior.

| Variable | Default | Effect |
|---|---|---|
| `HERMIS_OVERLAY_AUTOSTART` | `1` | Set to `0` to never launch the overlay automatically. You can still start it by hand with `npm start -- --data-dir <plugin data dir>` inside `overlay/`. |

## Disclosure

Everything the plugin does outside of plain Python tool calls:

**Background processes**
- Installation checks and automatic overlay launch run `node --version` as a bounded, read-only subprocess. They do not run npm or change dependencies merely to check the runtime.
- A daemon thread in the Hermes process runs a WebSocket server bound to **127.0.0.1 only**, on an ephemeral port, protected by a per-session token. Only the overlay connects to it.
- When Autopilot turns on (or on the first surface drawn with no overlay connected), the plugin starts the Electron overlay as a **detached background process** via `npm start`. On the first run it runs `npm ci` first. Disable with `HERMIS_OVERLAY_AUTOSTART=0`.
- `launch_app` starts the requested app as a detached process. It never uses `shell=True`.

**Network**
- `npm ci` (first run only) downloads the pinned overlay dependencies from the npm registry, including the Electron binary. Nothing binary is committed to this repo.
- Camera gestures (optional, off by default) download the MediaPipe gesture model **once** from `storage.googleapis.com` (see below).
- The overlay window can load **https images** in `image` surfaces.
- Artifact surfaces run in a sandboxed frame whose CSP allows scripts only from `cdnjs.cloudflare.com`, `cdn.jsdelivr.net` and `unpkg.com`, and blocks all other connections (`connect-src 'none'`).
- Links (`web` surfaces, links in documents) open in your **default browser** when you click them. The overlay never browses by itself.
- To animate the orb, the overlay connects to **your local Hermes gateway**: it asks the gateway's control pipe (Windows named pipe `hermes-gateway-<hash>`, or `gateway.sock` on POSIX) for its address and a short-lived session ticket under your own user identity, then opens the gateway WebSocket (`/api/ws`, by default `127.0.0.1:8642`) and only listens to `voice.status` and `wake.detected`. It sends nothing to the agent. Overrides: `HERMES_GATEWAY_WS_URL` / `HERMES_GATEWAY_URL`, `HERMES_GATEWAY_TOKEN` / `HERMES_API_TOKEN`, `HERMES_API_PORT`.
- The plugin itself makes no outbound requests.

**Camera gestures (optional)**
- Off by default. Enable with `/hermis gestures on`. The camera turns on **only** while Autopilot Mode is active, and turns off (all tracks stopped) when you leave the mode or disable gestures. A small green dot next to the orb shows when the camera is on.
- Frames are processed **locally** by MediaPipe inside the overlay process (GPU when available, CPU fallback). They are never rendered on screen, never stored and never sent anywhere. MediaPipe also tries to send usage logs to `odml.pa.googleapis.com`; the overlay's Content Security Policy blocks that request, so nothing leaves the machine.
- With surfaces on screen, gestures act on them. With **no** surfaces (or all hidden), they act on your **real windows** through Win32: fist minimizes the active window, swipe switches to the previous/next window, palm minimizes all visible windows and a second palm restores exactly those. Gestures only minimize; they never close an app. The overlay window itself is always excluded.
- The first time gestures are enabled, the overlay downloads `gesture_recognizer.task` (~8 MB, Apache-2.0) once from `storage.googleapis.com` into the plugin data directory. Nothing binary is committed to this repo.
- The model and the MediaPipe WASM reach the renderer only through a private `hermis-media://` protocol with **fixed routes** (no arbitrary file reads). The camera permission is granted only to the overlay's own page and only for **video**.

**Setup checklist** (`/hermis setup` and the first Autopilot run)
- Reads Hermes `config.yaml` **read-only** and checks whether optional engines are installed. API keys are checked only for **presence** in the process environment; their values and `.env` are never read.
- **Copy** buttons write the shown command to your clipboard. The plugin never runs these commands.
- Opening or refreshing setup does not complete the first-use welcome; the quick guide still appears when you first enable Autopilot.
- The summary distinguishes detected missing prerequisites from informational steps. No detected missing prerequisites does not verify live voice, playback or Desktop settings. Follow each step in its indicated environment, not necessarily PowerShell.

**Desktop control**
- The overlay is a transparent, always-on-top, full-screen window. Clicks pass through wherever nothing is drawn.
- `layout_windows` moves, resizes, focuses and minimizes **your real windows** via `user32`. Windows running as administrator cannot be moved (Windows UIPI).
- `launch_app` resolves apps through `PATH`, the `App Paths` registry key (read-only) and `System32`. Apps without an `.exe` there (Microsoft Store apps such as WhatsApp) are looked up in the Start menu list with `powershell.exe Get-StartApps` (read-only, cached for 10 minutes) and opened with `explorer.exe shell:AppsFolder\<app id>`; the id always comes from that system list, never from the request text.

**Agent context**
- `pre_llm_call` adds the Autopilot instructions and a cached list of open surfaces and windows to the turn. It never captures the screen.
- `post_llm_call` copies `html`/`svg` code blocks from the reply to the overlay, only while Autopilot is on.
- `pre_tool_call` / `post_tool_call` / `post_llm_call` only observe turn and tool activity to animate the orb. They never change arguments or results.

**Files** (in the Hermes plugin data directory for `hermis`)
- `state.json`: Autopilot on/off and the open surfaces.
- `overlay.json`: the current WebSocket port and session token.
- `overlay.log`: npm and overlay output.

The installation directory also contains `overlay/.hermis-bootstrap.lock`, an empty native-lock identity file shared by cooperating hosts. Checks do not create it. The launcher keeps the file in place after releasing ownership; do not remove it while another host may be running. The implementation uses Python's [Windows byte-range locking](https://docs.python.org/3/library/msvcrt.html#msvcrt.locking) or [POSIX flock](https://docs.python.org/3/library/fcntl.html#fcntl.flock).

## Architecture

```
Hermes process                              Electron overlay (detached)
┌────────────────────────────────┐          ┌──────────────────────────────┐
│ tools: autopilot, render_…,    │  WS on   │ orb + surface container      │
│        layout_windows, …       │ 127.0.0.1│ (Lumen shell)                │
│ hooks: pre/post_llm_call, …    │◄────────►│ transparent, always on top,  │
│ ws_server (daemon thread)      │  + token │ click-through                │
│ win32_windows (user32)         │          │ sandboxed artifact frames    │
└────────────────────────────────┘          └──────────────────────────────┘
```

Protocol: `x-lumen-desktop v2`, inspired by [Lumen OS](https://github.com/gabogabucho/Lumen-os) ("there are no apps, only surfaces").

## Development

```bash
python -m unittest discover -s tests      # plugin tests
cd overlay && npm ci && node dev/mock-server.js   # scripted demo server, no Hermes needed
# then, in a second terminal, run the npm start command the mock prints
```

## Known limitations

- Windows only for window management; a single monitor.
- The overlay can take a few minutes the very first time (Electron download).
- Elevated (administrator) windows cannot be arranged.

## License

[MIT](LICENSE)
