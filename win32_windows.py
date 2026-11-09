"""Control de ventanas reales y lanzamiento seguro de aplicaciones en Windows (Día 3).

Usa ``ctypes.windll.user32`` (stdlib) en Windows para no requerir dependencias
nativas externas (``pywin32``) que rompan la validación en Linux/CI, y degrada
limpiamente con un mensaje claro fuera de Windows. Nunca usa ``shell=True``.
"""
from __future__ import annotations

import ctypes
import json
from ctypes import wintypes
import math
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

LAYOUTS = ("split", "grid", "maximize", "focus", "minimize_others")

# Títulos de ventanas del sistema o del propio overlay que nunca deben moverse.
_IGNORED_TITLES = frozenset({
    "program manager",
    "windows input experience",
    "microsoft text input application",
    "h.e.r.m.i.s overlay",
    "settings",
    "configuración",
})

# Alias seguros en español neutro e inglés hacia ejecutables estándar.
APP_ALIASES: dict[str, str] = {
    "notepad": "notepad.exe",
    "bloc de notas": "notepad.exe",
    "notas": "notepad.exe",
    "calc": "calc.exe",
    "calculator": "calc.exe",
    "calculadora": "calc.exe",
    "explorer": "explorer.exe",
    "explorador": "explorer.exe",
    "explorador de archivos": "explorer.exe",
    "file explorer": "explorer.exe",
    "paint": "mspaint.exe",
    "mspaint": "mspaint.exe",
    "cmd": "cmd.exe",
    "terminal": "wt.exe",
    "windows terminal": "wt.exe",
    "powershell": "powershell.exe",
    "code": "code",
    "vscode": "code",
    "visual studio code": "code",
    "chrome": "chrome.exe",
    "google chrome": "chrome.exe",
    "edge": "msedge.exe",
    "microsoft edge": "msedge.exe",
    "firefox": "firefox.exe",
    "excel": "excel.exe",
    "microsoft excel": "excel.exe",
    "word": "winword.exe",
    "microsoft word": "winword.exe",
    "powerpoint": "powerpnt.exe",
    "spotify": "spotify.exe",
}

# Constantes Win32
_SW_RESTORE = 9
_SW_MAXIMIZE = 3
_SW_MINIMIZE = 6
_SW_SHOW = 5
_SWP_NOSIZE = 0x0001
_SWP_NOMOVE = 0x0002
_SWP_NOZORDER = 0x0004
_SWP_SHOWWINDOW = 0x0040
_HWND_TOPMOST = -1
_HWND_NOTOPMOST = -2
# Cuánto esperamos a que aparezca la ventana de una app recién lanzada.
_LAUNCH_WAIT_S = 5.0
_LAUNCH_POLL_S = 0.25
_SPI_GETWORKAREA = 0x0030
_GWL_EXSTYLE = -20
_WS_EX_TOOLWINDOW = 0x00000080
_DWMWA_CLOAKED = 14


def is_windows() -> bool:
    return sys.platform == "win32"


def get_work_area() -> tuple[int, int, int, int]:
    """Devuelve ``(x, y, width, height)`` del área de trabajo del monitor principal."""
    if not is_windows():
        return (0, 0, 1920, 1040)
    try:
        rect = wintypes.RECT()
        ok = ctypes.windll.user32.SystemParametersInfoW(
            _SPI_GETWORKAREA, 0, ctypes.byref(rect), 0
        )
        if ok:
            w = max(640, int(rect.right - rect.left))
            h = max(480, int(rect.bottom - rect.top))
            return (int(rect.left), int(rect.top), w, h)
    except Exception:
        pass
    return (0, 0, 1920, 1040)


def _is_cloaked(hwnd: int) -> bool:
    if not is_windows():
        return False
    try:
        cloaked = ctypes.c_int(0)
        res = ctypes.windll.dwmapi.DwmGetWindowAttribute(
            wintypes.HWND(hwnd),
            wintypes.DWORD(_DWMWA_CLOAKED),
            ctypes.byref(cloaked),
            ctypes.sizeof(cloaked),
        )
        return res == 0 and cloaked.value != 0
    except Exception:
        return False


