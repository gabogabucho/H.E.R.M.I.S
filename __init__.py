"""H.E.R.M.I.S — el escritorio como OS para agentes (plugin de Hermes).

Día 1 (esqueleto):
- Servidor WebSocket local (127.0.0.1 + token) que consume el overlay
  Electron: el agente manda datos, el overlay dibuja superficies.
- Tool ``render_surface`` con las superficies ``notification`` y
  ``document``.

Protocolo ``x-lumen-desktop v2``: el agente nunca manda HTML, solo datos.
Más en ``BRIEF.md`` y ``docs/RESEARCH.md``.
"""
from __future__ import annotations

import logging

from . import schemas
from . import tools
from . import ws_server

logger = logging.getLogger("hermis")


def register(ctx) -> None:
    """Levanta el WS del overlay y registra las tools de Día 1."""
    try:
        ws_server.start()
    except Exception as exc:  # el overlay es opcional: render_surface avisa solo
        logger.warning("no se pudo levantar el WS del overlay: %s", exc)
    ctx.register_tool(name="render_surface", toolset="hermis",
                      schema=schemas.RENDER_SURFACE_SCHEMA, handler=tools.render_surface)
