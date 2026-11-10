"""Handlers de las tools y hooks de H.E.R.M.I.S (Día 2).

Reglas: firma ``(args: dict, **kwargs) -> str`` en tools, siempre devuelven JSON
y nunca levantan excepciones (el error va en el JSON). El hook ``pre_llm_call``
acepta ``**kwargs`` y lee únicamente el cache local ``state.json``.
"""
from __future__ import annotations

import functools
import json
import logging
from typing import Any, Callable

from . import overlay_launcher
from . import setup_checks
from . import welcome
from . import win32_windows
from . import ws_server
from . import orb_lifecycle

SURFACES = (
    "notification",
    "document",
    "email_list",
    "table",
    "cards",
    "web",
    "image",
    "artifact",
)
LEVELS = ("info", "success", "error")
MAX_ARTIFACT_BYTES = 256 * 1024

logger = logging.getLogger("hermis")
SETUP_ID = "hermis-setup"


def _setup_entry() -> dict[str, Any]:
    return {"id": SETUP_ID, "surface": "setup", "data": setup_checks.surface_data()}


def show_tour() -> dict[str, Any]:
    """/hermis tour: vuelve a dibujar la guía rápida y Hermes la explica en el próximo turno."""
    st = ws_server.load_state()
    entry = welcome.entry(bool(st.get("gestures")))
    st.setdefault("surfaces", {})[entry["id"]] = entry
    st["tour_pending"] = True
    ws_server.save_state(st)
    delivered, note = _safe_broadcast({"type": "render", "surface": entry["surface"], "id": entry["id"],
                                       "data": entry["data"]})
    launch_note = _maybe_start_overlay(delivered)
    return {"delivered": delivered, "note": launch_note or note}


def show_setup() -> dict[str, Any]:
    """Dibuja (o actualiza) el checklist de configuración; lo usan /hermis setup y 'Volver a revisar'."""
    entry = _setup_entry()
    st = ws_server.load_state()
    st.setdefault("surfaces", {})[SETUP_ID] = entry
    st["onboarded"] = True
    ws_server.save_state(st)
    delivered, note = _safe_broadcast({"type": "render", "surface": "setup", "id": SETUP_ID, "data": entry["data"]})
    launch_note = _maybe_start_overlay(delivered)
    return {"delivered": delivered, "note": launch_note or note}


def _always_json(handler: Callable[..., str]) -> Callable[..., str]:
    """Cumple el contrato del módulo: un fallo inesperado (disco, Win32) vuelve como JSON."""
    @functools.wraps(handler)
    def wrapper(*args: Any, **kwargs: Any) -> str:
        try:
            return handler(*args, **kwargs)
        except Exception as exc:
            logger.exception("tool %s falló", handler.__name__)
            return _json({"ok": False, "error": "internal_error",
                          "message": f"{type(exc).__name__}: {exc}"})
    return wrapper


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
    elif surface == "artifact":
        if data.get("kind") not in ("html", "svg"):
            return "artifact requiere data.kind ('html' o 'svg')"
        content = data.get("content")
        if not _non_empty_str(content):
            return "artifact requiere data.content (string no vacío)"
        if len(str(content).encode("utf-8")) > MAX_ARTIFACT_BYTES:
            return (f"artifact content supera el máximo de {MAX_ARTIFACT_BYTES // 1024} KB; "
                    "reduci el gráfico o dividilo en varias superficies")
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


def _refresh_windows_cache(st: dict[str, Any]) -> None:
    """Actualiza el listado de ventanas visibles en el diccionario de estado."""
    try:
        titles = [w["title"] for w in win32_windows.list_open_windows()[:15] if isinstance(w.get("title"), str)]
        if titles:
            st["windows"] = titles
    except Exception:
        pass


