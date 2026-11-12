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
  (data dir) y no relanza durante 90 s (se limpia con ``reset_cooldown`` si el
  overlay conectado se desconecta); Electron bloquea instancias únicas.
- Desactivable con ``HERMIS_OVERLAY_AUTOSTART=0``.
- A held native lock serializes cooperating hosts using the same overlay
  installation, through installation and the owned npm wrapper's lifetime.
  The identity file is never deleted as a stale-lock recovery mechanism.

Los textos que ve el usuario salen del catálogo (messages/*.json): cada
detalle lleva su clave y se resuelve en el idioma de la interfaz.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, BinaryIO

from . import bootstrap_lock, child_env, i18n, ws_server

logger = logging.getLogger("hermis")

_RELAUNCH_COOLDOWN_S = 90
_INSTALL_TIMEOUT_S = 300
_STARTUP_TIMEOUT_S = 30
_LAUNCH_FILE = "overlay.launch"
_LOG_FILE = "overlay.log"
MIN_NODE_VERSION = (22, 12, 0)
NODE_REQUIREMENT = ".".join(map(str, MIN_NODE_VERSION))

_overlay_dir = Path(__file__).parent / "overlay"

_launch_lock = threading.Lock()
_last_launch: float | None = None
_pipeline_busy = False
_launch_process: subprocess.Popen | None = None
_bootstrap_guard: BinaryIO | None = None
_bootstrap: dict[str, Any] = {"phase": "idle", "error": None, "started_at": 0}
# Código de fallo → clave del catálogo. El texto vive en un solo lugar y sale
# en el idioma de la interfaz.
_ERROR_DETAILS = {
    "install_failed": "launcher.error.install_failed",
    "install_timeout": "launcher.error.install_timeout",
    "install_denied": "launcher.error.install_denied",
    "launch_failed": "launcher.error.launch_failed",
    "launch_exited": "launcher.error.launch_exited",
    "startup_timeout": "launcher.error.startup_timeout",
    "process_unknown": "launcher.error.process_unknown",
    "storage_failed": "launcher.error.storage_failed",
    "worker_failed": "launcher.error.worker_failed",
    "lock_failed": "launcher.error.lock_failed",
}


def _release_bootstrap_guard() -> None:
    """Release our native ownership while holding _launch_lock."""
    global _bootstrap_guard
    guard, _bootstrap_guard = _bootstrap_guard, None
    if guard is not None:
        with contextlib.suppress(OSError):
            bootstrap_lock.release(guard)


def _process_running(process: subprocess.Popen | None) -> bool:
    if process is None:
        return False
    try:
        return process.poll() is None
    except OSError:
        return True  # Unknown ownership is not permission to start a duplicate.


def bootstrap_status(locale: str | None = None) -> dict[str, Any]:
    """Return a read-only local snapshot; a started process is not a connection."""
    loc = locale or i18n.get_locale()
    if ws_server.overlay_connected():
        return {"phase": "connected", "error": None,
                "detail": i18n.t("launcher.detail.connected", loc), "retryable": False}

    if os.environ.get("HERMIS_OVERLAY_AUTOSTART") == "0":
        return {"phase": "disabled", "error": None,
                "detail": i18n.t("launcher.detail.disabled", loc), "retryable": False}
    with _launch_lock:
        status = dict(_bootstrap)
        process, busy = _launch_process, _pipeline_busy
    if status["phase"] == "starting":
        try:
            code = process.poll() if process is not None else None
        except OSError:
            status.update(phase="failed", error="process_unknown")
        else:
            if code not in (None, 0):
                status.update(phase="failed", error="launch_exited", exit_code=code)
            elif time.monotonic() - status["started_at"] >= _STARTUP_TIMEOUT_S:
                status.update(phase="failed", error="startup_timeout")
    status.pop("started_at", None)
    detail_key = _ERROR_DETAILS.get(status["error"], "launcher.detail.unverified")
    if status["phase"] == "busy":
        detail_key = "launcher.detail.busy"
    running = _process_running(process)
    status["retryable"] = not busy and not running and status["phase"] in {"idle", "failed"}
    parts = [detail_key]
    if status["phase"] == "failed" and running:
        parts.append("launcher.detail.failed_running")
    elif status["phase"] == "failed" and status["retryable"]:
        parts.append("launcher.detail.failed_retry")
    status["detail"] = " ".join(i18n.t(key, loc) for key in parts)
    return status


def bootstrap_summary(locale: str | None = None) -> str:
    status = bootstrap_status(locale)
    code = f" ({status['error']})" if status["error"] else ""
    exit_code = f" [exit {status['exit_code']}]" if "exit_code" in status else ""
    return f"{status['phase']}{code}{exit_code}: {status.get('detail', '')}"


def _bootstrap_failed(code: str, data_dir: Path, exit_code: int | None = None) -> None:
    global _bootstrap, _last_launch
    with _launch_lock:
        _bootstrap = {"phase": "failed", "error": code, "started_at": 0}
        if exit_code is not None:
            _bootstrap["exit_code"] = exit_code
        _last_launch = None
        with contextlib.suppress(OSError):
            (data_dir / _LAUNCH_FILE).unlink(missing_ok=True)


def runtime_status(locale: str | None = None) -> dict[str, Any]:
    """Inspect PATH and a bounded Node version probe without installing anything."""
    loc = locale or i18n.get_locale()
    node, npm = shutil.which("node"), shutil.which("npm")
    status: dict[str, Any] = {"node": node, "npm": npm, "version": None, "error": None}
    requirement = i18n.t("launcher.requirement", loc, version=NODE_REQUIREMENT)
    if not node or not npm:
        status["error"] = i18n.t("launcher.error.node_missing", loc, requirement=requirement)
        return status
    try:
        result = subprocess.run([node, "--version"], stdin=subprocess.DEVNULL,
                                capture_output=True, text=True, timeout=5,
                                env=child_env.minimal_env(), **_detach_kwargs())
    except (OSError, subprocess.TimeoutExpired):
        status["error"] = i18n.t("launcher.error.node_unverified", loc, requirement=requirement)
        return status
    match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", result.stdout.strip()) if result.returncode == 0 else None
    if match is None:
        status["error"] = i18n.t("launcher.error.node_version", loc, requirement=requirement)
        return status
    version = tuple(map(int, match.groups()))
    status["version"] = "v" + ".".join(map(str, version))
    if version < MIN_NODE_VERSION:
        status["error"] = i18n.t("launcher.error.node_incompatible", loc,
                                version=status["version"], requirement=requirement)
    return status


def reset_cooldown(data_dir: Path | None = None) -> None:
    """Limpia el cooldown de 90 s cuando el último cliente del overlay se desconecta."""
    global _last_launch
    target_dir = data_dir if data_dir is not None else ws_server.data_dir()
    with _launch_lock:
        _last_launch = None
    with contextlib.suppress(OSError):
        (target_dir / _LAUNCH_FILE).unlink(missing_ok=True)


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
    if not digest:
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
    global _pipeline_busy, _launch_process, _bootstrap
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        with open(data_dir / _LOG_FILE, "ab") as log:
            if installing:
                try:
                    result = subprocess.run([npm, "ci"], cwd=str(overlay_path),
                                            stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                                            env=child_env.minimal_env(),
                                            timeout=_INSTALL_TIMEOUT_S, **_detach_kwargs())
                    if result.returncode != 0:
                        log.write(f"\n[hermis] npm ci failed with exit code {result.returncode}\n"
                                  .encode("utf-8", "replace"))
                        _bootstrap_failed("install_failed", data_dir, result.returncode)
                        return
                    _write_deps_marker(overlay_path)
                except subprocess.TimeoutExpired:
                    log.write(b"\n[hermis] npm ci tardo demasiado; intento cancelado\n")
                    _bootstrap_failed("install_timeout", data_dir)
                    return
                except Exception as exc:
                    log.write(f"\n[hermis] npm ci fallo: {exc}\n".encode("utf-8", "replace"))
                    _bootstrap_failed("install_denied", data_dir)
                    return
            try:
                process = subprocess.Popen([npm, "start", "--", "--data-dir", str(data_dir)],
                                           cwd=str(overlay_path), stdin=subprocess.DEVNULL,
                                           stdout=log, stderr=subprocess.STDOUT,
                                           env=child_env.minimal_env(child_env.OVERLAY_GATEWAY_VARS),
                                           **_detach_kwargs())
            except Exception:
                _bootstrap_failed("launch_failed", data_dir)
                return
            with _launch_lock:
                _launch_process = process
                _bootstrap = {"phase": "starting", "error": None, "started_at": time.monotonic()}
            if process is not None:
                try:
                    process.wait()
                except OSError:
                    with _launch_lock:
                        _bootstrap = {"phase": "failed", "error": "process_unknown", "started_at": 0}
    except Exception:
        _bootstrap_failed("storage_failed", data_dir)
    finally:
        with _launch_lock:
            _pipeline_busy = False
            if not _process_running(_launch_process):
                _release_bootstrap_guard()


def ensure_overlay_running(*, retry: bool = False) -> str | None:
    """Abre el overlay Electron si corresponde; devuelve la note de la tool.

    Devuelve ``None`` cuando no hay nada que avisar: env desactivado, throttle
    activo (se lanzó hace menos de 90 s) o pipeline en curso.
    """
    global _last_launch, _pipeline_busy, _bootstrap, _launch_process, _bootstrap_guard
    loc = i18n.get_locale()
    if os.environ.get("HERMIS_OVERLAY_AUTOSTART") == "0":
        return None
    snapshot = bootstrap_status(loc)
    if snapshot["phase"] == "connected":
        return None
    runtime = runtime_status(loc)
    if runtime["error"]:
        return runtime["error"]
    npm = runtime["npm"]
    data_dir = ws_server.data_dir()
    now = time.time()
    with _launch_lock:
        if _pipeline_busy or _process_running(_launch_process):
            return None
        _release_bootstrap_guard()
        if retry and snapshot["phase"] == "failed" and snapshot["retryable"]:
            _last_launch = None
            with contextlib.suppress(OSError):
                (data_dir / _LAUNCH_FILE).unlink(missing_ok=True)
        if _recent_launch(now, data_dir):
            return None
        try:
            _bootstrap_guard = bootstrap_lock.acquire(_overlay_dir)
        except OSError:
            _bootstrap = {"phase": "failed", "error": "lock_failed", "started_at": 0}
            return i18n.t("launcher.error.lock_failed", loc)
        if _bootstrap_guard is None:
            _bootstrap = {"phase": "busy", "error": None, "started_at": 0}
            return i18n.t("launcher.detail.busy", loc)
        _last_launch = now
        _pipeline_busy = True
        _launch_process = None
        _bootstrap = {"phase": "installing", "error": None, "started_at": time.monotonic()}
    updating = (_overlay_dir / "node_modules").exists()
    installing = needs_install(_overlay_dir) or (retry and snapshot["error"] in {"launch_failed", "launch_exited"})
    with _launch_lock:
        _bootstrap["phase"] = "installing" if installing else "starting"
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        (data_dir / _LAUNCH_FILE).write_text(
            json.dumps({"launched_at": now, "pid": os.getpid()}), encoding="utf-8")
    except Exception:
        _bootstrap_failed("storage_failed", data_dir)
        with _launch_lock:
            _pipeline_busy = False
            _release_bootstrap_guard()
        return i18n.t("launcher.error.storage_failed", loc)
    try:
        threading.Thread(target=_launch_pipeline, args=(npm, _overlay_dir, data_dir, installing),
                         daemon=True, name="hermis-overlay-launch").start()
    except Exception:
        _bootstrap_failed("worker_failed", data_dir)
        with _launch_lock:
            _pipeline_busy = False
            _release_bootstrap_guard()
        return i18n.t("launcher.error.worker_failed", loc)
    if installing and updating:
        return i18n.t("launcher.note.installing_update", loc)
    if installing:
        return i18n.t("launcher.note.installing_first", loc)
    return i18n.t("launcher.note.starting", loc)
