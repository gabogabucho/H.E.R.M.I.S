"""Servidor WebSocket local para el overlay Electron de H.E.R.M.I.S.

El plugin levanta un servidor WS en 127.0.0.1 (puerto efímero) con token de
una sola sesión. El overlay lee ``overlay.json`` (puerto + token, dentro del
``plugin_data_dir``) y se autentica mandando ``{"type":"hello","token":…}``
como primer mensaje: sin hello válido se cierra la conexión (4401). Todo
queda en loopback — nada escucha en interfaces externas.

Estado Día 1: solo ``broadcast`` (plugin → overlay). Los mensajes posteriores
del overlay se ignoran; Día 2+ agrega ``close_surface``/``list_surfaces`` y
estado persistente.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import secrets
import threading
from pathlib import Path
from typing import Any

logger = logging.getLogger("hermis")

_HOST = "127.0.0.1"
_HELLO_TIMEOUT_S = 10

_lock = threading.Lock()
_loop: asyncio.AbstractEventLoop | None = None
_clients: set[Any] = set()
_thread: threading.Thread | None = None
_token: str | None = None
_ready = threading.Event()


def _data_dir() -> Path:
    """Directorio de estado del plugin (sobrevive updates; sigue al perfil)."""
    try:
        from plugins.plugin_storage import plugin_data_dir
        return Path(plugin_data_dir("hermis"))
    except Exception:
        return Path.home() / ".hermes" / "plugin-data" / "hermis"


def _write_overlay_info(port: int, token: str) -> None:
    """Puerto y token de la sesión, escritura atómica; el overlay lee esto."""
    info = {"host": _HOST, "port": port, "token": token, "pid": os.getpid()}
    target = _data_dir() / "overlay.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".tmp")
    tmp.write_text(json.dumps(info), encoding="utf-8")
    os.replace(tmp, target)
    logger.info("overlay.json listo (puerto %s)", port)


async def _handler(conn: Any) -> None:
    try:
        hello = json.loads(await asyncio.wait_for(conn.recv(), _HELLO_TIMEOUT_S))
    except Exception:
        await conn.close(code=4400, reason="hello timeout o mensaje inválido")
        return
    if not isinstance(hello, dict) or hello.get("type") != "hello" or hello.get("token") != _token:
        await conn.close(code=4401, reason="token inválido")
        return
    await conn.send(json.dumps({"type": "hello_ok"}))
    with _lock:
        _clients.add(conn)
    try:
        async for _ in conn:  # Día 1: el overlay no manda nada más
            pass
    finally:
        with _lock:
            _clients.discard(conn)


async def _serve(token: str) -> None:
    from websockets.asyncio.server import serve

    async with serve(_handler, _HOST, 0) as server:
        global _loop
        port = server.sockets[0].getsockname()[1]
        with _lock:
            _loop = asyncio.get_running_loop()
        _write_overlay_info(port, token)
        _ready.set()
        await server.serve_forever()


def _run(token: str) -> None:
    try:
        asyncio.run(_serve(token))
    except Exception as exc:
        logger.warning("servidor WS del overlay terminó: %s", exc)
    finally:
        _ready.set()


def start() -> None:
    """Levanta el servidor WS una sola vez (idempotente, hilo daemon)."""
    global _thread, _token
    with _lock:
        if _thread is not None:
            return
        _token = secrets.token_urlsafe(32)
        _thread = threading.Thread(target=_run, args=(_token,), daemon=True, name="hermis-ws")
        _thread.start()
    _ready.wait(timeout=10)
    if not _ready.is_set():
        logger.warning("el WS no arrancó en %ss; render_surface entregará 0 clientes",
                       _HELLO_TIMEOUT_S)


def broadcast(obj: dict[str, Any]) -> int:
    """Manda un mensaje a todos los overlays conectados (thread-safe).

    Devuelve la cantidad de clientes a los que se les encoló el envío.
    """
    with _lock:
        loop, count = _loop, len(_clients)
    if loop is None or count == 0:
        return 0
    loop.call_soon_threadsafe(_send_all, json.dumps(obj, ensure_ascii=False))
    return count


def _send_all(text: str) -> None:
    """Corre en el loop del servidor: encola un envío por cliente."""
    for conn in list(_clients):
        asyncio.ensure_future(_safe_send(conn, text))


async def _safe_send(conn: Any, text: str) -> None:
    try:
        await conn.send(text)
    except Exception:
        pass
