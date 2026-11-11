"""In-session controls that reuse the existing autopilot tool.

Todos los textos salen del catálogo (messages/*.json): el chat y el overlay
hablan el mismo idioma, el que se puede cambiar con ``/hermis lang es|en``.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from . import i18n, overlay_launcher, setup_checks, tools, ws_server

USAGE_KEY = "commands.usage"


def _usage(loc: str) -> str:
    return i18n.t(USAGE_KEY, loc)


def _lang(parts: list[str], loc: str) -> str:
    """`/hermis lang`, `/hermis lang es|en`, `/hermis lang reset`."""
    if len(parts) == 1:
        return i18n.t("commands.lang.current", loc, lang=loc)
    arg = parts[1]
    if arg == "reset":
        effective = ws_server.set_locale(None)
        return i18n.t("commands.lang.reset", effective, lang=effective)
    target = i18n.normalize_locale(arg)
    if not target:
        return (i18n.t("commands.lang.unknown", loc, arg=arg) + "\n"
                + i18n.t("commands.lang.supported", loc))
    effective = ws_server.set_locale(target)
    return i18n.t("commands.lang.set", effective, lang=effective)


def handle(raw_args: str = "") -> str:
    """Return status, switch the mode, inspect local prerequisites, or show the setup checklist."""
    parts = raw_args.strip().lower().split()
    action = parts[0] if parts else "status"
    loc = i18n.get_locale()
    if action not in {"status", "on", "off", "check", "setup", "retry", "tour", "gestures", "lang"}:
        return _usage(loc)
    if action == "gestures":
        if len(parts) != 2 or parts[1] not in ("on", "off"):
            return _usage(loc)
    elif action == "lang":
        if len(parts) > 2:
            return _usage(loc)
    elif len(parts) > 1:
        return _usage(loc)
    if action == "lang":
        return _lang(parts, loc)
    if action == "retry":
        note = overlay_launcher.ensure_overlay_running(retry=True)
        summary = overlay_launcher.bootstrap_summary(loc)
        return i18n.t("commands.retry.startup", loc, summary=summary) + (f"\n{note}" if note else "")
    if action == "gestures":
        # Toggle opcional (apagado por defecto): persiste el flag y avisa al overlay.
        state = parts[1]
        result = json.loads(tools.set_gestures({"enabled": state == "on"}))
        if not result.get("ok"):
            return i18n.t("commands.gestures.failed", loc)
        connection = (i18n.t("commands.overlay.connected", loc) if result.get("overlay_connected")
                      else i18n.t("commands.overlay.not_connected", loc))
        state_label = i18n.t("commands.value.on" if state == "on" else "commands.value.off", loc)
        return f"{i18n.t('commands.gestures.state', loc, state=state_label)}\nOverlay: {connection}"
    if action == "tour":
        # Repite la bienvenida: guía rápida en pantalla y Hermes la explica en el próximo turno.
        try:
            shown = tools.show_tour()
            where = (i18n.t("commands.tour.where_overlay", loc) if shown.get("delivered")
                     else i18n.t("commands.tour.where_pending", loc))
        except Exception:
            where = i18n.t("commands.tour.where_failed", loc)
        return f"{i18n.t('commands.tour.header', loc)}\n{where}"
    if action == "setup":
        # Mismo checklist en el chat y en el overlay (con botones Copiar).
        try:
            shown = tools.show_setup()
            where = (i18n.t("commands.setup.where_overlay", loc) if shown.get("delivered")
                     else i18n.t("commands.setup.where_pending", loc))
        except Exception:
            where = i18n.t("commands.setup.where_failed", loc)
        checks = setup_checks.as_text(loc)
        return f"{i18n.t('commands.setup.header', loc)}\n{checks}\n{where}"
    if action in {"on", "off"}:
        result = json.loads(tools.autopilot({"state": action}))
        if not result.get("ok"):
            return i18n.t("commands.on.failed" if action == "on" else "commands.off.failed", loc)
        connection = (i18n.t("commands.overlay.connected", loc) if result.get("overlay_connected")
                      else i18n.t("commands.overlay.not_connected", loc))
        done = i18n.t("commands.on.done" if action == "on" else "commands.off.done", loc)
        lines = [done, f"Overlay: {connection}"]
        if result.get("note"):
            lines.append(str(result["note"]))
        return "\n".join(lines)
    state = ws_server.load_state()
    lines = [
        i18n.t("commands.status.autopilot_on" if state.get("autopilot") else "commands.status.autopilot_off", loc),
        i18n.t("commands.status.surfaces", loc, count=len(state.get("surfaces") or {})),
        i18n.t("commands.status.gestures_on" if state.get("gestures") else "commands.status.gestures_off", loc),
        i18n.t("commands.status.overlay_connection", loc),
        i18n.t("commands.status.overlay_startup", loc, summary=overlay_launcher.bootstrap_summary(loc)),
        i18n.t("commands.status.locale", loc, lang=loc),
    ]
    if action == "check":
        dependencies = Path(__file__).parent / "overlay" / "node_modules"
        runtime = overlay_launcher.runtime_status(loc)
        lines.extend([
            i18n.t("commands.check.header", loc),
            i18n.t("commands.check.windows_available" if sys.platform == "win32"
                   else "commands.check.windows_unavailable", loc),
            i18n.t("commands.check.node_found" if runtime["node"] else "commands.check.node_missing", loc,
                   version=runtime["version"] or i18n.t("commands.check.node_version_unverified", loc)),
            i18n.t("commands.check.npm_found" if runtime["npm"] else "commands.check.npm_missing", loc),
            i18n.t("commands.check.runtime", loc,
                   detail=runtime["error"] or i18n.t("commands.check.runtime_compatible", loc,
                                                     version=overlay_launcher.NODE_REQUIREMENT)),
            i18n.t("commands.check.dependencies_present" if dependencies.is_dir()
                   else "commands.check.dependencies_missing", loc),
            i18n.t("commands.check.voice", loc),
            i18n.t("commands.check.wake", loc),
            i18n.t("commands.check.computer_use", loc),
        ])
    return "\n".join(lines)
