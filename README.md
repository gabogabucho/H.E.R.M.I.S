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
| **`/hermis`** | `/hermis status`, `/hermis on`, `/hermis off`, `/hermis check` (read-only installation check), `/hermis setup` (setup checklist). |
| **Onboarding** | The first time Autopilot turns on, the overlay shows a setup checklist (overlay, speech-to-text, its language, text-to-speech, wake word, computer-use approvals). Every missing step comes with the exact command and a **Copy** button; nothing is installed or changed for you. Reopen it any time with `/hermis setup`. |

Voice, the "hey hermes" wake word and computer use all come from Hermes itself. This plugin does not reimplement them.

## Requirements

- **Windows 10/11** (the window manager uses Win32; other platforms load the plugin but `layout_windows` / `launch_app` return `unsupported_platform`).
- **Hermes Agent ≥ 0.22**.
- **Node.js 20+ and npm** on `PATH`, for the overlay.
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

## Configuration

| Variable | Default | Effect |
|---|---|---|
| `HERMIS_OVERLAY_AUTOSTART` | `1` | Set to `0` to never launch the overlay automatically. You can still start it by hand with `npm start -- --data-dir <plugin data dir>` inside `overlay/`. |

## Disclosure

Everything the plugin does outside of plain Python tool calls:

**Background processes**
- A daemon thread in the Hermes process runs a WebSocket server bound to **127.0.0.1 only**, on an ephemeral port, protected by a per-session token. Only the overlay connects to it.
- When Autopilot turns on (or on the first surface drawn with no overlay connected), the plugin starts the Electron overlay as a **detached background process** via `npm start`. On the first run it runs `npm ci` first. Disable with `HERMIS_OVERLAY_AUTOSTART=0`.
- `launch_app` starts the requested app as a detached process. It never uses `shell=True`.

**Network**
- `npm ci` (first run only) downloads the pinned overlay dependencies from the npm registry, including the Electron binary. Nothing binary is committed to this repo.
- The overlay window can load **https images** in `image` surfaces.
- Artifact surfaces run in a sandboxed frame whose CSP allows scripts only from `cdnjs.cloudflare.com`, `cdn.jsdelivr.net` and `unpkg.com`, and blocks all other connections (`connect-src 'none'`).
- Links (`web` surfaces, links in documents) open in your **default browser** when you click them. The overlay never browses by itself.
- To animate the orb, the overlay connects to **your local Hermes gateway**: it asks the gateway's control pipe (Windows named pipe `hermes-gateway-<hash>`, or `gateway.sock` on POSIX) for its address and a short-lived session ticket under your own user identity, then opens the gateway WebSocket (`/api/ws`, by default `127.0.0.1:8642`) and only listens to `voice.status` and `wake.detected`. It sends nothing to the agent. Overrides: `HERMES_GATEWAY_WS_URL` / `HERMES_GATEWAY_URL`, `HERMES_GATEWAY_TOKEN` / `HERMES_API_TOKEN`, `HERMES_API_PORT`.
- The plugin itself makes no outbound requests.

**Setup checklist** (`/hermis setup` and the first Autopilot run)
- Reads Hermes `config.yaml` **read-only** and checks whether optional engines are installed. API keys are checked only for **presence** in the process environment; their values and `.env` are never read.
- **Copy** buttons write the shown command to your clipboard. The plugin never runs these commands.

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