def list_open_windows() -> list[dict[str, Any]]:
    """Lista las ventanas visibles de usuario en el escritorio."""
    if not is_windows():
        return []
    user32 = ctypes.windll.user32
    results: list[dict[str, Any]] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def _enum_proc(hwnd: int, _lparam: int) -> bool:
        try:
            if not user32.IsWindowVisible(hwnd):
                return True
            length = user32.GetWindowTextLengthW(hwnd)
            if length <= 0:
                return True
            ex_style = user32.GetWindowLongW(hwnd, _GWL_EXSTYLE)
            if ex_style & _WS_EX_TOOLWINDOW:
                return True
            if _is_cloaked(hwnd):
                return True
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            title = buf.value.strip()
            if not title or title.lower() in _IGNORED_TITLES:
                return True
            rect = wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(rect))
            width = int(rect.right - rect.left)
            height = int(rect.bottom - rect.top)
            if width <= 10 or height <= 10:
                return True
            results.append({
                "hwnd": int(hwnd),
                "title": title,
                "x": int(rect.left),
                "y": int(rect.top),
                "width": width,
                "height": height,
            })
        except Exception:
            pass
        return True

    try:
        user32.EnumWindows(_enum_proc, 0)
    except Exception:
        return []
    return results


def _bring_to_front(hwnd: int) -> bool:
    """Trae una ventana al frente aunque el llamador corra en segundo plano.

    Windows rechaza en silencio ``SetForegroundWindow`` desde un proceso que no
    tiene el foco (el gateway de Hermes). Engancharse a la entrada del hilo de la
    ventana activa lo habilita; el salto TOPMOST → NOTOPMOST sube la ventana en el
    orden Z aunque Windows no ceda el foco. No simula teclas (Alt abre menús).
    Devuelve True si la ventana quedó como ventana activa.
    """
    if not is_windows():
        return False
    try:
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        target = wintypes.HWND(hwnd)
        user32.ShowWindow(target, _SW_RESTORE if user32.IsIconic(target) else _SW_SHOW)
        if user32.SetForegroundWindow(target) and user32.GetForegroundWindow() == hwnd:
            return True
        foreground = user32.GetForegroundWindow()
        fg_thread = user32.GetWindowThreadProcessId(foreground, None) if foreground else 0
        own_thread = kernel32.GetCurrentThreadId()
        attached = bool(fg_thread and fg_thread != own_thread
                        and user32.AttachThreadInput(own_thread, fg_thread, True))
        try:
            flags = _SWP_NOMOVE | _SWP_NOSIZE | _SWP_SHOWWINDOW
            user32.SetWindowPos(target, wintypes.HWND(_HWND_TOPMOST), 0, 0, 0, 0, flags)
            user32.SetWindowPos(target, wintypes.HWND(_HWND_NOTOPMOST), 0, 0, 0, 0, flags)
            user32.BringWindowToTop(target)
            user32.SetForegroundWindow(target)
        finally:
            if attached:
                user32.AttachThreadInput(own_thread, fg_thread, False)
        return user32.GetForegroundWindow() == hwnd
    except Exception:
        return False


def _window_snapshot() -> dict[int, str]:
    """``{hwnd: título}`` de las ventanas de usuario visibles ahora."""
    return {w["hwnd"]: w["title"] for w in list_open_windows()}


