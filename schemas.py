"""Schemas JSON de las tools de H.E.R.M.I.S (lo que lee el LLM).

Mismo patrón que los plugins bundled: ``{"name", "description",
"parameters"}`` con ``additionalProperties: false``. Las descripciones son
las que deciden si el agente elige la tool, así que llevan el contrato del
protocolo ``x-lumen-desktop v2`` inline.
"""
from __future__ import annotations

from typing import Any


def _schema(name: str, description: str, properties: dict[str, Any],
            required: list[str] | None = None) -> dict[str, Any]:
    params: dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        params["required"] = required
    params["additionalProperties"] = False
    return {"name": name, "description": description, "parameters": params}


RENDER_SURFACE_SCHEMA = _schema(
    "render_surface",
    "Draw a data surface floating over the user's Windows desktop (transparent "
    "always-on-top overlay; clicks pass through where nothing is drawn). Send "
    "data, not HTML — the overlay has the components (x-lumen-desktop v2). "
    "Surfaces: 'notification' with data {text, level: 'success'|'info'|'error'} "
    "and 'document' with data {title, body_markdown}. Returns JSON: ok, surface, "
    "delivered (overlay clients the render was pushed to), overlay_connected.",
    {
        "surface": {"type": "string", "enum": ["notification", "document"],
                    "description": "Which overlay component draws the data."},
        "data": {"type": "object",
                 "description": ("Payload for the surface: notification = {text, "
                                 "level}; document = {title, body_markdown}.")},
    },
    required=["surface", "data"],
)
