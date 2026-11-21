// Mock del servidor WS del plugin H.E.R.M.I.S (Día 2).
// Implementa el mismo contrato que ws_server.py: overlay.json con host/port/
// token/pid, hello obligatorio (4401 si el token es inválido, 4400 si falla)
// y la secuencia completa del Día 2: mode (intro), notificación, email_list,
// table, cards, image, web, custom, actualización de email_list, close de la
// table y mode de salida (~2 s entre mensajes). Sin Hermes instalado.
'use strict';

const os = require('os');
const path = require('path');
const fs = require('fs');
const crypto = require('crypto');
const { WebSocketServer } = require('ws');

const HELLO_TIMEOUT_MS = 10000;
const clients = new Set();

const SAMPLE_EMAILS = [
  {
    from: 'Juan Pérez',
    subject: 'Entrega del TP final — necesito prórroga',
    snippet: 'Profesora: tuve un problema con la PC y no llego…',
    date: '10:42',
    body_markdown: 'Hola,\n\nTuve un problema con la notebook y no puedo terminar hoy.\n\n**¿Puedo entregarlo el viernes?** Lo que ya tengo:\n\n- Parte 1: lista\n- Informe: a medio hacer\n\nGracias,\nJuan',
  },
  {
    from: 'Coordinación 3ºB',
    subject: 'Cierre de notas del trimestre: viernes',
    snippet: 'Recordá que el viernes cierra el trimestre…',
    date: '09:15',
    body_markdown: '### Cierre de notas\n\nEl **viernes a las 12:00** cierra el trimestre. Falta:\n\n1. Cargar las notas en el sistema\n2. Firmar el acta\n\n> Si algo se pipe, avisen hoy.',
  },
  { from: 'Lucía Gómez', subject: 'Consulta sobre el parcial', snippet: '¿El parcial incluye la unidad 4?', date: '08:58' },
  { from: 'Google Drive', subject: 'Te compartieron "Trabajos prácticos"', date: 'Ayer' },
  { from: 'Martín Ruiz', subject: 'Re: reunión de padres', snippet: 'Confirmo que voy el jueves a las 18.', date: 'Ayer' },
];

// Misma id que la superficie original: actualiza en el lugar.
const SAMPLE_EMAILS_UPDATED = [
  { from: 'Juan Pérez', subject: 'Re: Entrega del TP final — aprovó la prórroga', snippet: 'Perfecto, entonces viernes 18:00…', date: '11:05' },
  ...SAMPLE_EMAILS.slice(1),
  { from: 'Ana Torres', subject: 'Te paso el material de lectura', snippet: 'Tres PDFs para la clase del lunes.', date: '07:30' },
];

const SAMPLE_TABLE = {
  title: 'Notas 3ºB',
  columns: ['Alumno', 'TP1', 'TP2', 'Parcial', 'Promedio'],
  rows: [
    ['Juan Pérez', '8', '7', '6', '7,0'],
    ['Lucía Gómez', '9', '9', '8', '8,7'],
    ['Martín Ruiz', '6', null, '7', '6,5'],
    { Alumno: 'Ana Torres', TP1: '10', TP2: '9', Parcial: '9', Promedio: '9,3' },
  ],
};

const SAMPLE_CARDS = {
  title: 'Tu día',
  items: [
    { title: '15 correos sin leer', subtitle: 'Bandeja de entrada', body: '3 parecen urgentes.', badge: 'nuevo' },
    { title: '2 clases mañana', subtitle: 'Agenda', body: '5ºA 8:00 · 6ºB 10:30' },
    { title: 'Acta del trimestre', subtitle: 'Pendiente', body: 'Falta tu firma.', badge: 'urgente' },
  ],
};

const SAMPLE_IMAGE_SVG = `<svg xmlns="http://www.w3.org/2000/svg" width="320" height="180"><defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#0071E3"/><stop offset="1" stop-color="#5AC8FA"/></linearGradient></defs><rect width="320" height="180" rx="16" fill="url(#g)"/><circle cx="160" cy="82" r="40" fill="rgba(255,255,255,0.85)"/><text x="160" y="152" font-family="Segoe UI, sans-serif" font-size="15" fill="#fff" text-anchor="middle">imagen via data: URI</text></svg>`;
const SAMPLE_IMAGE_URI = `data:image/svg+xml,${encodeURIComponent(SAMPLE_IMAGE_SVG)}`;

const SAMPLE_WEB = {
  title: 'Hermes Agent — Documentación',
  url: 'https://hermes-agent.nousresearch.com/docs',
};

const SAMPLE_CUSTOM_HTML = `<div style="font-family:Segoe UI,sans-serif;padding:16px;color:#1D1D1F">
  <h2 style="margin:0 0 8px;color:#0071E3">Salida de emergencia aislada</h2>
  <p>Este HTML viene del agente, pasa por <strong>DOMPurify</strong> y se renderiza en un <em>iframe sandbox</em>.</p>
  <ul><li>Sin allow-scripts</li><li>Origen opaco</li><li>CSP heredada</li></ul>
</div>`;

function parseArgs(argv) {
  const args = {};
  for (let i = 0; i < argv.length; i++) {
    if (argv[i] === '--data-dir' && argv[i + 1]) {
      args.dataDir = argv[i + 1];
      i++;
    } else if (argv[i] === '--port' && argv[i + 1]) {
      args.port = Number(argv[i + 1]);
      i++;
    } else if (argv[i] === '--exit-after' && argv[i + 1]) {
      args.exitAfter = Number(argv[i + 1]);
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
    [600, { type: 'mode', autopilot: true }],
    [4000, { type: 'render', surface: 'notification', data: { text: 'Piloto automático activado (mock)', level: 'success' } }],
    [6000, { type: 'render', surface: 'email_list', id: 'email_list-1', data: { title: 'Últimos correos', items: SAMPLE_EMAILS } }],
    [8000, { type: 'render', surface: 'table', id: 'table-1', data: SAMPLE_TABLE }],
    [10000, { type: 'render', surface: 'cards', id: 'cards-1', data: SAMPLE_CARDS }],
    [12000, { type: 'render', surface: 'image', id: 'image-1', data: { title: 'Muestra', src: SAMPLE_IMAGE_URI, alt: 'Gradiente de muestra' } }],
    [14000, { type: 'render', surface: 'web', id: 'web-1', data: SAMPLE_WEB }],
    [16000, { type: 'render', surface: 'custom', id: 'custom-1', data: { title: 'HTML aislado', html: SAMPLE_CUSTOM_HTML } }],
    [18000, { type: 'render', surface: 'email_list', id: 'email_list-1', data: { title: 'Últimos correos (actualizada)', items: SAMPLE_EMAILS_UPDATED } }],
    [20000, { type: 'close', id: 'table-1' }],
    [22000, { type: 'mode', autopilot: false }],
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

  // Para pruebas automatizadas: se apaga solo a los N segundos.
  if (Number.isFinite(args.exitAfter) && args.exitAfter > 0) {
    setTimeout(() => {
      console.log(`[mock] --exit-after ${args.exitAfter}s: saliendo`);
      process.exit(0);
    }, args.exitAfter * 1000);
  }

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
