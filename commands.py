"""In-session controls that reuse the existing autopilot tool."""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

from . import setup_checks, tools, ws_server

USAGE = "Usage: /hermis [status|on|off|check|setup]"


def handle(raw_args: str = "") -> str:
    """Return status, switch the mode, inspect local prerequisites, or show the setup checklist."""
    action = raw_args.strip().lower() or "status"
    if action not in {"status", "on", "off", "check", "setup"}:
        return USAGE
    if action == "setup":
        # Mismo checklist en el chat y en el overlay (con botones Copiar).
        try:
            shown = tools.show_setup()
            where = ("Also on screen in the overlay." if shown.get("delivered")
                     else str(shown.get("note") or "The overlay will show it when it starts."))
        except Exception:
            where = "Could not draw it in the overlay."
        return f"H.E.R.M.I.S setup (read-only; copy and run what is missing):\n{setup_checks.as_text()}\n{where}"
    if action in {"on", "off"}:
        result = json.loads(tools.autopilot({"state": action}))
        if not result.get("ok"):
            return "Autopilot change failed. Check the local plugin logs."
        connection = "connected" if result.get("overlay_connected") else "not connected"
        lines = [f"Autopilot: {action}", f"Overlay: {connection}"]
        if result.get("note"):
            lines.append(str(result["note"]))
        return "\n".join(lines)
    state = ws_server.load_state()
    lines = [
        f"Autopilot: {'on' if state.get('autopilot') else 'off'}",
        f"Surfaces: {len(state.get('surfaces') or {})}",
        "Overlay connection: not checked (read-only status).",
    ]
    if action == "check":
        dependencies = Path(__file__).parent / "overlay" / "node_modules"
        lines.extend([
            "Read-only installation check; not an end-to-end test.",
            f"Windows desktop: {'available' if sys.platform == 'win32' else 'unavailable on this OS'}",
            f"Node.js: {'found (version not checked; requires 20+)' if shutil.which('node') else 'missing'}",
            f"npm: {'found' if shutil.which('npm') else 'missing'}",
            f"Overlay dependencies: {'directory present (not validated)' if dependencies.is_dir() else 'not installed'}",
            "Voice: not verified; check voice mode in Hermes.",
            "Wake word: not verified; check wake-word settings in Hermes.",
            "Computer use: not verified; run hermes computer-use doctor on Windows.",
        ])
    return "\n".join(lines)
