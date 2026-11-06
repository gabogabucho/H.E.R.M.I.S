# H.E.R.M.I.S — Overlay (Día 1)

Overlay Electron transparente para Windows 11: se conecta al servidor WebSocket
del plugin y dibuja lo que llega — el orbe y las superficies `notification` y
`document`. Los clics pasan al escritorio donde no hay nada dibujado.

## Correrlo con el mock (sin Hermes)

1. Instalar dependencias (descarga el binario de Electron; versión fija):

   ```
   npm install
   ```

2. Levantar el mock del plugin (implementa el mismo contrato que `ws_server.py`):

   ```
   node dev/mock-server.js
   ```

   El mock escribe `overlay.json` en una carpeta temporal e imprime el
   comando siguiente.

3. En otra terminal, apuntar el overlay a esa carpeta:

   ```
   npm start -- --data-dir "<carpeta que imprimió el mock>"
   ```

Qué deberías ver: una notificación arriba a la derecha (con auto-cierre y
botón de cierre), un documento flotante con markdown renderizado, y el orbe
abajo a la derecha pasando por `listening → thinking → speaking → idle`.
Sobre cualquier superficie podés arrastrarla por el header o cerrarla con ×.
Donde no hay superficies, los clics llegan a tu escritorio.

## Con el plugin real

El overlay lee `%HERMES_HOME%\plugin-data\hermis\overlay.json` (o
`~/.hermes/plugin-data/hermis/overlay.json` si no hay `HERMES_HOME`), que el
plugin escribe al levantar su WS. El override manual es el mismo:

```
npm start -- --data-dir <ruta>
```

## Estructura

- `main.js` — proceso main: ventana transparente que cubre el área de trabajo,
  `alwaysOnTop` nivel `screen-saver`, click-through (`setIgnoreMouseEvents` con
  forward), conexión WS (hello + token, reconexión con backoff) y vigilancia de
  `overlay.json` (si cambia el puerto o el token, reconecta).
- `preload.js` — `contextBridge` mínimo. El token y el WS viven en el main,
  nunca en el renderer.
- `renderer/` — shell portado de Lumen OS: `<lumen-orb>`, `<lumen-window>`,
  notificaciones y CSS de vidrio; markdown sanitizado (marked + DOMPurify).
  CSP estricta, `contextIsolation`, sin `nodeIntegration`, sandbox.
- `dev/mock-server.js` — mock del plugin para probar de punta a punta.

## Pendiente (Día 2)

- Morph del orbe con `mode` (autopilot), superficies `email_list`, `table`,
  `cards`, y `close_surface` / `list_surfaces`.
