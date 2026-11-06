"""Handlers de las tools y hooks de H.E.R.M.I.S (Día 2).

Reglas: firma ``(args: dict, **kwargs) -> str`` en tools, siempre devuelven JSON
y nunca levantan excepciones (el error va en el JSON). El hook ``pre_llm_call``
acepta ``**kwargs`` y lee únicamente el cache local ``state.json``.
"""
from __future__ import annotations

import json
from typing import Any

from . import overlay_launcher
from . import ws_server

SURFACES = (
    "notification",
    "document",
    "email_list",
    "table",
    "cards",
    "web",
    "image",
    "custom",
)
LEVELS = ("info", "success", "error")


def _non_empty_str(val: Any) -> bool:
    return isinstance(val, str) and bool(val.strip())


def _opt_str(val: Any) -> bool:
    return val is None or isinstance(val, str)


def _validate_surface_data(surface: str, data: dict[str, Any]) -> str | None:
    """Devuelve mensaje de error si data no cumple el contrato de la superficie, o None."""
    if not _opt_str(data.get("title")):
        return "title debe ser un string"
    if surface == "notification":
        if not _non_empty_str(data.get("text")):
            return "notification requiere data.text (string no vacío)"
        level = data.get("level")
        if level is not None and level not in LEVELS:
            return f"level debe ser uno de: {', '.join(LEVELS)}"
    elif surface == "document":
        title, body = data.get("title"), data.get("body_markdown")
        if (not isinstance(title, str) and not isinstance(body, str)) or not _opt_str(body):
            return "document requiere al menos title o body_markdown como string"
    elif surface == "email_list":
        items = data.get("items")
        if not isinstance(items, list) or not items:
            return "email_list requiere data.items (lista no vacía de correos)"
        for item in items:
            if not isinstance(item, dict) or not (
                _non_empty_str(item.get("from")) or _non_empty_str(item.get("subject"))
            ):
                return "cada correo en email_list requiere al menos 'from' o 'subject' (string no vacío)"
    elif surface == "table":
        cols, rows = data.get("columns"), data.get("rows")
        if not isinstance(cols, list) or not cols or not all(_non_empty_str(c) for c in cols):
            return "table requiere data.columns (lista no vacía de strings)"
        if not isinstance(rows, list) or not all(isinstance(r, (list, dict)) for r in rows):
            return "table requiere data.rows (lista de filas)"
    elif surface == "cards":
        items = data.get("items")
        if not isinstance(items, list) or not items or not all(isinstance(i, dict) and bool(i) for i in items):
            return "cards requiere data.items (lista no vacía de objetos)"
    elif surface == "web":
        url = data.get("url")
        if not _non_empty_str(url) or not str(url).startswith(("http://", "https://")):
            return "web requiere data.url con http:// o https://"
    elif surface == "image":
        if not (_non_empty_str(data.get("src")) or _non_empty_str(data.get("url"))):
            return "image requiere data.src o data.url (string no vacío)"
        if not _opt_str(data.get("alt")):
            return "image alt debe ser un string"
    elif surface == "custom":
        if not _non_empty_str(data.get("html")):
            return "custom requiere data.html (string no vacío)"
    return None


def _safe_broadcast(payload: dict[str, Any]) -> tuple[int, str | None]:
    try:
        delivered = ws_server.broadcast(payload)
        note = "overlay no conectado: la superficie no se dibujó" if delivered == 0 else None
        return delivered, note
    except Exception as exc:
        return 0, f"broadcast falló: {exc}"


def _maybe_start_overlay(delivered: int) -> str | None:
    """Sin overlay conectado, intenta abrirlo (una vez por cooldown)."""
    if delivered > 0:
        return None
    try:
        return overlay_launcher.ensure_overlay_running()
    except Exception as exc:
        return f"no se pudo abrir el overlay: {exc}"


def autopilot(args: dict[str, Any], **kwargs: Any) -> str:
    """Activa o desactiva el Modo Piloto Automático y persiste el estado."""
    if not isinstance(args, dict):
        return _json({"ok": False, "error": "invalid_args", "message": "args debe ser un objeto"})
    state = args.get("state")
    if state not in ("on", "off"):
        return _json({"ok": False, "error": "invalid_state", "message": "state debe ser 'on' u 'off'"})
    active = state == "on"
    st = ws_server.load_state()
    st["autopilot"] = active
    if not active:
        st["surfaces"] = {}
    ws_server.save_state(st)
    delivered, note = _safe_broadcast({"type": "mode", "autopilot": active})
    if active:
        launch_note = _maybe_start_overlay(delivered)
        if launch_note:
            note = launch_note
    out: dict[str, Any] = {
        "ok": True,
        "state": state,
        "autopilot": active,
        "delivered": delivered,
        "overlay_connected": delivered > 0,
        "note": note,
    }
    return _json({k: v for k, v in out.items() if v is not None})


