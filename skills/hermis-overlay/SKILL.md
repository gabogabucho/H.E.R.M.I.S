---
name: hermis-overlay
description: Ajusta la transparencia (opacidad) y el tema visual (claro u oscuro) de las superficies flotantes del overlay H.E.R.M.I.S a pedido del usuario (por ejemplo "haz el fondo más traslúcido", "baja la opacidad al 60%", "pon las ventanas en modo oscuro", "make the overlay more transparent").
---

# H.E.R.M.I.S — Control de Transparencia y Tema del Overlay

Cuando el usuario pida ajustar qué tan traslúcido u opaco se ve el fondo de las ventanas flotantes de H.E.R.M.I.S, o cambiar entre fondo claro y oscuro:

## Cómo aplicarlo inmediatamente

Llama a la herramienta `render_surface` usando `surface="notification"` e incluyendo `opacity` (porcentaje entero entre `20` y `98`) y/o `theme` (`"light"` o `"dark"`) dentro de `data`:

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

## Guía de valores de `opacity`
- **Muy traslúcido / cristal ligero:** `55` a `68`
- **Equilibrado (por defecto):** `82` a `85`
- **Casi sólido / máxima lectura:** `92` a `96`
- Si el usuario dice *"más traslúcido"* o *"baja la opacidad"* sin dar un número, usa `65` (o resta ~15 puntos al valor actual).
- Si el usuario dice *"más opaco"* o *"menos transparente"*, usa `94`.
- Si el usuario pide *"modo oscuro"* / *"fondo oscuro"* / *"dark mode"*, envía `"theme": "dark"` (y `"theme": "light"` para volver a fondo claro).
