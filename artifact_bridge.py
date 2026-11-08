"""Puente automático de artefactos: respuesta de Hermes → superficie ``artifact``.

El plugin es una INTERFAZ, no una fuente de datos (ver ``BRIEF.md``): Hermes
ya genera artefactos HTML/SVG en sus respuestas (bloques ```html / ```svg).
Con el Modo Piloto Automático activo, este hook ``post_llm_call`` detecta
esos bloques con el mismo criterio que ``apps/desktop/src/lib/artifact-detect.ts``
de Hermes Desktop y los dibuja en el overlay como superficies ``artifact``.
No lanza excepciones nunca y con el modo apagado no hace nada.
"""
from __future__ import annotations

import hashlib
import re
from typing import Any

from . import tools, ws_server

# Umbrales del criterio de artifact-detect.ts (html/svg): un bloque es
# artefacto cuando es inequívocamente un documento HTML o un gráfico SVG
# grande; los fragmentos chicos quedan en el chat.
HTML_DOC_MIN_CHARS = 160
HTML_FRAGMENT_MIN_CHARS = 1200
SVG_MIN_CHARS = 2000

_HTML_LANGUAGES = frozenset({"html", "htm", "xhtml"})
_HTML_DOC_RE = re.compile(r"<!doctype\s+html|<html[\s>]|<head[\s>]|<body[\s>]", re.IGNORECASE)
_HTML_TAG_RE = re.compile(r"<[a-z][a-z0-9-]*(\s[^>]*)?>", re.IGNORECASE)
_SVG_TAG_RE = re.compile(r"<svg[\s>]", re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]*>")
_FENCE_RE = re.compile(r"```([^\n]*)\r?\n(.*?)```", re.DOTALL)


def _sanitize_language(raw: str) -> str:
    """Primer token del tag del fence, en minúsculas (como sanitizeLanguageTag)."""
    token = raw.strip().split()
    return token[0].strip(".,;:!?").lower() if token else ""


def _title_from_tag(content: str, tag: str) -> str:
    match = re.search(rf"<{tag}[^>]*>([\s\S]*?)</{tag}>", content, re.IGNORECASE)
    if not match:
        return ""
    text = _TAG_RE.sub(" ", match.group(1) or "")
    return re.sub(r"\s+", " ", text).strip()[:80]


def detect_artifact(language: str, code: str) -> tuple[str, str] | None:
    """Devuelve ``(kind, title)`` si el bloque califica como artefacto, o None."""
    trimmed = code.strip()
    if not trimmed:
        return None
    if language in _HTML_LANGUAGES:
        is_doc = bool(_HTML_DOC_RE.search(trimmed))
        if (is_doc and len(trimmed) >= HTML_DOC_MIN_CHARS) or (
            not is_doc and len(trimmed) >= HTML_FRAGMENT_MIN_CHARS and _HTML_TAG_RE.search(trimmed)
        ):
            title = _title_from_tag(trimmed, "title") or _title_from_tag(trimmed, "h1") or "HTML"
            return ("html", title)
        return None
    if language == "svg":
        if len(trimmed) >= SVG_MIN_CHARS and _SVG_TAG_RE.search(trimmed):
            return ("svg", _title_from_tag(trimmed, "title") or "SVG")
        return None
    return None


def artifact_id(kind: str, title: str) -> str:
    """Id estable: una versión nueva del mismo gráfico reemplaza a la anterior."""
    digest = hashlib.sha256(f"{kind}:{title}".encode("utf-8")).hexdigest()[:8]
    return f"artifact-{digest}"


def post_llm_call(**kwargs: Any) -> None:
    """Dibuja los bloques ```html / ```svg de la respuesta como superficies artifact."""
    try:
        response = kwargs.get("assistant_response")
        if not isinstance(response, str) or not response.strip():
            return
        if not ws_server.load_state().get("autopilot", False):
            return
        for raw_language, body in _FENCE_RE.findall(response):
            detected = detect_artifact(_sanitize_language(raw_language), body)
            if detected is None:
                continue
            kind, title = detected
            tools.render_surface({
                "surface": "artifact",
                "id": artifact_id(kind, title),
                "data": {"kind": kind, "title": title, "content": body.strip()},
            })
    except Exception:
        # Un puente caído nunca bloquea ni transforma la respuesta del agente.
        return
