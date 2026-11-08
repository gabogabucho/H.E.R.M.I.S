---
name: hermis-overlay
description: Ajusta la transparencia (opacidad) y el tema visual (claro u oscuro) de las superficies flotantes del overlay H.E.R.M.I.S a pedido del usuario.
---

# H.E.R.M.I.S — Control de Transparencia y Tema del Overlay

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
