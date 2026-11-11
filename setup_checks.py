"""Chequeos de instalación para el onboarding de H.E.R.M.I.S (solo lectura).

Nunca instala ni cambia la configuración de Hermes: diagnostica y devuelve el
comando exacto para que el usuario lo copie. Las credenciales se chequean solo
por presencia en el entorno del proceso, nunca leyendo ``.env`` ni su valor.

Los motores de voz se buscan en el entorno del proceso que corre el plugin: si
el usuario ya los instaló pero no reinició el gateway, siguen apareciendo como
faltantes, y el arreglo indicado (reiniciar) es justo el correcto.

Los textos salen del catálogo (messages/*.json): el checklist se lee en el
idioma de la interfaz, no solo en español.
"""
from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path
from typing import Any

from . import i18n, overlay_launcher

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
    return i18n.read_hermes_config()


def _get(cfg: dict[str, Any] | None, dotted: str) -> Any:
    return i18n.config_value(cfg, dotted)


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


def _check_overlay(loc: str) -> dict[str, Any]:
    label = i18n.t("setup.check.overlay", loc)
    runtime = overlay_launcher.runtime_status(loc)
    if runtime["error"]:
        return _item("overlay", label, "warn", runtime["error"],
                     "winget install OpenJS.NodeJS.LTS")
    startup = overlay_launcher.bootstrap_status(loc)
    if startup.get("phase") == "failed":
        return _item("overlay", label, "warn", overlay_launcher.bootstrap_summary(loc),
                     "/hermis retry" if startup.get("retryable") else None)
    if startup.get("phase") in {"installing", "starting", "disabled", "busy"}:
        return _item("overlay", label, "info", overlay_launcher.bootstrap_summary(loc))
    if not (OVERLAY_DIR / "node_modules").is_dir():
        return _item("overlay", label, "warn",
                     i18n.t("setup.overlay.missing_deps", loc),
                     f'cd "{OVERLAY_DIR}"; npm ci')
    return _item("overlay", label, "ok", i18n.t("setup.overlay.ready", loc))


def _check_stt(cfg: dict[str, Any] | None, loc: str) -> dict[str, Any]:
    label = i18n.t("setup.check.stt", loc)
    provider = str(_get(cfg, "stt.provider") or "local")
    if provider == "elevenlabs" and not os.environ.get("ELEVENLABS_API_KEY"):
        return _item("stt", label, "warn",
                     i18n.t("setup.stt.elevenlabs_missing_key", loc, path=hermes_home() / ".env"),
                     "ELEVENLABS_API_KEY=")
    if provider != "local":
        return _item("stt", label, "ok", i18n.t("setup.stt.cloud_provider", loc, provider=provider))
    if _has_module("faster_whisper"):
        return _item("stt", label, "ok", i18n.t("setup.stt.whisper_local", loc))
    return _item("stt", label, "warn",
                 i18n.t("setup.stt.missing_local", loc),
                 f"hermes pm install --extra voice --extra stt-whisper; {RESTART}")


def _check_language(cfg: dict[str, Any] | None, loc: str) -> dict[str, Any]:
    label = i18n.t("setup.check.stt_language", loc)
    if cfg is None:
        return _item("stt_language", label, "info", i18n.t("setup.language.unreadable", loc))
    language = _get(cfg, "stt.language") or "en"
    if str(language).lower().startswith("en"):
        return _item("stt_language", label, "info",
                     i18n.t("setup.language.english", loc),
                     "hermes config set stt.language es")
    return _item("stt_language", label, "ok", i18n.t("setup.language.current", loc, language=language))


def _check_tts(cfg: dict[str, Any] | None, loc: str) -> dict[str, Any]:
    label = i18n.t("setup.check.tts", loc)
    provider = str(_get(cfg, "tts.provider") or "edge")
    if cfg is not None and _get(cfg, "voice.auto_tts") is False:
        # En el Desktop "leer en voz alta" es una preferencia local (solo se copia de
        # voice.auto_tts la primera vez): sin el toggle, la charla de voz solo transcribe.
        return _item("tts", label, "info",
                     i18n.t("setup.tts.auto_tts_off", loc),
                     "hermes config set voice.auto_tts true")
    if provider == "elevenlabs":
        if not _has_module("elevenlabs"):
            return _item("tts", label, "warn", i18n.t("setup.tts.elevenlabs_missing_pkg", loc),
                         f"hermes pm install --extra tts-premium; {RESTART}")
        if not os.environ.get("ELEVENLABS_API_KEY"):
            return _item("tts", label, "warn",
                         i18n.t("setup.tts.elevenlabs_missing_key", loc, path=hermes_home() / ".env"),
                         "ELEVENLABS_API_KEY=")
        return _item("tts", label, "ok", i18n.t("setup.tts.elevenlabs_ready", loc))
    return _item("tts", label, "ok", i18n.t("setup.tts.provider", loc, provider=provider))


