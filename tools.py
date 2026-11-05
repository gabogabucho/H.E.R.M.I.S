"""Handlers de las tools de H.E.R.M.I.S.

Reglas: firma ``(args: dict, **kwargs) -> str``, siempre devuelven JSON y
nunca levantan excepciones (el error va en el JSON).
"""
from __future__ import annotations

import json
from typing import Any

from . import ws_server

SURFACES = ("notification", "document")
LEVELS = ("info", "success", "error")


def render_surface(args: dict[str, Any], **kwargs) -> str:
    """Dibuja una superficie flotante sobre el escritorio real."""
    if not isinstance(args, dict):
        return _json({"ok": False, "error": "invalid_args",
                      "message": "args debe ser un objeto"})
    surface = args.get("surface")
    data = args.get("data")
    if surface not in SURFACES:
        return _json({"ok": False, "error": "invalid_surface",
                      "message": f"surface debe ser una de: {', '.join(SURFACES)}"})
    if not isinstance(data, dict):
        return _json({"ok": False, "error": "invalid_data",
                      "message": "data debe ser un objeto"})
    if surface == "notification":
        text = data.get("text")
        if not isinstance(text, str) or not text.strip():
            return _json({"ok": False, "error": "invalid_data",
                          "message": "notification requiere data.text (string no vacío)"})
        level = data.get("level")
        if level is not None and level not in LEVELS:
            return _json({"ok": False, "error": "invalid_data",
                          "message": f"level debe ser uno de: {', '.join(LEVELS)}"})
    elif surface == "document":
        title, body = data.get("title"), data.get("body_markdown")
        if (not isinstance(title, str) and not isinstance(body, str)) or (
            title is not None and not isinstance(title, str)
        ) or (body is not None and not isinstance(body, str)):
            return _json({"ok": False, "error": "invalid_data",
                          "message": "document requiere al menos title o body_markdown como string"})
    note: str | None = None
    try:
        delivered = ws_server.broadcast({"type": "render", "surface": surface, "data": data})
    except Exception as exc:  # el broadcast jamás rompe el turno
        delivered, note = 0, f"broadcast falló: {exc}"
    out: dict[str, Any] = {"ok": True, "surface": surface, "delivered": delivered,
                           "overlay_connected": delivered > 0}
    out["note"] = note or ("overlay no conectado: la superficie no se dibujó"
                           if delivered == 0 else None)
    return _json({k: v for k, v in out.items() if v is not None})


def _json(obj: dict[str, Any]) -> str:
    return json.dumps(obj, ensure_ascii=False)
