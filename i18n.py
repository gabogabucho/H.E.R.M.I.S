"""Catálogo de mensajes de H.E.R.M.I.S (única fuente de verdad: es + en).

``messages/es.json`` y ``messages/en.json`` son las dos caras de un mismo
catálogo: las lee el plugin (Python) y, por el WebSocket local, el overlay
(JS). Agregar un texto nuevo significa agregar la clave en los dos idiomas a
la vez; ``tests/test_i18n.py`` falla si falta una.

El idioma de la interfaz se resuelve en este orden:

1. el override manual (``/hermis lang es|en``, guardado en ``state.json``);
2. ``stt.language`` de la ``config.yaml`` de Hermes (el idioma con el que el
   usuario le habla al agente);
3. ``BASE_LOCALE`` (el idioma base del producto: inglés, como Hermes).

Ninguno de los dos primeros es obligatorio: si falta la config o no se puede
leer, la interfaz sigue funcionando en el idioma base.
"""
from __future__ import annotations

import json
import os
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any

CATALOG_DIR = Path(__file__).resolve().parent / "messages"
SUPPORTED: tuple[str, ...] = ("es", "en")
# Idioma base: el mismo que Hermes usa por defecto (stt.language) y el idioma
# del README. El español se activa con stt.language: es o con /hermis lang es.
BASE_LOCALE = "en"
FALLBACK_LOCALE = "en"


def normalize_locale(value: Any) -> str | None:
    """'es', 'es-AR', 'EN_us' → 'es' / 'en'; None si no es un idioma soportado."""
    if not isinstance(value, str):
        return None
    raw = value.strip().lower().replace("_", "-")
    if not raw:
        return None
    base = raw.split("-")[0]
    return base if base in SUPPORTED else None


@lru_cache(maxsize=None)
def _catalog(locale: str) -> dict[str, str]:
    """Catálogo plano {clave: texto} de un idioma; vacío si el archivo falla."""
    try:
        raw = json.loads((CATALOG_DIR / f"{locale}.json").read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(raw, dict):
        return {}
    return {
        key: value
        for key, value in raw.items()
        if isinstance(key, str) and isinstance(value, str) and not key.startswith("_")
    }


def catalog(locale: Any = None) -> dict[str, str]:
    """Catálogo completo de un idioma (con fallback al base si no existe)."""
    loc = normalize_locale(locale) or BASE_LOCALE
    data = _catalog(loc)
    if not data:
        data = _catalog(FALLBACK_LOCALE)
    return data


def overlay_strings(locale: Any = None) -> dict[str, str]:
    """Solo las claves que el overlay necesita (las que empieza con 'overlay.')."""
    return {k: v for k, v in catalog(locale).items() if k.startswith("overlay.")}


def t(key: str, locale: Any = None, **kwargs: Any) -> str:
    """Texto de una clave en el idioma pedido.

    Si la clave no existe, devuelve la propia clave (visible, pero nunca
    rompe la interfaz). Los placeholders van como argumentos con nombre:
    ``t("setup.stt.cloud_provider", "en", provider="elevenlabs")``.
    """
    loc = normalize_locale(locale) or get_locale()
    text = _catalog(loc).get(key)
    if text is None:
        text = _catalog(FALLBACK_LOCALE).get(key, key)
    if kwargs:
        try:
            return text.format(**kwargs)
        except (KeyError, IndexError, ValueError):
            return text
    return text


def hermes_home() -> Path:
    """Directorio de Hermes (misma regla que el resto del plugin)."""
    home = os.environ.get("HERMES_HOME")
    if home:
        return Path(home)
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local")) / "hermes"
    return Path.home() / ".hermes"


def read_hermes_config() -> dict[str, Any] | None:
    """config.yaml de Hermes, o None si no se puede leer."""
    try:
        import yaml  # viene con Hermes; si falta, se degrada al idioma base

        raw = yaml.safe_load((hermes_home() / "config.yaml").read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return None


def config_value(cfg: dict[str, Any] | None, dotted: str) -> Any:
    """Lee 'stt.language' de un dict de config (None si no existe)."""
    node: Any = cfg
    for part in dotted.split("."):
        if not isinstance(node, dict):
            return None
        node = node.get(part)
    return node


def resolve_locale(override: Any = None, config: dict[str, Any] | None = None) -> str:
    """Idioma de la interfaz: override manual > stt.language de Hermes > base."""
    forced = normalize_locale(override)
    if forced:
        return forced
    if config is None:
        config = read_hermes_config()
    from_hermes = normalize_locale(config_value(config, "stt.language"))
    if from_hermes:
        return from_hermes
    return BASE_LOCALE


def get_locale() -> str:
    """Idioma efectivo: override guardado en state.json > config de Hermes > base."""
    override: Any = None
    try:
        from . import ws_server  # import diferido: ws_server usa este módulo

        override = ws_server.load_state().get("locale")
    except Exception:
        override = None
    return resolve_locale(override)
