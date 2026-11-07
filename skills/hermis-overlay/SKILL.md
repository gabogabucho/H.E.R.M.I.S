---
name: hermis-overlay
description: Ajusta la transparencia (opacidad) y el tema visual (claro u oscuro) de las superficies flotantes del overlay H.E.R.M.I.S, o acomoda/abre ventanas reales de Windows (split, grid, maximize, focus, minimize_others, launch_app) a pedido del usuario.
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

- **Muy traslúcido / cristal ligero:** `55` a `68`
- **Equilibrado (por defecto):** `82` a `85`
- **Casi sólido / máxima lectura:** `92` a `96`
- **Tema oscuro / claro:** `"theme": "dark"` o `"theme": "light"`

## 2. Acomodar Ventanas Reales (`layout_windows`) y Abrir Apps (`launch_app`)

- Si las tools `layout_windows` y `launch_app` están registradas en la sesión, úsalas directamente:
  - `layout_windows(layout="split"|"grid"|"maximize"|"focus"|"minimize_others", windows=["Excel", "Chrome"])`
  - `launch_app(app="notepad"|"calc"|"explorer"|"chrome"|"code"|..., args=[...])`
- Si la sesión actual del Gateway se inició antes de registrar `layout_windows` / `launch_app`, puedes invocar el módulo directamente con Python:
  ```powershell
  python -c "import win32_windows, json; print(json.dumps(win32_windows.apply_layout('split', ['PowerShell', 'Chrome']), ensure_ascii=False))"
  ```
  o para abrir una app:
  ```powershell
  python -c "import win32_windows, json; print(json.dumps(win32_windows.launch_application('notepad'), ensure_ascii=False))"
  ```
