"""Política de aprobación de ``launch_app``: función pura, sin efectos.

La tool rechaza por su cuenta shells, intérpretes y rutas (defensa en
profundidad: no depende del hook). Este módulo decide, para el hook
``pre_tool_call`` de Hermes, qué hace falta por llamada:

- shell, intérprete o ruta → ``{"action": "block", "message": ...}`` (veto: el
  mensaje pasa a ser el resultado de la tool y nada se ejecuta);
- app de la allowlist sin argumentos, o un navegador de la allowlist con
  exactamente una URL http/https → ``None`` (no se pregunta);
- todo lo demás → ``{"action": "approve", "message": ...}`` (Hermes le pide
  confirmación al usuario antes de ejecutar la tool).
"""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

# Shells, intérpretes y script hosts que launch_app nunca abre. Se compara el
# nombre pedido Y el ejecutable resuelto (basename sin extensión, minúsculas):
# un alias que resuelva a uno de estos binarios también se rechaza.
BLOCKED_EXECUTABLES = frozenset({
    "cmd", "powershell", "powershell_ise", "pwsh", "wt", "windowsterminal", "conhost", "wscript",
    "cscript", "mshta", "rundll32", "regsvr32", "msiexec", "reg", "regedit",
    "schtasks", "sc", "certutil", "bitsadmin", "wmic", "bash", "wsl", "sh",
    "python", "pythonw", "py", "node", "deno", "bun", "java", "javaw", "ruby",
    "perl", "php",
})

# Alias que quedan después de sacar los de shell: apps que se abren solas,
# sin argumentos y sin preguntar.
SAFE_LAUNCH_APPS = frozenset({
    "notepad", "bloc de notas", "notas",
    "calc", "calculator", "calculadora",
    "explorer", "explorador", "explorador de archivos", "file explorer",
    "paint", "mspaint",
    "code", "vscode", "visual studio code",
    "excel", "microsoft excel",
    "word", "microsoft word",
    "powerpoint",
    "spotify",
})

# Navegadores de la allowlist: abren sin preguntar solo con exactamente un
# argumento que sea una URL http/https válida.
BROWSER_ALIASES = frozenset({
    "chrome", "google chrome", "edge", "microsoft edge", "firefox",
})

_PATH_CHARS = ("/", "\\", ":")


def is_path_like(app: str) -> bool:
    """True si trae una ruta o URL: launch_app solo acepta nombres."""
    return any(ch in app for ch in _PATH_CHARS)


def _exe_base(name: str) -> str:
    """Basename sin extensión, en minúsculas ('C:\\x\\PS.exe' → 'ps')."""
    base = str(name).replace("\\", "/").rstrip("/").rsplit("/", 1)[-1].strip().lower()
    if "." in base:
        base = base.rsplit(".", 1)[0]
    return base


def _blocked_executable(name: str) -> bool:
    base = _exe_base(name)
    # Python's versioned and windowless executable names are still interpreters.
    return base in BLOCKED_EXECUTABLES or re.fullmatch(r"pythonw?(?:[0-9]+(?:\.[0-9]+)*)?w?", base) is not None


def reject_reason(app: str, resolved: str | None = None) -> str | None:
    """Razón de rechazo para ``launch_app``, o None si el nombre es aceptable."""
    name = str(app).strip()
    if not name:
        return None  # una app vacía la rechaza la tool con su propio error
    if is_path_like(name):
        return (f"launch_app solo abre aplicaciones por su nombre; no acepta "
                f"rutas ni URLs: {name!r}")
    if _blocked_executable(name) or (
        resolved is not None and _blocked_executable(resolved)
    ):
        return (f"launch_app no abre shells, intérpretes ni script hosts "
                f"(para ejecutar comandos, usa la terminal de Hermes con su "
                f"aprobación): {name!r}")
    return None


# Palabras que delatan una consola en el nombre de una app del menú Inicio
# ("Windows PowerShell", "Terminal", "Símbolo del sistema", "Ubuntu"...).
_CONSOLE_WORDS = BLOCKED_EXECUTABLES | frozenset({
    "terminal", "prompt", "símbolo", "simbolo", "ubuntu", "debian", "kali",
    "opensuse", "git",
})


def reject_start_app(name: str, aumid: str) -> str | None:
    """Razón de rechazo para una app del menú Inicio (nombre + AppID del sistema).

    Las apps de la Store se abren sin argumentos, pero una consola igual sirve
    para ejecutar comandos: se rechaza por nombre y por el ejecutable del AppID.
    """
    words = set(re.split(r"[^\wáéíóúñ]+", str(name).lower()))
    aumid_l = str(aumid).lower()
    if (words & _CONSOLE_WORDS or any(_blocked_executable(word) for word in words) or _blocked_executable(aumid_l)
            or "windowsterminal" in aumid_l or "powershell" in aumid_l):
        return (f"launch_app no abre consolas ni shells (para ejecutar comandos, "
                f"usa la terminal de Hermes con su aprobación): {name!r}")
    return None


def is_http_url(arg: str) -> bool:
    """True si el argumento es una URL http/https con scheme y netloc válidos."""
    try:
        parsed = urlparse(str(arg).strip())
    except ValueError:
        return False
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def _resolve(name: str) -> str | None:
    """Ejecutable resuelto para el chequeo del hook (import tardío: ciclo)."""
    try:
        from . import win32_windows
        return win32_windows.resolve_executable(name)
    except Exception:
        return None


def launch_policy(args: dict[str, Any] | None) -> dict[str, str] | None:
    """Directiva de Hermes para una llamada a ``launch_app`` (ver docstring)."""
    if not isinstance(args, dict):
        return None
    app = args.get("app")
    if not isinstance(app, str) or not app.strip():
        return None  # la tool devuelve su propio error de validación
    name = app.strip()
    reason = reject_reason(name, _resolve(name))
    if reason:
        return {"action": "block", "message": reason}
    raw = args.get("args")
    clean = ([str(a) for a in raw if isinstance(a, str) and a.strip()]
             if isinstance(raw, list) else [])
    key = name.lower()
    if not clean and key in SAFE_LAUNCH_APPS:
        return None
    if key in BROWSER_ALIASES and len(clean) == 1 and is_http_url(clean[0]):
        return None
    return {"action": "approve", "message": f"H.E.R.M.I.S quiere abrir {' '.join([name, *clean])}"}
