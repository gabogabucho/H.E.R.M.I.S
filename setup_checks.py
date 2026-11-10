"""Chequeos de instalación para el onboarding de H.E.R.M.I.S (solo lectura).

Nunca instala ni cambia la configuración de Hermes: diagnostica y devuelve el
comando exacto para que el usuario lo copie. Las credenciales se chequean solo
por presencia en el entorno del proceso, nunca leyendo ``.env`` ni su valor.

Los motores de voz se buscan en el entorno del proceso que corre el plugin: si
el usuario ya los instaló pero no reinició el gateway, siguen apareciendo como
faltantes, y el arreglo indicado (reiniciar) es justo el correcto.
"""
from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path
from typing import Any

from . import overlay_launcher

OVERLAY_DIR = Path(__file__).resolve().parent / "overlay"
RESTART = "hermes gateway stop; hermes gateway ensure"
CUA_KEYS = ("cua:type:foreground", "cua:key:foreground", "cua:click:foreground", "cua:focus_app:foreground")


def hermes_home() -> Path:
    home = os.environ.get("HERMES_HOME")
    if home:
        return Path(home)
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local")) / "hermes"
    return Path.home() / ".hermes"


def _read_config() -> dict[str, Any] | None:
    """config.yaml de Hermes, o None si no se puede leer (el chequeo queda como 'info')."""
    try:
        import yaml  # viene con Hermes; si falta, los chequeos de config se degradan
        raw = yaml.safe_load((hermes_home() / "config.yaml").read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return None


def _get(cfg: dict[str, Any] | None, dotted: str) -> Any:
    node: Any = cfg
    for part in dotted.split("."):
        if not isinstance(node, dict):
            return None
        node = node.get(part)
    return node


def _has_module(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except Exception:
        return False


def _item(check_id: str, label: str, status: str, detail: str, fix: str | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {"id": check_id, "label": label, "status": status, "detail": detail}
    if fix:
        out["fix"] = fix
    return out


def _check_overlay() -> dict[str, Any]:
    label = "Overlay (Electron)"
    runtime = overlay_launcher.runtime_status()
    if runtime["error"]:
        return _item("overlay", label, "warn", runtime["error"],
                     "winget install OpenJS.NodeJS.LTS")
    startup = overlay_launcher.bootstrap_status()
    if startup["phase"] == "failed":
        return _item("overlay", label, "warn", overlay_launcher.bootstrap_summary(),
                     "/hermis retry" if startup["retryable"] else None)
    if startup["phase"] in {"installing", "starting", "disabled"}:
        return _item("overlay", label, "info", overlay_launcher.bootstrap_summary())
    if not (OVERLAY_DIR / "node_modules").is_dir():
        return _item("overlay", label, "warn",
                     "Faltan las dependencias del overlay (se instalan solas al activar el modo, o ahora).",
                     f'cd "{OVERLAY_DIR}"; npm ci')
    return _item("overlay", label, "ok", "Listo.")


def _check_stt(cfg: dict[str, Any] | None) -> dict[str, Any]:
    label = "Transcripción de voz"
    provider = str(_get(cfg, "stt.provider") or "local")
    if provider == "elevenlabs" and not os.environ.get("ELEVENLABS_API_KEY"):
        return _item("stt", label, "warn",
                     f"ElevenLabs elegido pero falta ELEVENLABS_API_KEY (agregala, sin #, en {hermes_home() / '.env'} y reiniciá).",
                     "ELEVENLABS_API_KEY=")
    if provider != "local":
        return _item("stt", label, "ok", f"Proveedor en la nube: {provider}.")
    if _has_module("faster_whisper"):
        return _item("stt", label, "ok", "Whisper local instalado.")
    return _item("stt", label, "warn",
                 "Falta el motor local (faster-whisper). Si ya lo instalaste, reiniciá el gateway.",
                 f"hermes pm install --extra voice --extra stt-whisper; {RESTART}")


def _check_language(cfg: dict[str, Any] | None) -> dict[str, Any]:
    label = "Idioma de la transcripción"
    if cfg is None:
        return _item("stt_language", label, "info", "No se pudo leer config.yaml.")
    language = _get(cfg, "stt.language") or "en"
    if str(language).lower().startswith("en"):
        return _item("stt_language", label, "info",
                     "Está en inglés (el valor por defecto). Si le hablás en español, cambialo.",
                     "hermes config set stt.language es")
    return _item("stt_language", label, "ok", f"Idioma: {language}.")


def _check_tts(cfg: dict[str, Any] | None) -> dict[str, Any]:
    label = "Voz de respuesta (TTS)"
    provider = str(_get(cfg, "tts.provider") or "edge")
    if cfg is not None and _get(cfg, "voice.auto_tts") is False:
        # En el Desktop "leer en voz alta" es una preferencia local (solo se copia de
        # voice.auto_tts la primera vez): sin el toggle, la charla de voz solo transcribe.
        return _item("tts", label, "info",
                     "Si Hermes te contesta solo con texto: en el Desktop activá el parlante (ver el paso 'En el "
                     "Desktop'). voice.auto_tts solo cubre la terminal y la mensajería.",
                     "hermes config set voice.auto_tts true")
    if provider == "elevenlabs":
        if not _has_module("elevenlabs"):
            return _item("tts", label, "warn", "ElevenLabs elegido pero falta su paquete.",
                         f"hermes pm install --extra tts-premium; {RESTART}")
        if not os.environ.get("ELEVENLABS_API_KEY"):
            return _item("tts", label, "warn",
                         f"Falta ELEVENLABS_API_KEY (agregala, sin #, en {hermes_home() / '.env'} y reiniciá).",
                         "ELEVENLABS_API_KEY=")
        return _item("tts", label, "ok", "ElevenLabs listo.")
    return _item("tts", label, "ok", f"Proveedor: {provider}.")


def _check_wake(cfg: dict[str, Any] | None) -> dict[str, Any]:
    label = 'Wake word ("hey hermes")'
    if not (_has_module("pyopen_wakeword") or _has_module("openwakeword")):
        return _item("wake", label, "warn", "Falta el motor del wake word. Si ya lo instalaste, reiniciá el gateway.",
                     f"hermes pm install --extra wake-openwakeword; {RESTART}")
    if not _get(cfg, "wake_word.enabled"):
        return _item("wake", label, "info", "Instalado. Activalo en el chat de Hermes.", "/wake on")
    return _item("wake", label, "ok", "Escuchando.")


def _check_computer_use(cfg: dict[str, Any] | None) -> dict[str, Any]:
    label = "Permisos del computer use"
    allow = _get(cfg, "command_allowlist")
    if isinstance(allow, list) and any(isinstance(k, str) and k.startswith("cua:") for k in allow):
        return _item("computer_use", label, "ok", "Escribir y usar teclas no pide aprobación cada vez.")
    snippet = "command_allowlist:\n" + "\n".join(f"  - {k}" for k in CUA_KEYS)
    return _item("computer_use", label, "info",
                 f"Cada vez que escriba o use el teclado te va a pedir aprobación. Para darla una sola vez, "
                 f"elegí 'Always' o agregá esto a {hermes_home() / 'config.yaml'}.", snippet)


def _desktop_toggles() -> dict[str, Any]:
    """Paso fijo: el Desktop guarda estos dos toggles adentro de la app y el plugin no puede leerlos."""
    return _item("desktop", "En el Desktop", "info",
                 "Elegí 'This device' abajo en la barra lateral (en un gateway remoto el plugin no corre). "
                 "Pasá el mouse sobre el micrófono: la oreja activa 'hey hermes' y el parlante lee las "
                 "respuestas en voz alta. Sin el parlante, la charla de voz solo transcribe. "
                 "Para hablar, usá el botón negro de la derecha (el micrófono es solo dictado).")


def _check_gestures() -> dict[str, Any]:
    """Ítem informativo: gestos con cámara (opcional, apagados por defecto)."""
    label = "Gestos con cámara (opcional)"
    try:
        from . import ws_server
        enabled = bool(ws_server.load_state().get("gestures", False))
    except Exception:
        enabled = False
    if enabled:
        return _item("gestures", label, "ok",
                     "Activados: la cámara se prende solo durante el modo piloto y todo se procesa en tu PC.")
    return _item("gestures", label, "info",
                 "Apagados. Para cerrar o cambiar de superficie con la mano, activalos: la cámara "
                 "funciona solo en el modo piloto y los cuadros nunca salen de tu PC.",
                 "/hermis gestures on")


def run_checks() -> list[dict[str, Any]]:
    """Todos los chequeos; un fallo inesperado en uno nunca rompe el resto."""
    cfg = _read_config()
    checks = (_check_overlay, lambda: _check_stt(cfg), lambda: _check_language(cfg),
              lambda: _check_tts(cfg), lambda: _check_wake(cfg), lambda: _check_computer_use(cfg),
              _check_gestures, _desktop_toggles)
    items = []
    for check in checks:
        try:
            items.append(check())
        except Exception as exc:
            items.append(_item("error", "Chequeo", "info", f"No se pudo revisar: {type(exc).__name__}."))
    return items


def surface_data() -> dict[str, Any]:
    items = run_checks()
    pending = sum(1 for it in items if it["status"] == "warn")
    if pending:
        subtitle = f"{pending} paso(s) pendiente(s). Consulta las indicaciones de cada paso y vuelve a revisar."
    elif any(it["status"] == "info" for it in items):
        subtitle = "No se detectaron faltantes. Revisa las indicaciones de los pasos informativos."
    else:
        subtitle = "Chequeos completados sin faltantes detectados."
    return {"title": "Configuración de H.E.R.M.I.S", "subtitle": subtitle, "items": items}


def as_text() -> str:
    icons = {"ok": "[ok]", "warn": "[falta]", "info": "[info]"}
    lines = []
    for it in run_checks():
        lines.append(f"{icons.get(it['status'], '-')} {it['label']}: {it['detail']}")
        if it.get("fix"):
            lines.extend(f"    {line}" for line in it["fix"].splitlines())
    return "\n".join(lines)
