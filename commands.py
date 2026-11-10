"""In-session controls that reuse the existing autopilot tool."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from . import overlay_launcher, setup_checks, tools, ws_server

USAGE = "Usage: /hermis [status|on|off|check|setup|retry|tour|gestures on|off]"


def handle(raw_args: str = "") -> str:
    """Return status, switch the mode, inspect local prerequisites, or show the setup checklist."""
    parts = raw_args.strip().lower().split()
    action = parts[0] if parts else "status"
    if action not in {"status", "on", "off", "check", "setup", "retry", "tour", "gestures"}:
        return USAGE
    if action == "gestures":
        if len(parts) != 2 or parts[1] not in ("on", "off"):
            return USAGE
    elif len(parts) > 1:
        return USAGE
    if action == "retry":
        note = overlay_launcher.ensure_overlay_running(retry=True)
        return f"Overlay startup: {overlay_launcher.bootstrap_summary()}" + (f"\n{note}" if note else "")
    if action == "gestures":
        # Toggle opcional (apagado por defecto): persiste el flag y avisa al overlay.
        state = parts[1]
        result = json.loads(tools.set_gestures({"enabled": state == "on"}))
        if not result.get("ok"):
            return "Gestures change failed. Check the local plugin logs."
        connection = "connected" if result.get("overlay_connected") else "not connected"
        return f"Gestures: {state}\nOverlay: {connection}"
    if action == "tour":
        # Repite la bienvenida: guía rápida en pantalla y Hermes la explica en el próximo turno.
        try:
            shown = tools.show_tour()
            where = ("The quick guide is on screen." if shown.get("delivered")
                     else str(shown.get("note") or "The overlay will show it when it starts."))
        except Exception:
            where = "Could not draw the guide in the overlay."
        return f"H.E.R.M.I.S tour: Hermes will explain Autopilot Mode on your next message.\n{where}"
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
        f"Gestures: {'on' if state.get('gestures') else 'off'}",
        "Overlay connection: not checked across processes (local startup status below).",
        f"Overlay startup: {overlay_launcher.bootstrap_summary()}",
    ]
    if action == "check":
        dependencies = Path(__file__).parent / "overlay" / "node_modules"
        runtime = overlay_launcher.runtime_status()
        lines.extend([
            "Read-only installation check; not an end-to-end test.",
            f"Windows desktop: {'available' if sys.platform == 'win32' else 'unavailable on this OS'}",
            f"Node.js: {(runtime['version'] or 'found (version not verified)') if runtime['node'] else 'missing'}",
            f"npm: {'found' if runtime['npm'] else 'missing'}",
            f"Overlay runtime: {runtime['error'] or ('compatible; requires Node.js >= ' + overlay_launcher.NODE_REQUIREMENT)}",
            f"Overlay dependencies: {'directory present (not validated)' if dependencies.is_dir() else 'not installed'}",
            "Voice: not verified; check voice mode in Hermes.",
            "Wake word: not verified; check wake-word settings in Hermes.",
            "Computer use: not verified; run hermes computer-use doctor on Windows.",
        ])
    return "\n".join(lines)