def _check_wake(cfg: dict[str, Any] | None, loc: str) -> dict[str, Any]:
    label = i18n.t("setup.check.wake", loc)
    if not (_has_module("pyopen_wakeword") or _has_module("openwakeword")):
        return _item("wake", label, "warn", i18n.t("setup.wake.missing_engine", loc),
                     f"hermes pm install --extra wake-openwakeword; {RESTART}")
    if not _get(cfg, "wake_word.enabled"):
        return _item("wake", label, "info", i18n.t("setup.wake.installed_disabled", loc), "/wake on")
    return _item("wake", label, "ok", i18n.t("setup.wake.listening", loc))


def _check_computer_use(cfg: dict[str, Any] | None, loc: str) -> dict[str, Any]:
    label = i18n.t("setup.check.computer_use", loc)
    allow = _get(cfg, "command_allowlist")
    if isinstance(allow, list) and any(isinstance(k, str) and k.startswith("cua:") for k in allow):
        return _item("computer_use", label, "ok", i18n.t("setup.computer_use.allowed", loc))
    snippet = "command_allowlist:\n" + "\n".join(f"  - {k}" for k in CUA_KEYS)
    return _item("computer_use", label, "info",
                 i18n.t("setup.computer_use.needs_approval", loc, path=hermes_home() / "config.yaml"),
                 snippet)


def _desktop_toggles(loc: str) -> dict[str, Any]:
    """Paso fijo: el Desktop guarda estos dos toggles adentro de la app y el plugin no puede leerlos."""
    return _item("desktop", i18n.t("setup.check.desktop", loc), "info",
                 i18n.t("setup.desktop.detail", loc))


def _check_gestures(loc: str) -> dict[str, Any]:
    """Ítem informativo: gestos con cámara (opcional, apagados por defecto)."""
    label = i18n.t("setup.check.gestures", loc)
    try:
        from . import ws_server
        enabled = bool(ws_server.load_state().get("gestures", False))
    except Exception:
        enabled = False
    if enabled:
        return _item("gestures", label, "ok", i18n.t("setup.gestures.on", loc))
    return _item("gestures", label, "info",
                 i18n.t("setup.gestures.off", loc),
                 "/hermis gestures on")


def _resolve_locale(locale: str | None, cfg: dict[str, Any] | None) -> str:
    """Idioma del checklist: explícito > override guardado > stt.language > base."""
    if locale:
        forced = i18n.normalize_locale(locale)
        if forced:
            return forced
    override: Any = None
    try:
        from . import ws_server
        override = ws_server.load_state().get("locale")
    except Exception:
        override = None
    return i18n.resolve_locale(override, cfg)


def run_checks(locale: str | None = None) -> list[dict[str, Any]]:
    """Todos los chequeos; un fallo inesperado en uno nunca rompe el resto."""
    cfg = _read_config()
    loc = _resolve_locale(locale, cfg)
    checks = (lambda: _check_overlay(loc), lambda: _check_stt(cfg, loc), lambda: _check_language(cfg, loc),
              lambda: _check_tts(cfg, loc), lambda: _check_wake(cfg, loc), lambda: _check_computer_use(cfg, loc),
              lambda: _check_gestures(loc), lambda: _desktop_toggles(loc))
    items = []
    for check in checks:
        try:
            items.append(check())
        except Exception as exc:
            items.append(_item("error", i18n.t("setup.check.generic", loc), "info",
                               i18n.t("setup.error.generic", loc, error=type(exc).__name__)))
    return items


def surface_data(locale: str | None = None) -> dict[str, Any]:
    loc = _resolve_locale(locale, _read_config())
    items = run_checks(loc)
    pending = sum(1 for it in items if it["status"] == "warn")
    if pending:
        subtitle = i18n.t("setup.subtitle.pending", loc, count=pending)
    elif any(it["status"] == "info" for it in items):
        subtitle = i18n.t("setup.subtitle.info", loc)
    else:
        subtitle = i18n.t("setup.subtitle.ok", loc)
    return {"title": i18n.t("setup.title", loc), "subtitle": subtitle, "items": items}


def as_text(locale: str | None = None) -> str:
    loc = _resolve_locale(locale, _read_config())
    icons = {"ok": i18n.t("setup.status.ok", loc), "warn": i18n.t("setup.status.warn", loc),
             "info": i18n.t("setup.status.info", loc)}
    lines = []
    for it in run_checks(loc):
        lines.append(f"{icons.get(it['status'], '-')} {it['label']}: {it['detail']}")
        if it.get("fix"):
            lines.extend(f"    {line}" for line in it["fix"].splitlines())
    return "\n".join(lines)