def _bring_launched_window_to_front(before: dict[int, str], app_name: str) -> dict[str, Any]:
    """Busca la ventana de una app recién lanzada y la trae al frente.

    No se busca por PID: la Calculadora (UWP) vive en ApplicationFrameHost y
    Chrome suele reusar su proceso. Orden: ventana nueva → ventana cuyo título
    cambió (pestaña nueva en un Chrome abierto) → título que contiene el nombre.
    """
    name = app_name.strip().lower()
    # Si la app ya estaba abierta casi nunca aparece una ventana nueva: no hace
    # falta esperar los 5 s enteros.
    already_open = bool(name) and any(name in title.lower() for title in before.values())
    deadline = time.monotonic() + (min(_LAUNCH_WAIT_S, 1.5) if already_open else _LAUNCH_WAIT_S)
    after = before
    while time.monotonic() < deadline:
        time.sleep(_LAUNCH_POLL_S)
        after = _window_snapshot()
        new = [h for h in after if h not in before]
        if new:
            hwnd = new[-1]
            return {"focused": _bring_to_front(hwnd), "window": after[hwnd]}
    changed = [h for h, title in after.items() if h in before and before[h] != title]
    named = [h for h, title in after.items() if name and name in title.lower()]
    named_changed = [h for h in named if h in changed]
    # El nombre manda: un título que cambió en otra app (una pestaña que se
    # actualiza sola) no le puede ganar a la ventana de la app pedida.
    for candidates in (named_changed, named, changed):
        if candidates:
            hwnd = candidates[0]
            return {"focused": _bring_to_front(hwnd), "window": after[hwnd]}
    return {"focused": False}


def _move_window(hwnd: int, x: int, y: int, width: int, height: int) -> bool:
    if not is_windows():
        return False
    try:
        user32 = ctypes.windll.user32
        user32.ShowWindow(wintypes.HWND(hwnd), _SW_RESTORE)
        ok = user32.SetWindowPos(
            wintypes.HWND(hwnd),
            0,
            int(x),
            int(y),
            int(width),
            int(height),
            _SWP_NOZORDER | _SWP_SHOWWINDOW,
        )
        _bring_to_front(hwnd)
        return bool(ok)
    except Exception:
        return False


def _focus_window(hwnd: int) -> bool:
    if not is_windows():
        return False
    _bring_to_front(hwnd)
    return True


def _maximize_window(hwnd: int) -> bool:
    if not is_windows():
        return False
    try:
        user32 = ctypes.windll.user32
        user32.ShowWindow(wintypes.HWND(hwnd), _SW_MAXIMIZE)
        _bring_to_front(hwnd)
        return True
    except Exception:
        return False


def _minimize_window(hwnd: int) -> bool:
    if not is_windows():
        return False
    try:
        return bool(ctypes.windll.user32.ShowWindow(wintypes.HWND(hwnd), _SW_MINIMIZE))
    except Exception:
        return False


_WINDOW_SYNONYMS: dict[str, tuple[str, ...]] = {
    "notepad": ("notepad", "bloc de notas", "sin título", "untitled"),
    "bloc de notas": ("bloc de notas", "notepad", "sin título", "untitled"),
    "notas": ("bloc de notas", "notepad", "notas", "sin título"),
    "calc": ("calculadora", "calculator", "calc"),
    "calculator": ("calculator", "calculadora"),
    "calculadora": ("calculadora", "calculator"),
    "explorer": ("explorador", "file explorer", "explorer"),
    "explorador": ("explorador", "file explorer", "explorer"),
    "powershell": ("powershell", "windows powershell", "terminal"),
    "code": ("visual studio code", "vscode", "code"),
    "vscode": ("visual studio code", "vscode"),
}


def match_windows(queries: list[str], available: list[dict[str, Any]] | None = None) -> tuple[list[dict[str, Any]], list[str]]:
    """Resuelve cada query por coincidencia parcial (case-insensitive) o sinónimo bilingüe en el título."""
    pool = list(available) if available is not None else list_open_windows()
    matched: list[dict[str, Any]] = []
    used_hwnds: set[int] = set()
    unmatched: list[str] = []

    for q in queries:
        needle = q.strip().lower()
        if not needle:
            continue
        candidates = _WINDOW_SYNONYMS.get(needle, (needle,))
        found = next(
            (
                w for w in pool
                if w["hwnd"] not in used_hwnds
                and any(cand in w["title"].lower() for cand in candidates)
            ),
            None,
        )
        if found is not None:
            matched.append(found)
            used_hwnds.add(found["hwnd"])
        else:
            unmatched.append(q)
    return matched, unmatched


