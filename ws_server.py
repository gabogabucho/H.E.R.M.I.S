"""Servidor WebSocket local para el overlay Electron de H.E.R.M.I.S.

El plugin levanta un servidor WS en 127.0.0.1 (puerto efímero) con token de
una sola sesión. El overlay lee ``overlay.json`` (puerto + token, dentro del
``plugin_data_dir``) y se autentica mandando ``{"type":"hello","token":…}``
como primer mensaje: sin hello válido se cierra la conexión (4401). Todo
queda en loopback — nada escucha en interfaces externas.

Estado Día 2: ``broadcast`` (plugin → overlay) y sincronización al conectar:
cuando un overlay completa el ``hello``, recibe ``mode`` (estado de
``state.json``), ``gestures`` y un ``render`` por cada superficie activa, en
orden. Los mensajes del overlay (``setup.refresh``, ``gesture.close``,
``voice.status``…) corren fuera del loop del WS.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import secrets
import sys
import threading
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger("hermis")

_HOST = "127.0.0.1"
_HELLO_TIMEOUT_S = 10
_STARTUP_TIMEOUT_S = 10.0

_STATE: dict[str, Any] = getattr(sys, "_hermis_ws_state", None) or {
    "lock": threading.Lock(),
    "loop": None,
    "port": None,
    "data_dir_override": None,
    "clients": set(),
    "thread": None,
    "token": None,
    "ready": threading.Event(),
    "handler": None,
}
setattr(sys, "_hermis_ws_state", _STATE)
_lock: threading.Lock = _STATE["lock"]
_clients: set[Any] = _STATE["clients"]
_ready: threading.Event = _STATE["ready"]


def _data_dir(override: Path | str | None = None) -> Path:
    """Directorio de estado del plugin (sobrevive updates; sigue al perfil)."""
    if override is not None:
        return Path(override)
    try:
        from plugins.plugin_storage import plugin_data_dir
        return Path(plugin_data_dir("hermis"))
    except Exception:
        hermes_home = os.environ.get("HERMES_HOME")
        if hermes_home:
            base = Path(hermes_home)
        elif sys.platform == "win32":
            base = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local")) / "hermes"
        else:
            base = Path.home() / ".hermes"
        return base / "plugin-data" / "hermis"


def data_dir() -> Path:
    """Directorio de estado efectivo del plugin (respeta el override de start())."""
    return _data_dir(_STATE["data_dir_override"])


def _atomic_write_text(target: Path, content: str) -> None:
    """Escritura atómica tolerante a bloqueos transitorios de lectura en Windows ([WinError 5])."""
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f"{target.stem}.{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text(content, encoding="utf-8")
    for attempt in range(5):
        try:
            os.replace(tmp, target)
            return
        except PermissionError:
            if attempt < 4:
                time.sleep(0.02)
    try:
        target.write_text(content, encoding="utf-8")
    finally:
        with contextlib.suppress( OSError):
            tmp.unlink(missing_ok=True)


def _write_overlay_info(port: int, token: str, data_dir: Path | str | None = None) -> None:
    """Puerto y token de la sesión, escritura atómica; el overlay lee esto."""
    info = {"host": _HOST, "port": port, "token": token, "pid": os.getpid()}
    target = _data_dir(data_dir) / "overlay.json"
    _atomic_write_text(target, json.dumps(info))
    logger.info("overlay.json listo (puerto %s)", port)


def load_state(data_dir: Path | str | None = None) -> dict[str, Any]:
    """Lee state.json del plugin_data_dir (modo piloto automático + superficies activas)."""
    target = _data_dir(data_dir if data_dir is not None else _STATE["data_dir_override"]) / "state.json"
    with _lock:
        try:
            raw = json.loads(target.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                out: dict[str, Any] = {
                    "autopilot": bool(raw.get("autopilot", False)),
                    "seq": int(raw.get("seq", 0)),
                    "surfaces": dict(raw.get("surfaces") or {}) if isinstance(raw.get("surfaces"), dict) else {},
                    "gestures": bool(raw.get("gestures", False)),
                }
                if isinstance(raw.get("windows"), list):
                    out["windows"] = [str(w) for w in raw["windows"] if isinstance(w, str) and w.strip()]
                if raw.get("onboarded"):
                    out["onboarded"] = True
                if raw.get("tour_pending"):
                    out["tour_pending"] = True
                return out
        except Exception:
            pass
        return {"autopilot": False, "seq": 0, "surfaces": {}, "gestures": False}


def save_state(state: dict[str, Any], data_dir: Path | str | None = None) -> None:
    """Persiste state.json de forma atómica en plugin_data_dir."""
    target = _data_dir(data_dir if data_dir is not None else _STATE["data_dir_override"]) / "state.json"
    with _lock:
        _atomic_write_text(target, json.dumps(state, ensure_ascii=False))


def _handle_client_message(raw: Any) -> None:
    """Process incoming JSON messages from an authenticated overlay client."""
    try:
        msg = json.loads(raw)
    except Exception:
        return
    if not isinstance(msg, dict):
        return
    msg_type = msg.get("type")
    if msg_type == "setup.refresh":
        # Botón "Volver a revisar" del onboarding. Fuera del loop del WS: los
        # chequeos leen disco y no deben frenar la entrega de mensajes.
        def _refresh() -> None:
            with contextlib.suppress(Exception):
                from . import tools

                tools.show_setup()

        threading.Thread(target=_refresh, daemon=True, name="hermis-setup-refresh").start()
    elif msg_type == "gesture.close":
        # Gesto ✊ del overlay: cierra la superficie de adelante con la misma
        # lógica que close_surface (state.json + difusión). Fuera del loop del
        # WS, como setup.refresh: toca disco y difunde.
        surface_id = msg.get("id")
        if isinstance(surface_id, str) and surface_id.strip():
            def _close() -> None:
                with contextlib.suppress(Exception):
                    from . import tools

                    tools.close_surface({"id": surface_id.strip()})

            threading.Thread(target=_close, daemon=True, name="hermis-gesture-close").start()
    elif msg_type == "gesture.window":
        # Sin superficies en pantalla, el gesto actúa sobre ventanas reales
        # (minimizar, cambiar, escritorio). Fuera del loop: Win32 puede tardar.
        action = msg.get("action")
        if isinstance(action, str):
            def _window() -> None:
                with contextlib.suppress(Exception):
                    from . import tools

                    tools.gesture_window({"action": action})

            threading.Thread(target=_window, daemon=True, name="hermis-gesture-window").start()
    elif msg_type == "voice.status":
        with contextlib.suppress(Exception):
            from . import orb_lifecycle

            active = (
                bool(msg.get("listening"))
                if "listening" in msg
                else (str(msg.get("state") or "").lower() in ("listening", "recording"))
            )
            orb_lifecycle.set_listening(active)
    elif msg_type == "wake.detected":
        with contextlib.suppress(Exception):
            from . import orb_lifecycle

            # Sin intro: dentro del modo el wake solo pone el orbe a escuchar
            # (la intro completa ya la dispara la entrada al piloto automático).
            orb_lifecycle.set_listening(True)


async def _handler(conn: Any) -> None:
    try:
        hello = json.loads(await asyncio.wait_for(conn.recv(), _HELLO_TIMEOUT_S))
    except Exception:
        with contextlib.suppress(Exception):
            await conn.close(code=4400, reason="hello timeout o mensaje inválido")
        return
    tok = hello.get("token") if isinstance(hello, dict) else None
    expected = _STATE["token"]
    if (
        not isinstance(hello, dict)
        or hello.get("type") != "hello"
        or not isinstance(tok, str)
        or expected is None
        or not secrets.compare_digest(tok, expected)
    ):
        with contextlib.suppress(Exception):
            await conn.close(code=4401, reason="token inválido")
        return
    await conn.send(json.dumps({"type": "hello_ok"}))
    if hello.get("role") == "publisher":
        with contextlib.suppress(Exception):
            raw = await asyncio.wait_for(conn.recv(), _HELLO_TIMEOUT_S)
            msg = json.loads(raw)
            if isinstance(msg, dict) and msg.get("type") == "broadcast" and "payload" in msg:
                with _lock:
                    count = len(_clients)
                if count > 0:
                    _send_all(json.dumps(msg["payload"], ensure_ascii=False))
                await conn.send(json.dumps({"delivered": count}))
        return
    # Sincronización al conectar: el overlay recupera el estado actual (mode +
    # gestos + un render por superficie persistida, en orden) antes del stream.
    st = load_state()
    await _safe_send(conn, json.dumps({"type": "mode", "autopilot": bool(st.get("autopilot", False))}))
    await _safe_send(conn, json.dumps({"type": "gestures", "enabled": bool(st.get("gestures", False))}))
    for entry in (st.get("surfaces") or {}).values():
        if not isinstance(entry, dict) or not isinstance(entry.get("id"), str):
            continue
        await _safe_send(conn, json.dumps({
            "type": "render",
            "surface": entry.get("surface"),
            "id": entry.get("id"),
            "data": entry.get("data"),
        }, ensure_ascii=False))
    with _lock:
        _clients.add(conn)
    try:
        async for raw in conn:
            _handle_client_message(raw)
            pass
    finally:
        with _lock:
            _clients.discard(conn)
            remaining = len(_clients)
        if remaining == 0:
            with contextlib.suppress(Exception):
                from . import overlay_launcher

                overlay_launcher.reset_cooldown()


_STATE["handler"] = _handler


async def _dispatch(conn: Any) -> None:
    await _STATE["handler"](conn)


async def _serve(token: str, data_dir: Path | str | None = None) -> None:
    from websockets.asyncio.server import serve

    async with serve(_dispatch, _HOST, 0) as server:
        port = server.sockets[0].getsockname()[1]
        with _lock:
            _STATE["loop"] = asyncio.get_running_loop()
            _STATE["port"] = port
        _write_overlay_info(port, token, data_dir)
        _ready.set()
        await server.serve_forever()


def _run(token: str, data_dir: Path | str | None = None) -> None:
    coro = _serve(token, data_dir)
    try:
        asyncio.run(coro)
    except Exception as exc:
        coro.close()
        logger.warning("servidor WS del overlay terminó: %s", exc)
    finally:
        with _lock:
            _STATE["loop"] = None
            _STATE["port"] = None
        _ready.set()


def _probe_existing_server(data_dir: Path | str | None = None) -> bool:
    """Devuelve True si OTRO proceso ya tiene un WS válido en overlay.json."""
    try:
        info = json.loads((_data_dir(data_dir) / "overlay.json").read_text(encoding="utf-8"))
        if info.get("pid") == os.getpid():
            return False
    except Exception:
        return False

    async def _check() -> bool:
        from websockets.asyncio.client import connect

        uri = f"ws://{info['host']}:{info['port']}"
        async with connect(uri, open_timeout=0.4, close_timeout=0.2) as conn:
            await conn.send(json.dumps({"type": "hello", "token": info["token"], "role": "publisher"}))
            ack = json.loads(await asyncio.wait_for(conn.recv(), timeout=0.4))
            return isinstance(ack, dict) and ack.get("type") == "hello_ok"

    out = [False]

    def _runner() -> None:
        coro = _check()
        try:
            out[0] = asyncio.run(coro)
        except Exception:
            coro.close()

    t = threading.Thread(target=_runner, daemon=True)
    t.start()
    t.join(timeout=1.0)
    return out[0]


def start(data_dir: Path | str | None = None) -> None:
    """Levanta el servidor WS una sola vez (idempotente, hilo daemon)."""
    with _lock:
        if data_dir is not None:
            _STATE["data_dir_override"] = data_dir
        thread: threading.Thread | None = _STATE["thread"]
        if thread is not None and thread.is_alive():
            return
        override = _STATE["data_dir_override"]
    if _probe_existing_server(override):
        return
    with _lock:
        thread = _STATE["thread"]
        if thread is not None and thread.is_alive():
            return
        _ready.clear()
        token = secrets.token_urlsafe(32)
        _STATE["token"] = token
        thread = threading.Thread(
            target=_run, args=(token, _STATE["data_dir_override"]), daemon=True, name="hermis-ws"
        )
        _STATE["thread"] = thread
        thread.start()
    _ready.wait(timeout=_STARTUP_TIMEOUT_S)
    with _lock:
        started = _ready.is_set() and _STATE["loop"] is not None
    if not started:
        logger.warning("el WS no arrancó en %ss; render_surface entregará 0 clientes",
                       _STARTUP_TIMEOUT_S)


def _relay_to_overlay_server(obj: dict[str, Any]) -> int | None:
    """Si otro proceso de Hermes es dueño de overlay.json, publica vía WS local.

    Devuelve la cantidad de entregas, o ``None`` si no se pudo conectar al
    servidor dueño (conexión rechazada, timeout o handshake roto): señal para
    que el llamador tome el relevo. Si el servidor vivo rechaza el token (o
    cierra la sesión) devuelve 0: hay un dueño vivo, no hay relevo que tomar.
    """
    try:
        info = json.loads((_data_dir(_STATE["data_dir_override"]) / "overlay.json").read_text(encoding="utf-8"))
        with _lock:
            if _STATE["loop"] is not None and info.get("port") == _STATE["port"]:
                return 0
    except Exception:
        return 0

    async def _publish() -> int | None:
        try:
            from websockets.asyncio.client import connect
            from websockets.exceptions import ConnectionClosed

            uri = f"ws://{info['host']}:{info['port']}"
            async with connect(uri, open_timeout=1.0, close_timeout=0.5) as conn:
                await conn.send(json.dumps({"type": "hello", "token": info["token"], "role": "publisher"}))
                ack = json.loads(await asyncio.wait_for(conn.recv(), timeout=1.0))
                if not isinstance(ack, dict) or ack.get("type") != "hello_ok":
                    return 0
                await conn.send(json.dumps({"type": "broadcast", "payload": obj}, ensure_ascii=False))
                res = json.loads(await asyncio.wait_for(conn.recv(), timeout=1.0))
                return int(res.get("delivered", 0)) if isinstance(res, dict) else 0
        except Exception as exc:
            # El servidor responde y cierra la sesión (token inválido u otro
            # rechazo): hay un dueño vivo, no hay relevo que tomar.
            from websockets.exceptions import ConnectionClosed

            if isinstance(exc, ConnectionClosed):
                return 0
            return None

    out: list[int | None] = [None]

    def _runner() -> None:
        coro = _publish()
        try:
            out[0] = asyncio.run(coro)
        except Exception:
            coro.close()

    t = threading.Thread(target=_runner, daemon=True)
    t.start()
    t.join(timeout=2.5)
    return out[0]


def broadcast(obj: dict[str, Any]) -> int:
    """Manda un mensaje a todos los overlays conectados (thread-safe).

    Devuelve la cantidad de clientes a los que se les encoló el envío.
    Si el dueño de overlay.json no responde (proceso caído), este proceso
    toma el relevo: levanta su propio servidor, reescribe overlay.json y
    devuelve 0 entregas (el overlay se reconecta solo y recupera el estado).
    """
    with _lock:
        loop, count = _STATE["loop"], len(_clients)
    if loop is not None and count > 0:
        loop.call_soon_threadsafe(_send_all, json.dumps(obj, ensure_ascii=False))
        return count
    delivered = _relay_to_overlay_server(obj)
    if delivered is None:
        _take_over_overlay_server()
        return 0
    return delivered


def _take_over_overlay_server() -> None:
    """El dueño de overlay.json no responde: levanta/anuncia nuestro servidor."""
    try:
        start()
    except Exception as exc:
        logger.warning("no se pudo tomar el relevo del WS del overlay: %s", exc)
        return
    with _lock:
        loop, port, token = _STATE["loop"], _STATE["port"], _STATE["token"]
    if loop is None or port is None or token is None:
        return
    try:
        info = json.loads((_data_dir(_STATE["data_dir_override"]) / "overlay.json").read_text(encoding="utf-8"))
        if (info.get("pid") == os.getpid() and info.get("port") == port
                and info.get("token") == token):
            return
    except Exception:
        pass
    if _probe_existing_server(_STATE["data_dir_override"]):
        return  # un dueño válido está vivo: no lo tapamos
    _write_overlay_info(port, token, _STATE["data_dir_override"])


def _send_all(text: str) -> None:
    """Corre en el loop del servidor: encola un envío por cliente."""
    for conn in list(_clients):
        asyncio.create_task(_safe_send(conn, text))


async def _safe_send(conn: Any, text: str) -> None:
    try:
        await conn.send(text)
    except Exception:
        pass
