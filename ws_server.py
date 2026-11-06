"""Servidor WebSocket local para el overlay Electron de H.E.R.M.I.S.

El plugin levanta un servidor WS en 127.0.0.1 (puerto efímero) con token de
una sola sesión. El overlay lee ``overlay.json`` (puerto + token, dentro del
``plugin_data_dir``) y se autentica mandando ``{"type":"hello","token":…}``
como primer mensaje: sin hello válido se cierra la conexión (4401). Todo
queda en loopback — nada escucha en interfaces externas.

Estado Día 2: ``broadcast`` (plugin → overlay) y sincronización al conectar:
cuando un overlay completa el ``hello``, recibe ``mode`` (estado de
``state.json``) y un ``render`` por cada superficie activa, en orden. Los
mensajes posteriores del overlay se ignoran.
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


def _write_overlay_info(port: int, token: str, data_dir: Path | str | None = None) -> None:
    """Puerto y token de la sesión, escritura atómica; el overlay lee esto."""
    info = {"host": _HOST, "port": port, "token": token, "pid": os.getpid()}
    target = _data_dir(data_dir) / "overlay.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f"overlay.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(info), encoding="utf-8")
    os.replace(tmp, target)
    logger.info("overlay.json listo (puerto %s)", port)


def load_state(data_dir: Path | str | None = None) -> dict[str, Any]:
    """Lee state.json del plugin_data_dir (modo piloto automático + superficies activas)."""
    target = _data_dir(data_dir if data_dir is not None else _STATE["data_dir_override"]) / "state.json"
    with _lock:
        try:
            raw = json.loads(target.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                return {
                    "autopilot": bool(raw.get("autopilot", False)),
                    "seq": int(raw.get("seq", 0)),
                    "surfaces": dict(raw.get("surfaces") or {}) if isinstance(raw.get("surfaces"), dict) else {},
                }
        except Exception:
            pass
        return {"autopilot": False, "seq": 0, "surfaces": {}}


def save_state(state: dict[str, Any], data_dir: Path | str | None = None) -> None:
    """Persiste state.json de forma atómica en plugin_data_dir."""
    target = _data_dir(data_dir if data_dir is not None else _STATE["data_dir_override"]) / "state.json"
    with _lock:
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(f"state.{os.getpid()}.tmp")
        tmp.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, target)


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
    # un render por superficie persistida, en orden) antes de pasar al stream.
    st = load_state()
    await _safe_send(conn, json.dumps({"type": "mode", "autopilot": bool(st.get("autopilot", False))}))
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
        async for _ in conn:  # Día 1: el overlay no manda nada más
            pass
    finally:
        with _lock:
            _clients.discard(conn)


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


def _relay_to_overlay_server(obj: dict[str, Any]) -> int:
    """Si otro proceso de Hermes es dueño de overlay.json, publica vía WS local."""
    try:
        info = json.loads((_data_dir(_STATE["data_dir_override"]) / "overlay.json").read_text(encoding="utf-8"))
        with _lock:
            if _STATE["loop"] is not None and info.get("port") == _STATE["port"]:
                return 0
    except Exception:
        return 0

    async def _publish() -> int:
        from websockets.asyncio.client import connect

        uri = f"ws://{info['host']}:{info['port']}"
        async with connect(uri, open_timeout=1.0, close_timeout=0.5) as conn:
            await conn.send(json.dumps({"type": "hello", "token": info["token"], "role": "publisher"}))
            ack = json.loads(await asyncio.wait_for(conn.recv(), timeout=1.0))
            if not isinstance(ack, dict) or ack.get("type") != "hello_ok":
                return 0
            await conn.send(json.dumps({"type": "broadcast", "payload": obj}, ensure_ascii=False))
            res = json.loads(await asyncio.wait_for(conn.recv(), timeout=1.0))
            return int(res.get("delivered", 0)) if isinstance(res, dict) else 0

    out = [0]

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
    """
    with _lock:
        loop, count = _STATE["loop"], len(_clients)
    if loop is not None and count > 0:
        loop.call_soon_threadsafe(_send_all, json.dumps(obj, ensure_ascii=False))
        return count
    return _relay_to_overlay_server(obj)


def _send_all(text: str) -> None:
    """Corre en el loop del servidor: encola un envío por cliente."""
    for conn in list(_clients):
        asyncio.create_task(_safe_send(conn, text))


async def _safe_send(conn: Any, text: str) -> None:
    try:
        await conn.send(text)
    except Exception:
        pass