def apply_layout(layout: str, queries: list[str]) -> dict[str, Any]:
    """Aplica ``layout`` ('split'|'grid'|'maximize'|'focus'|'minimize_others') a las ventanas indicadas."""
    if not is_windows():
        return {
            "ok": False,
            "error": "unsupported_platform",
            "message": "layout_windows requiere Windows (Win32 API)",
        }
    all_windows = list_open_windows()
    matched, unmatched = match_windows(queries, all_windows)
    if not matched:
        return {
            "ok": False,
            "error": "no_matching_windows",
            "message": f"No se encontraron ventanas que coincidan con: {', '.join(queries)}",
            "available_windows": [w["title"] for w in all_windows[:15]],
        }

    wx, wy, ww, wh = get_work_area()
    placed: list[dict[str, Any]] = []

    if layout == "split":
        n = len(matched)
        col_w = ww // n
        for idx, win in enumerate(matched):
            x = wx + idx * col_w
            w = ww - idx * col_w if idx == n - 1 else col_w
            _move_window(win["hwnd"], x, wy, w, wh)
            placed.append({"title": win["title"], "x": x, "y": wy, "width": w, "height": wh})
    elif layout == "grid":
        n = len(matched)
        cols = max(1, math.ceil(math.sqrt(n)))
        rows = max(1, math.ceil(n / cols))
        cell_w = ww // cols
        cell_h = wh // rows
        for idx, win in enumerate(matched):
            r = idx // cols
            c = idx % cols
            x = wx + c * cell_w
            y = wy + r * cell_h
            w = ww - c * cell_w if c == cols - 1 else cell_w
            h = wh - r * cell_h if r == rows - 1 else cell_h
            _move_window(win["hwnd"], x, y, w, h)
            placed.append({"title": win["title"], "x": x, "y": y, "width": w, "height": h})
    elif layout == "maximize":
        for win in matched:
            _maximize_window(win["hwnd"])
            placed.append({"title": win["title"], "state": "maximized"})
    elif layout == "focus":
        for win in matched:
            _focus_window(win["hwnd"])
            placed.append({"title": win["title"], "state": "focused"})
    elif layout == "minimize_others":
        keep_hwnds = {w["hwnd"] for w in matched}
        minimized_count = 0
        for win in all_windows:
            if win["hwnd"] not in keep_hwnds:
                if _minimize_window(win["hwnd"]):
                    minimized_count += 1
        for win in matched:
            _focus_window(win["hwnd"])
            placed.append({"title": win["title"], "state": "focused", "minimized_others": minimized_count})

    out: dict[str, Any] = {
        "ok": True,
        "layout": layout,
        "matched": placed,
        "unmatched": unmatched,
    }
    return out


def _find_in_app_paths(exe_name: str) -> str | None:
    """Busca un ejecutable en el registro de Windows (App Paths)."""
    if not is_windows():
        return None
    try:
        import winreg
        candidates = [exe_name] if exe_name.lower().endswith(".exe") else [f"{exe_name}.exe", exe_name]
        for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            for cand in candidates:
                key_path = rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{cand}"
                try:
                    with winreg.OpenKey(root, key_path) as key:
                        val, _ = winreg.QueryValueEx(key, None)
                        if isinstance(val, str) and val.strip():
                            cleaned = val.strip().strip('"')
                            if Path(cleaned).exists():
                                return cleaned
                except OSError:
                    continue
    except Exception:
        pass
    return None


def resolve_executable(app_name: str) -> str | None:
    """Resuelve un nombre o alias de aplicación a un ejecutable verificable."""
    key = app_name.strip().lower()
    if not key:
        return None
    # Bloquear rutas arbitrarias o caracteres de shell
    if any(ch in key for ch in (";", "&", "|", "`", "$", ">", "<", "\n", "\r")):
        return None
    target = APP_ALIASES.get(key, key)
    found = shutil.which(target)
    if found:
        return found
    if is_windows():
        reg_hit = _find_in_app_paths(target)
        if reg_hit:
            return reg_hit
        sys32 = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / (
            target if target.endswith(".exe") else f"{target}.exe"
        )
        if sys32.exists():
            return str(sys32)
    return None


