---
name: hermis-overlay
description: Ajusta la transparencia (opacidad) y el tema visual (claro u oscuro) de las superficies flotantes del overlay H.E.R.M.I.S, o acomoda, abre y escribe texto en ventanas reales de Windows (split, grid, maximize, focus, minimize_others, launch_app, type_in_window) a pedido del usuario.
---

# H.E.R.M.I.S — Control de Transparencia, Tema y Ventanas Reales

## 1. Ajustar Transparencia (`opacity`) y Tema (`theme`) del Overlay

Cuando el usuario pida ajustar qué tan traslúcido u opaco se ve el fondo de las ventanas flotantes de H.E.R.M.I.S, o cambiar entre fondo claro y oscuro, llama a `render_surface` usando `surface="notification"` e incluyendo `opacity` (`20` a `98`) y/o `theme` (`"light"` o `"dark"`):

```json
{
  "surface": "notification",
  "data": {
    "text": "Transparencia ajustada al 65%",
    "level": "info",
    "opacity": 65
  }
}
```

## 2. Acomodar Ventanas Reales (`layout_windows`), Abrir Apps (`launch_app`) y Escribir Texto (`type_in_window`)

- Para acomodar o enfocar ventanas reales:
  - `layout_windows(layout="split"|"grid"|"maximize"|"focus"|"minimize_others", windows=["PowerShell", "Bloc de notas"])`
- Para abrir una aplicación:
  - `launch_app(app="notepad"|"calc"|"explorer"|"chrome"|"code"|..., args=[...])`
- **Para escribir texto dentro de una ventana abierta (como el Bloc de notas / Notepad):**
  Ejecuta con la herramienta de terminal este comando Python que enfoca la ventana, hace clic en el área de edición y envía las teclas Unicode con `SendInput`:
  ```powershell
  python -c "import sys, json; sys.path.insert(0, 'c:/Users/EnderJavier/Documents/Proyectos WEB/H.E.R.M.I.S'); import win32_windows; print(json.dumps(win32_windows.type_in_window('bloc de notas', 'hello world'), ensure_ascii=False))"
  ```
