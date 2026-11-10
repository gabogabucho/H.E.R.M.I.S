"""Lanzador en segundo plano del overlay Electron de H.E.R.M.I.S.

Las tools abren el overlay cuando el usuario entra al Modo Piloto Automático
o cuando llega un dibujo sin overlay conectado (``register()`` jamás lanza
procesos). Reglas:

- Si falta ``node`` o ``npm`` no lanza nada y devuelve una note clara.
- Si falta ``overlay/node_modules``, la primera vez corre ``npm ci`` y
  después ``npm start``, todo desacoplado: la tool vuelve enseguida y nunca
  espera a npm; el trabajo corre en un hilo daemon del proceso plugin.
- Proceso desprendido: ``stdin=DEVNULL`` y ``stdout/stderr`` a
  ``overlay.log`` en el data dir; ``DETACHED_PROCESS`` + ``CREATE_NO_WINDOW``
  en Windows, ``start_new_session`` en el resto.
- No lanza dos veces: marca en memoria del proceso y en ``overlay.launch``
  (data dir) y no relanza durante 90 s; Electron bloquea instancias únicas.
- Desactivable con ``HERMIS_OVERLAY_AUTOSTART=0``.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

from . import ws_server

logger = logging.getLogger("hermis")

_RELAUNCH_COOLDOWN_S = 90
_INSTALL_TIMEOUT_S = 300
_LAUNCH_FILE = "overlay.launch"
_LOG_FILE = "overlay.log"

_overlay_dir = Path(__file__).parent / "overlay"

_launch_lock = threading.Lock()
_last_launch: float | None = None
_pipeline_busy = False


def _recent_launch(now: float, data_dir: Path) -> bool:
    """¿Se lanzó el overlay hace menos de 90 s (memoria o archivo)?"""
    if _last_launch is not None and (now - _last_launch) < _RELAUNCH_COOLDOWN_S:
        return True
    try:
        raw = json.loads((data_dir / _LAUNCH_FILE).read_text(encoding="utf-8"))
        ts = float(raw.get("launched_at") or 0)
        return ts > 0 and (now - ts) < _RELAUNCH_COOLDOWN_S
    except Exception:
        return False


def _detach_kwargs() -> dict[str, Any]:
    """Flags de desprendimiento del proceso según plataforma."""
    if sys.platform == "win32":
        # Sin DETACHED_PROCESS a propósito: junto a él Windows ignora CREATE_NO_WINDOW,
        # npm.cmd queda sin consola y node abre una ventana de terminal visible. Así se
        # crea una consola oculta que heredan npm, node y Electron.
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW}
    return {"start_new_session": True}


# Huella del package-lock con el que se hizo el último `npm ci` exitoso. Sin
# esto, un update del plugin que suma dependencias nunca las instalaba (solo se
# instalaba si faltaba node_modules entero).
_DEPS_MARKER = ".hermis-lock-sha256"


def _lock_digest(overlay_path: Path) -> str | None:
    try:
        return hashlib.sha256((overlay_path / "package-lock.json").read_bytes()).hexdigest()
    except OSError:
        return None


def needs_install(overlay_path: Path) -> bool:
    """Hay que correr `npm ci`: falta node_modules o cambió el package-lock."""
    modules = overlay_path / "node_modules"
    if not modules.exists():
        return True
    digest = _lock_digest(overlay_path)
    if digest is None:
        return False
    try:
        return (modules / _DEPS_MARKER).read_text(encoding="utf-8").strip() != digest
    except OSError:
        return True  # instalación previa sin huella: se reinstala una sola vez


def _write_deps_marker(overlay_path: Path) -> None:
    digest = _lock_digest(overlay_path)
    if digest is None:
        return
    try:
        (overlay_path / "node_modules" / _DEPS_MARKER).write_text(digest, encoding="utf-8")
    except OSError as exc:
        logger.warning("no se pudo guardar la huella de dependencias: %s", exc)


def _launch_pipeline(npm: str, overlay_path: Path, data_dir: Path, installing: bool) -> None:
    """Corre en un hilo daemon: ``npm ci`` (si falta) y después ``npm start``.

    No bloquea nunca a la tool: el overlay queda vivo con vida propia; si el
    proceso plugin muere a mitad del ``npm ci``, el próximo intento repite la
    instalación (sigue sin haber ``node_modules``).
    """
    global _pipeline_busy
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        with open(data_dir / _LOG_FILE, "ab") as log:
            if installing:
                try:
                    result = subprocess.run([npm, "ci"], cwd=str(overlay_path),
                                            stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                                            timeout=_INSTALL_TIMEOUT_S, **_detach_kwargs())
                    if result.returncode != 0:
                        log.write(f"\n[hermis] npm ci failed with exit code {result.returncode}\n"
                                  .encode("utf-8", "replace"))
                        return
                    _write_deps_marker(overlay_path)
                except subprocess.TimeoutExpired:
                    log.write(b"\n[hermis] npm ci tardo demasiado; intento cancelado\n")
                    return
                except Exception as exc:
                    log.write(f"\n[hermis] npm ci fallo: {exc}\n".encode("utf-8", "replace"))
                    return
            subprocess.Popen([npm, "start", "--", "--data-dir", str(data_dir)],
                             cwd=str(overlay_path), stdin=subprocess.DEVNULL,
                             stdout=log, stderr=subprocess.STDOUT, **_detach_kwargs())
    except Exception as exc:
        logger.warning("no se pudo abrir el overlay: %s", exc)
    finally:
        with _launch_lock:
            _pipeline_busy = False


def ensure_overlay_running() -> str | None:
    """Abre el overlay Electron si corresponde; devuelve la note de la tool.

    Devuelve ``None`` cuando no hay nada que avisar: env desactivado, throttle
    activo (se lanzó hace menos de 90 s) o pipeline en curso.
    """
    global _last_launch, _pipeline_busy
    if os.environ.get("HERMIS_OVERLAY_AUTOSTART") == "0":
        return None
    node, npm = shutil.which("node"), shutil.which("npm")
    if not node or not npm:
        return "instalá Node.js 20+ para ver el overlay"
    data_dir = ws_server.data_dir()
    now = time.time()
    with _launch_lock:
        if _pipeline_busy or _recent_launch(now, data_dir):
            return None
        _last_launch = now
        _pipeline_busy = True
    updating = (_overlay_dir / "node_modules").exists()
    installing = needs_install(_overlay_dir)
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        (data_dir / _LAUNCH_FILE).write_text(
            json.dumps({"launched_at": now, "pid": os.getpid()}), encoding="utf-8")
    except Exception as exc:
        logger.warning("no se pudo escribir %s: %s", _LAUNCH_FILE, exc)
    try:
        threading.Thread(target=_launch_pipeline, args=(npm, _overlay_dir, data_dir, installing),
                         daemon=True, name="hermis-overlay-launch").start()
    except Exception as exc:
        with _launch_lock:
            _pipeline_busy = False
        return f"no se pudo abrir el overlay: {exc}"
    if installing and updating:
        return "abriendo el overlay; actualiza sus dependencias (~1 min)"
    if installing:
        return "abriendo el overlay; la primera vez instala dependencias (~1 min)"
    return "abriendo el overlay…"