@_always_json
def autopilot(args: dict[str, Any], **kwargs: Any) -> str:
    """Activa o desactiva el Modo Piloto Automático y persiste el estado."""
    if not isinstance(args, dict):
        return _json({"ok": False, "error": "invalid_args", "message": "args debe ser un objeto"})
    state = args.get("state")
    if state not in ("on", "off"):
        return _json({"ok": False, "error": "invalid_state", "message": "state debe ser 'on' u 'off'"})
    active = state == "on"
    st = ws_server.load_state()
    was_active = bool(st.get("autopilot"))
    st["autopilot"] = active
    first_run = active and not st.get("onboarded")
    # Salir siempre limpia. Entrar limpia solo si el modo YA estaba activo: son
    # superficies de una sesión anterior (se cerró Hermes sin salir del modo). Si
    # venía apagado, lo recién dibujado es intencional (el modelo puede dibujar y
    # después activar el modo en el mismo turno) y se queda.
    clear = not active or was_active
    if clear:
        st["surfaces"] = {}
    first_surfaces: list[dict[str, Any]] = []
    if active:
        _refresh_windows_cache(st)
        if first_run:
            # Bienvenida, solo la primera vez (después, /hermis tour): guía rápida
            # en pantalla y Hermes lo explica por voz. El checklist técnico solo
            # aparece si falta algo; siempre queda /hermis setup.
            first_surfaces.append(welcome.entry(bool(st.get("gestures"))))
            setup = _setup_entry()
            if any(item.get("status") == "warn" for item in setup["data"].get("items", [])):
                first_surfaces.append(setup)
            for entry in first_surfaces:
                st.setdefault("surfaces", {})[entry["id"]] = entry
            st["onboarded"] = True
            st["tour_pending"] = True
    else:
        st.pop("windows", None)
    ws_server.save_state(st)
    orb_lifecycle.reset()
    if clear:
        # El overlay tiene que coincidir con lo que pre_llm_call le dice a Hermes.
        _safe_broadcast({"type": "close", "id": "all"})
    delivered, note = _safe_broadcast({"type": "mode", "autopilot": active})
    for entry in first_surfaces:
        _safe_broadcast({"type": "render", "surface": entry["surface"], "id": entry["id"], "data": entry["data"]})
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
        # Viaja en el resultado para que Hermes lo explique en este mismo turno.
        "welcome": welcome.voice_instruction(bool(st.get("gestures"))) if first_run else None,
    }
    return _json({k: v for k, v in out.items() if v is not None})


@_always_json
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
            existing_id = next(
                (sid for sid, entry in (st.get("surfaces") or {}).items()
                 if isinstance(entry, dict) and entry.get("surface") == surface and entry.get("data") == data),
                None,
            )
            if existing_id is not None:
                surface_id = existing_id
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


@_always_json
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


@_always_json
def gesture_window(args: dict[str, Any], **kwargs: Any) -> str:
    """Gesto sobre ventanas reales cuando no hay superficies en pantalla (no es una tool del agente)."""
    if not isinstance(args, dict) or args.get("action") not in win32_windows.GESTURE_ACTIONS:
        return _json({"ok": False, "error": "invalid_action",
                      "message": f"action debe ser una de: {', '.join(win32_windows.GESTURE_ACTIONS)}"})
    res = win32_windows.gesture_window(args["action"])
    st = ws_server.load_state()
    _refresh_windows_cache(st)  # Hermes ve qué quedó al frente en el próximo turno
    ws_server.save_state(st)
    return _json(res)


@_always_json
def set_gestures(args: dict[str, Any], **kwargs: Any) -> str:
    """Activa o desactiva los gestos con cámara (opcional, apagados por defecto).

    Solo persiste el flag y avisa al overlay: la cámara la prende el overlay,
    y solo cuando el modo piloto también está activo.
    """
    if not isinstance(args, dict):
        return _json({"ok": False, "error": "invalid_args", "message": "args debe ser un objeto"})
    enabled = args.get("enabled")
    if not isinstance(enabled, bool):
        return _json({"ok": False, "error": "invalid_enabled", "message": "enabled debe ser true o false"})
    st = ws_server.load_state()
    st["gestures"] = enabled
    ws_server.save_state(st)
    delivered, note = _safe_broadcast({"type": "gestures", "enabled": enabled})
    out: dict[str, Any] = {
        "ok": True,
        "gestures": enabled,
        "delivered": delivered,
        "overlay_connected": delivered > 0,
        "note": note,
    }
    return _json({k: v for k, v in out.items() if v is not None})


@_always_json
def list_surfaces(args: dict[str, Any] | None = None, **kwargs: Any) -> str:
    """Devuelve el estado de autopilot y las superficies activas."""
    st = ws_server.load_state()
    surfaces = list((st.get("surfaces") or {}).values())
    return _json({
        "ok": True,
        "autopilot": bool(st.get("autopilot", False)),
        "surfaces": surfaces,
    })


@_always_json
def layout_windows(args: dict[str, Any], **kwargs: Any) -> str:
    """Acomoda, enfoca o maximiza ventanas reales del escritorio de Windows."""
    if not isinstance(args, dict):
        return _json({"ok": False, "error": "invalid_args", "message": "args debe ser un objeto"})
    layout = args.get("layout")
    windows = args.get("windows")
    if layout not in win32_windows.LAYOUTS:
        return _json({
            "ok": False,
            "error": "invalid_layout",
            "message": f"layout debe ser uno de: {', '.join(win32_windows.LAYOUTS)}",
        })
    if not isinstance(windows, list) or not windows or not all(_non_empty_str(w) for w in windows):
        return _json({
            "ok": False,
            "error": "invalid_windows",
            "message": "windows debe ser una lista no vacía de nombres o títulos de ventana",
        })
    queries = [str(w).strip() for w in windows]
    res = win32_windows.apply_layout(layout, queries)
    st = ws_server.load_state()
    _refresh_windows_cache(st)
    ws_server.save_state(st)
    return _json(res)