def render_surface(args: dict[str, Any], **kwargs: Any) -> str:
    """Dibuja una superficie flotante sobre el escritorio real."""
    if not isinstance(args, dict):
        return _json({"ok": False, "error": "invalid_args", "message": "args debe ser un objeto"})
    surface = args.get("surface")
    data = args.get("data")
    raw_id = args.get("id")
    if surface not in SURFACES:
        return _json({"ok": False, "error": "invalid_surface",
                      "message": f"surface debe ser una de: {', '.join(SURFACES)}"})
    if not isinstance(data, dict):
        return _json({"ok": False, "error": "invalid_data", "message": "data debe ser un objeto"})
    if raw_id is not None and not _non_empty_str(raw_id):
        return _json({"ok": False, "error": "invalid_id", "message": "id debe ser un string no vacío"})
    err = _validate_surface_data(surface, data)
    if err is not None:
        return _json({"ok": False, "error": "invalid_data", "message": err})

    surface_id: str | None = None
    msg: dict[str, Any] = {"type": "render", "surface": surface, "data": data}
    if surface != "notification":
        st = ws_server.load_state()
        if isinstance(raw_id, str):
            surface_id = raw_id.strip()
        else:
            st["seq"] = int(st.get("seq", 0)) + 1
            surface_id = f"{surface}-{st['seq']}"
        st.setdefault("surfaces", {})[surface_id] = {
            "id": surface_id,
            "surface": surface,
            "data": data,
        }
        ws_server.save_state(st)
        msg["id"] = surface_id

    delivered, note = _safe_broadcast(msg)
    launch_note = _maybe_start_overlay(delivered)
    if launch_note:
        note = launch_note
    out: dict[str, Any] = {
        "ok": True,
        "id": surface_id,
        "surface": surface,
        "delivered": delivered,
        "overlay_connected": delivered > 0,
        "note": note,
    }
    return _json({k: v for k, v in out.items() if v is not None})


def close_surface(args: dict[str, Any], **kwargs: Any) -> str:
    """Cierra una superficie activa por id o todas con id='all'."""
    if not isinstance(args, dict):
        return _json({"ok": False, "error": "invalid_args", "message": "args debe ser un objeto"})
    target_id = args.get("id")
    if not _non_empty_str(target_id):
        return _json({"ok": False, "error": "invalid_id", "message": "id debe ser un string no vacío"})
    target_id = str(target_id).strip()
    st = ws_server.load_state()
    surfaces: dict[str, Any] = st.get("surfaces") or {}
    if target_id == "all":
        closed = list(surfaces.keys())
        st["surfaces"] = {}
    else:
        closed = [target_id] if surfaces.pop(target_id, None) is not None else []
        st["surfaces"] = surfaces
    ws_server.save_state(st)
    delivered, note = _safe_broadcast({"type": "close", "id": target_id})
    launch_note = _maybe_start_overlay(delivered)
    if launch_note:
        note = launch_note
    out: dict[str, Any] = {
        "ok": True,
        "id": target_id,
        "closed": closed,
        "delivered": delivered,
        "overlay_connected": delivered > 0,
        "note": note,
    }
    return _json({k: v for k, v in out.items() if v is not None})


def list_surfaces(args: dict[str, Any] | None = None, **kwargs: Any) -> str:
    """Devuelve el estado de autopilot y las superficies activas."""
    st = ws_server.load_state()
    surfaces = list((st.get("surfaces") or {}).values())
    return _json({
        "ok": True,
        "autopilot": bool(st.get("autopilot", False)),
        "surfaces": surfaces,
    })


def pre_llm_call(**kwargs: Any) -> dict[str, str] | None:
    """Inyecta instrucciones del Modo Piloto Automático y contexto de superficies abiertas."""
    st = ws_server.load_state()
    autopilot_on = bool(st.get("autopilot", False))
    surfaces: dict[str, Any] = st.get("surfaces") or {}
    if not autopilot_on and not surfaces:
        return None

    lines: list[str] = []
    if autopilot_on:
        lines.append(
            "[H.E.R.M.I.S — Modo Piloto Automático ACTIVO]\n"
            "- Respondé en 1–2 frases cortas para ser habladas por voz (no leas listas ni markdown en voz alta).\n"
            "- Todo contenido visual (correos, documentos, tablas, tarjetas, web, imágenes) mostralo con `render_surface`."
        )
    if surfaces:
        lines.append("[Superficies abiertas en pantalla]")
        for sid, entry in surfaces.items():
            surf = entry.get("surface", "unknown")
            data = entry.get("data") if isinstance(entry.get("data"), dict) else {}
            title = data.get("title")
            header = f"- id={sid} surface={surf}" + (f" title={title!r}" if title else "")
            lines.append(header)
            if surf == "email_list" and isinstance(data.get("items"), list):
                for idx, item in enumerate(data["items"], 1):
                    if isinstance(item, dict):
                        sender = item.get("from", "")
                        subj = item.get("subject", "")
                        body = item.get("body_markdown") or item.get("snippet") or ""
                        lines.append(f"  #{idx} de={sender!r} asunto={subj!r} texto={str(body)[:200]!r}")
    return {"context": "\n".join(lines)}


def _json(obj: dict[str, Any]) -> str:
    return json.dumps(obj, ensure_ascii=False)
