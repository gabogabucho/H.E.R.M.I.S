"""H.E.R.M.I.S — el escritorio como OS para agentes (plugin de Hermes).

Día 1–2:
- Servidor WebSocket local (127.0.0.1 + token) que consume el overlay
  Electron: el agente manda datos, el overlay dibuja superficies.
- Tools ``autopilot``, ``render_surface``, ``close_surface`` y ``list_surfaces``.
- Hook ``pre_llm_call`` con instrucciones del Modo Piloto Automático y
  contexto en caché de las superficies activas en pantalla.

Protocolo ``x-lumen-desktop v2``: el agente nunca manda HTML, solo datos.
Más en ``BRIEF.md`` y ``docs/RESEARCH.md``.
"""
from __future__ import annotations

import logging

from . import schemas
from . import tools
from . import ws_server
from . import commands

logger = logging.getLogger("hermis")


def register(ctx) -> None:
    """Levanta el WS del overlay y registra las tools y hooks de H.E.R.M.I.S."""
    try:
        ws_server.start(getattr(ctx, "plugin_data_dir", None))
    except Exception as exc:  # el overlay es opcional: las tools avisan si no hay clientes
        logger.warning("no se pudo levantar el WS del overlay: %s", exc)
    ctx.register_tool(name="autopilot", toolset="hermis",
                      schema=schemas.AUTOPILOT_SCHEMA, handler=tools.autopilot)
    ctx.register_tool(name="render_surface", toolset="hermis",
                      schema=schemas.RENDER_SURFACE_SCHEMA, handler=tools.render_surface)
    ctx.register_tool(name="close_surface", toolset="hermis",
                      schema=schemas.CLOSE_SURFACE_SCHEMA, handler=tools.close_surface)
    ctx.register_tool(name="list_surfaces", toolset="hermis",
                      schema=schemas.LIST_SURFACES_SCHEMA, handler=tools.list_surfaces)
    ctx.register_tool(name="layout_windows", toolset="hermis",
                      schema=schemas.LAYOUT_WINDOWS_SCHEMA, handler=tools.layout_windows)
    ctx.register_tool(name="launch_app", toolset="hermis",
                      schema=schemas.LAUNCH_APP_SCHEMA, handler=tools.launch_app)
    ctx.register_hook("pre_llm_call", tools.pre_llm_call)
    ctx.register_command(
        name="hermis", handler=commands.handle,
        description="Show H.E.R.M.I.S status, switch autopilot, or check installation.",
        args_hint="[status|on|off|check]",
    )