@_always_json
def launch_app(args: dict[str, Any], **kwargs: Any) -> str:
    """Abre una aplicación de escritorio por nombre o alias sin usar shell."""
    if not isinstance(args, dict):
        return _json({"ok": False, "error": "invalid_args", "message": "args debe ser un objeto"})
    app = args.get("app")
    if not _non_empty_str(app):
        return _json({"ok": False, "error": "invalid_app", "message": "app debe ser un string no vacío"})
    raw_args = args.get("args")
    if raw_args is not None and (not isinstance(raw_args, list) or not all(isinstance(a, str) for a in raw_args)):
        return _json({"ok": False, "error": "invalid_args_list", "message": "args debe ser una lista de strings"})
    res = win32_windows.launch_application(str(app).strip(), raw_args)
    st = ws_server.load_state()
    _refresh_windows_cache(st)
    ws_server.save_state(st)
    return _json(res)


def pre_llm_call(**kwargs: Any) -> dict[str, str] | None:
    """Inyecta instrucciones del Modo Piloto Automático y contexto de superficies y ventanas abiertas."""
    orb_lifecycle.pre_llm_call(**kwargs)
    st = ws_server.load_state()
    autopilot_on = bool(st.get("autopilot", False))
    surfaces: dict[str, Any] = st.get("surfaces") or {}
    windows: list[str] = st.get("windows") if isinstance(st.get("windows"), list) else []
    if not autopilot_on and not surfaces:
        return None

    lines: list[str] = []
    if autopilot_on:
        lines.append(
            "[H.E.R.M.I.S — Modo Piloto Automático ACTIVO / Autopilot Mode ACTIVE]\n"
            "- Idioma / Language: responde siempre en el mismo idioma que use el usuario "
            "(si es español, usa español neutro sin modismos regionales ni voseo; if English or another language, reply in that language).\n"
            "- Voz / Voice: responde en 1 o 2 frases cortas pensadas para ser habladas; no leas listas ni markdown en voz alta.\n"
            "- Mostrar / Show: todo lo que el usuario pida VER se muestra con `render_surface`, eligiendo la superficie "
            "por el TIPO de dato, sin importar de dónde viene: mensajes o correos → email_list; filas y columnas → table; "
            "ítems → cards; texto largo → document; una página web → web; una imagen → image; un aviso corto → notification.\n"
            "- Artefactos / Artifacts: si necesitas un gráfico, un diagrama o un dashboard, escribe un bloque ```html o ```svg "
            "como ya sabes hacer y aparecerá solo en pantalla; también puedes mandarlo directo con `render_surface` "
            "surface='artifact' (data={kind: 'html'|'svg', title, content}).\n"
            "- Contexto / Context: pedidos como 'abre el tercero' o 'cierra eso' se resuelven con lo que ya está en pantalla "
            "(listado abajo) y con `close_surface`, sin volver a consultar nada.\n"
            "- Ventanas / Windows: para abrir, enfocar o acomodar apps usa SIEMPRE `launch_app` y `layout_windows`, "
            "una llamada por acción; nunca terminal, execute_code ni el navegador para eso. `launch_app` abre "
            "cualquier app del menú Inicio por su nombre (también las de la Microsoft Store). Para abrir una web, "
            "`launch_app` con el navegador y la URL que haga falta como argumento. "
            "Para dividir pantalla: `layout_windows` layout='split' con los nombres de las apps.\n"
            "- Dentro de una app / Inside an app: para escribir o usar el teclado en una app ya abierta, usa tus "
            "herramientas de computer use. Antes de ENVIAR un mensaje a otra persona, confirma el texto por voz.\n"
            "- Transparencia y tema / Opacity & theme: si el usuario pide subir/bajar la transparencia (opacidad) del fondo o cambiar entre modo claro y oscuro, "
            "llama a `render_surface` con `surface='notification'` y `data={'text': '...', 'level': 'info', 'opacity': <20..98>, 'theme': 'light'|'dark'} "
            "(20 = muy traslúcido, 84 = normal, 96 = casi sólido)."
        )
        if st.get("tour_pending"):
            # Bienvenida activada con /hermis on o /hermis tour (sin pasar por la tool).
            lines.append("[Bienvenida / Welcome] " + welcome.voice_instruction(bool(st.get("gestures"))))
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
    if windows:
        lines.append("[Ventanas del escritorio en caché]")
        for wtitle in windows[:15]:
            lines.append(f"- {wtitle}")
    return {"context": "\n".join(lines)}


def _json(obj: dict[str, Any]) -> str:
    return json.dumps(obj, ensure_ascii=False)
