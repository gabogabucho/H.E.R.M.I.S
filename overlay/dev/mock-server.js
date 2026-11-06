// Mock del servidor WS del plugin H.E.R.M.I.S (Día 1).
// Implementa el mismo contrato que ws_server.py: overlay.json con host/port/
// token/pid, hello obligatorio (4401 si el token es inválido, 4400 si falla)
// y muestra de mensajes render (con y sin id) / close / state / mode.
// Sin Hermes instalado.
'use strict';

const os = require('os');
const path = require('path');
const fs = require('fs');
const crypto = require('crypto');
const { WebSocketServer } = require('ws');

const HELLO_TIMEOUT_MS = 10000;
const clients = new Set();

const SAMPLE_DOCUMENT = `# Bienvenida a H.E.R.M.I.S

Este documento lo **dibuja el mock** sobre tu escritorio real.

- El agente manda *datos*, nunca HTML
- El markdown se sanitiza con DOMPurify
- Los clics pasan donde no hay superficies

| Paso | Estado |
|---|---|
| Conexión WS | OK |
| hello_ok | OK |

    render_surface → superficie "document" — Día 1`;

const SAMPLE_DOCUMENT_UPDATED = `# Documento actualizado en el lugar

El mock re-renderizó **document-1**: misma id, misma ventana, nuevo contenido.

1. La posición y el arrastre se mantienen
2. Solo cambia el cuerpo del markdown

> Si leés esto, la actualización in-place funcionó.`;

function parseArgs(argv) {
  const args = {};
  for (let i = 0; i < argv.length; i++) {
    if (argv[i] === '--data-dir' && argv[i + 1]) {
      args.dataDir = argv[i + 1];
      i++;
    } else if (argv[i] === '--port' && argv[i + 1]) {
      args.port = Number(argv[i + 1]);
      i++;
    }
  }
  return args;
}

function writeOverlayInfo(file, info) {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  const tmp = `${file}.tmp`;
  fs.writeFileSync(tmp, JSON.stringify(info));
  fs.renameSync(tmp, file);
}

function sendSampleSequence(ws) {
  const steps = [
    [500, { type: 'state', orb: 'listening' }],
    [1200, { type: 'render', surface: 'notification', data: { text: 'Hermes conectado (mock)', level: 'info' } }],
    [2500, { type: 'render', surface: 'document', id: 'document-1', data: { title: 'Bienvenida a H.E.R.M.I.S', body_markdown: SAMPLE_DOCUMENT } }],
    [4000, { type: 'state', orb: 'thinking' }],
    [5500, { type: 'state', orb: 'speaking' }],
    [7000, { type: 'state', orb: 'idle' }],
    [8500, { type: 'render', surface: 'notification', data: { text: 'Todo listo', level: 'success' } }],
    [10000, {
      type: 'render',
      surface: 'email_list',
      id: 'email_list-1',
      data: {
        title: 'Bandeja de entrada (Día 2)',
        items: [
          { from: 'ana@ejemplo.com', subject: 'Notas del sprint' },
          { from: 'luis@ejemplo.com', subject: 'Re: demo del piloto automático' },
        ],
      },
    }],
    [12000, { type: 'render', surface: 'document', id: 'document-1', data: { title: 'Bienvenida (actualizada)', body_markdown: SAMPLE_DOCUMENT_UPDATED } }],
    [14000, { type: 'close', id: 'document-1' }],
    [16000, { type: 'mode', autopilot: true }],
    [18000, { type: 'mode', autopilot: false }],
  ];
  for (const [delay, msg] of steps) {
    setTimeout(() => {
      if (!clients.has(ws)) return;
      ws.send(JSON.stringify(msg));
      console.log(`[mock] → ${JSON.stringify(msg).slice(0, 72)}`);
    }, delay);
  }
}

function main() {
  const args = parseArgs(process.argv.slice(2));
  const dataDir = args.dataDir || fs.mkdtempSync(path.join(os.tmpdir(), 'hermis-mock-'));
  const overlayFile = path.join(dataDir, 'overlay.json');
  const port = Number.isInteger(args.port) && args.port > 0 ? args.port : 0;

  const wss = new WebSocketServer({ host: '127.0.0.1', port });
  const token = crypto.randomBytes(32).toString('base64url');

  wss.on('listening', () => {
    const address = wss.address();
    writeOverlayInfo(overlayFile, { host: '127.0.0.1', port: address.port, token, pid: process.pid });
    console.log(`[mock] overlay.json en: ${overlayFile}`);
    console.log('[mock] levantá el overlay en otra terminal con:');
    console.log(`       npm start -- --data-dir "${dataDir}"`);
  });

  wss.on('connection', (ws) => {
    console.log('[mock] cliente conectado, esperando hello…');
    let authed = false;
    const helloTimer = setTimeout(() => {
      if (!authed) {
        console.warn('[mock] hello timeout → cierre 4400');
        ws.close(4400, 'hello timeout o mensaje inválido');
      }
    }, HELLO_TIMEOUT_MS);

    ws.on('message', (raw) => {
      if (authed) return;
      let hello;
      try {
        hello = JSON.parse(raw.toString());
      } catch (e) {
        clearTimeout(helloTimer);
        console.warn('[mock] hello no JSON → cierre 4400');
        ws.close(4400, 'hello timeout o mensaje inválido');
        return;
      }
      if (hello && hello.type === 'hello' && hello.token === token) {
        authed = true;
        clearTimeout(helloTimer);
        clients.add(ws);
        ws.send(JSON.stringify({ type: 'hello_ok' }));
        console.log('[mock] hello_ok ✓ — mandando muestra');
        sendSampleSequence(ws);
      } else {
        clearTimeout(helloTimer);
        console.warn('[mock] token inválido → cierre 4401');
        ws.close(4401, 'token inválido');
      }
    });

    ws.on('close', () => {
      clearTimeout(helloTimer);
      clients.delete(ws);
      console.log('[mock] cliente desconectado');
    });
    ws.on('error', (e) => console.warn('[mock] ws error:', e.message));
  });
}

main();