_START_APPS_TTL_S = 600.0
_start_apps_cache: tuple[float, list[tuple[str, str]]] | None = None


def _start_apps() -> list[tuple[str, str]]:
    """``[(nombre, AUMID)]`` del menú Inicio, incluidas las apps de la Microsoft Store.

    Lista de solo lectura (``Get-StartApps``); tarda ~2 s, así que se cachea y solo
    se usa cuando la app no tiene un ``.exe`` resoluble.
    """
    global _start_apps_cache
    now = time.monotonic()
    if _start_apps_cache is not None:
        stamp, cached = _start_apps_cache
        if now - stamp < (_START_APPS_TTL_S if cached else 60.0):
            return cached
    apps: list[tuple[str, str]] = []
    try:
        out = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
             "Get-StartApps | Select-Object Name, AppID | ConvertTo-Json -Compress"],
            capture_output=True, text=True, timeout=15,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        raw = json.loads(out.stdout or "[]")
        if isinstance(raw, dict):
            raw = [raw]
        apps = [(str(a["Name"]), str(a["AppID"])) for a in raw
                if isinstance(a, dict) and a.get("Name") and a.get("AppID")]
    except Exception:
        apps = []
    _start_apps_cache = (now, apps)
    return apps


def find_start_app(app_name: str) -> tuple[str, str] | None:
    """Busca una app del menú Inicio por nombre: exacto, después prefijo, después contiene."""
    key = app_name.strip().lower()
    if not key:
        return None
    apps = _start_apps()
    for matches in (lambda n: n == key, lambda n: n.startswith(key), lambda n: key in n):
        for name, aumid in apps:
            if matches(name.lower()):
                return name, aumid
    return None


def launch_application(app_name: str, args: list[str] | None = None) -> dict[str, Any]:
    """Lanza una aplicación de escritorio sin usar ``shell=True``.

    Primero un ``.exe`` resoluble; si no hay, una app del menú Inicio (las de la
    Microsoft Store, como WhatsApp, no tienen ``.exe`` en PATH ni en App Paths).
    """
    if not is_windows():
        return {
            "ok": False,
            "error": "unsupported_platform",
            "message": "launch_app requiere Windows",
        }
    exe = resolve_executable(app_name)
    start_app = None if exe else find_start_app(app_name)
    if not exe and not start_app:
        return {
            "ok": False,
            "error": "app_not_found",
            "message": f"No se encontró la aplicación {app_name!r}",
        }
    safe_args = [str(a) for a in (args or []) if isinstance(a, str) and a.strip()]
    creationflags = (
        subprocess.DETACHED_PROCESS
        | subprocess.CREATE_NEW_PROCESS_GROUP
    )
    if exe:
        command = [exe, *safe_args]
    else:
        # El AUMID sale de la lista del sistema, nunca del texto del usuario.
        command = ["explorer.exe", f"shell:AppsFolder\\{start_app[1]}"]
    before = _window_snapshot()
    try:
        proc = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
        )
        out: dict[str, Any] = {
            "ok": True,
            "app": app_name,
            "executable": exe or "explorer.exe",
            "pid": proc.pid,
        }
        if start_app:
            out["store_app"] = start_app[0]
            if safe_args:
                out["note"] = "Las apps del menú Inicio se abren sin argumentos."
        # El gateway corre en segundo plano: sin esto la app abre detrás.
        match_name = start_app[0] if start_app else app_name
        out.update(_bring_launched_window_to_front(before, match_name))
        return out
    except Exception as exc:
        return {
            "ok": False,
            "error": "launch_failed",
            "message": f"No se pudo abrir {app_name!r}: {exc}",
        }
