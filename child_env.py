"""Entorno mínimo para los procesos hijos del plugin.

Hermes carga en ``os.environ`` las API keys de los proveedores; ni ``npm``,
ni el overlay Electron, ni las apps que abre ``launch_app`` las necesitan.
``minimal_env`` copia solo una allowlist de variables del sistema, del perfil
de usuario y de las overrides de gateway que el overlay lee del entorno. La
comparación es case-insensitive: en Windows ``Path`` y ``PATH`` son la misma
variable.
"""
from __future__ import annotations

import os
from typing import Iterable

_ALLOWED = frozenset({
    # sistema (npm en Windows es npm.cmd y necesita ComSpec)
    "PATH", "PATHEXT", "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "COMSPEC",
    "TEMP", "TMP",
    # usuario
    "USERPROFILE", "HOMEDRIVE", "HOMEPATH", "USERNAME", "COMPUTERNAME",
    # carpetas de programa y datos
    "LOCALAPPDATA", "APPDATA", "PROGRAMDATA", "PROGRAMFILES",
    "PROGRAMFILES(X86)", "PROGRAMW6432", "COMMONPROGRAMFILES",
    "COMMONPROGRAMFILES(X86)",
    # procesador
    "NUMBER_OF_PROCESSORS", "PROCESSOR_ARCHITECTURE", "OS",
    # dónde vive Hermes (el overlay busca ahí el pipe de control del gateway)
    "HERMES_HOME",
    # red
    "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "NODE_EXTRA_CA_CERTS",
})


# Overrides del gateway que lee el overlay (overlay/gateway_client.js). Incluyen
# tokens de Hermes: solo se pasan al proceso del overlay (``npm start``), nunca
# a ``npm ci``, a PowerShell ni a las apps que abre ``launch_app``.
OVERLAY_GATEWAY_VARS = (
    "HERMES_GATEWAY_WS_URL", "HERMES_GATEWAY_URL", "HERMES_GATEWAY_TOKEN",
    "HERMES_API_TOKEN", "HERMES_API_PORT", "HERMES_GATEWAY_PORT",
)


def minimal_env(extra: Iterable[str] | None = None) -> dict[str, str]:
    """Variables de ``os.environ`` dentro de la allowlist (case-insensitive).

    ``extra`` suma nombres a la allowlist de esa llamada; nunca keys ni tokens
    de proveedor.
    """
    allowed = _ALLOWED
    if extra:
        allowed = _ALLOWED | {str(name).upper() for name in extra}
    return {key: value for key, value in os.environ.items() if key.upper() in allowed}
