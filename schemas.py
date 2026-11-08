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


AUTOPILOT_SCHEMA = _schema(
    "autopilot",
    "Activate or deactivate H.E.R.M.I.S Autopilot Mode ('on' | 'off'). Call with "
    "state='on' when the user says 'modo piloto automático', 'activa el piloto "
    "automático', 'autopilot mode', or 'enable autopilot', and with state='off' when "
    "they say 'sal del piloto automático', 'desactiva el piloto automático', or "
    "'exit autopilot'. When 'on', "
    "the desktop overlay morphs into the floating orb and Hermes speaks short "
    "voice replies while drawing rich data surfaces on screen via render_surface. "
    "When 'off', clears open surfaces and returns to normal mode.",
    {
        "state": {
            "type": "string",
            "enum": ["on", "off"],
            "description": "'on' to enter Autopilot Mode; 'off' to exit and clear surfaces.",
        },
    },
    required=["state"],
)

RENDER_SURFACE_SCHEMA = _schema(
    "render_surface",
    "Draw a data surface floating over the user's Windows desktop (transparent "
    "always-on-top overlay; clicks pass through where nothing is drawn). Send "
    "data, not HTML — the overlay has the components (x-lumen-desktop v2). "
    "Surfaces: "
    "'notification' {text, level?: 'info'|'success'|'error', opacity?: 20..98, theme?: 'light'|'dark'}; "
    "'document' {title?, body_markdown?}; "
    "'email_list' {title?, items: [{id?, from, subject, snippet?, date?, body_markdown?}]}; "
    "'table' {title?, columns: [str], rows: [[cell]|object]}; "
    "'cards' {title?, items: [{title, subtitle?, body?, badge?}]}; "
    "'web' {title?, url: 'https://...'}; "
    "'image' {title?, src|url, alt?}; "
    "'custom' {title?, html} (sandboxed emergency fallback). "
    "Returns JSON: ok, id (for persistent surfaces), surface, delivered, overlay_connected.",
    {
        "surface": {
            "type": "string",
            "enum": [
                "notification",
                "document",
                "email_list",
                "table",
                "cards",
                "web",
                "image",
                "custom",
            ],
            "description": "Which overlay component draws the data.",
        },
        "data": {
            "type": "object",
            "description": "Structured payload matching the chosen surface contract.",
        },
        "id": {
            "type": "string",
            "description": "Optional surface id to create or update in place.",
        },
    },
    required=["surface", "data"],
)

CLOSE_SURFACE_SCHEMA = _schema(
    "close_surface",
    "Close an open floating surface on the desktop overlay by its id (e.g. "
    "'document-1', 'email_list-1'), or pass 'all' to close all open surfaces.",
    {
        "id": {
            "type": "string",
            "description": "Surface id to close, or 'all' to close every open surface.",
        },
    },
    required=["id"],
)

LIST_SURFACES_SCHEMA = _schema(
    "list_surfaces",
    "List all currently open floating surfaces on the desktop overlay and "
    "whether Autopilot Mode is active.",
    {},
)

LAYOUT_WINDOWS_SCHEMA = _schema(
    "layout_windows",
    "Arrange, focus, or maximize real Windows desktop application windows by "
    "matching their title or app name (e.g. 'pon Excel a la izquierda y Chrome a la derecha', "
    "'put Notepad on the left and PowerShell on the right', 'maximiza Chrome', 'enfoca VS Code'). "
    "Layouts: 'split' (side-by-side columns), 'grid' (2x2 or NxM grid), 'maximize', "
    "'focus' (bring to front), 'minimize_others' (minimize everything except matched windows).",
    {
        "layout": {
            "type": "string",
            "enum": ["split", "grid", "maximize", "focus", "minimize_others"],
            "description": "Window arrangement mode to apply on the primary monitor work area.",
        },
        "windows": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Window title or app name substrings in the desired order (e.g. ['Excel', 'Chrome']).",
        },
    },
    required=["layout", "windows"],
)

LAUNCH_APP_SCHEMA = _schema(
    "launch_app",
    "Launch a desktop application on Windows by name or alias without using a shell "
    "(e.g. 'notepad' / 'bloc de notas', 'calc' / 'calculadora', 'explorer' / 'explorador', "
    "'chrome', 'edge', 'code' / 'vscode', 'excel', 'word', 'powershell', 'spotify').",
    {
        "app": {
            "type": "string",
            "description": "Application name or alias to launch.",
        },
        "args": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Optional command-line arguments (e.g. file path or URL).",
        },
    },
    required=["app"],
)
