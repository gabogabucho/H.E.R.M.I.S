/**
 * gesture-test.js — prueba de factibilidad de gestos con cámara (MediaPipe),
 * aislada del overlay real. Se corre con Electron, nunca en producción:
 *
 *   cd overlay && npx electron dev/gesture-test.js
 *
 * Todo es local: sin API keys ni cuentas. La primera vez descarga el modelo
 * (gesture_recognizer.task, de Google) a una carpeta temporal y después lo
 * reutiliza. Las imágenes de la cámara nunca salen de la PC.
 *
 * Por qué un servidor en 127.0.0.1: el WASM de MediaPipe no carga desde file://
 * y getUserMedia pide un origen seguro (localhost lo es). Sirve solo tres cosas
 * fijas: la página, el paquete @mediapipe/tasks-vision y el modelo.
 */
'use strict';

const { app, BrowserWindow, session } = require('electron');
const fs = require('fs');
const http = require('http');
const https = require('https');
const os = require('os');
const path = require('path');

const MODEL_URL = 'https://storage.googleapis.com/mediapipe-models/gesture_recognizer/gesture_recognizer/float16/latest/gesture_recognizer.task';
const MODEL_PATH = path.join(os.tmpdir(), 'hermis-gesture', 'gesture_recognizer.task');
const TASKS_DIR = path.join(__dirname, '..', 'node_modules', '@mediapipe', 'tasks-vision');
const PAGE = path.join(__dirname, 'gesture-test.html');
const TYPES = { '.html': 'text/html', '.mjs': 'text/javascript', '.js': 'text/javascript', '.wasm': 'application/wasm', '.task': 'application/octet-stream' };

function download(url, dest) {
  return new Promise((resolve, reject) => {
    fs.mkdirSync(path.dirname(dest), { recursive: true });
    const tmp = `${dest}.part`;
    https.get(url, (res) => {
      if (res.statusCode !== 200) {
        res.resume();
        reject(new Error(`descarga del modelo: HTTP ${res.statusCode}`));
        return;
      }
      const out = fs.createWriteStream(tmp);
      res.pipe(out);
      out.on('finish', () => out.close(() => { fs.renameSync(tmp, dest); resolve(); }));
      out.on('error', reject);
    }).on('error', reject);
  });
}

// Solo rutas fijas: nada de servir archivos arbitrarios del disco.
function resolveFile(urlPath) {
  if (urlPath === '/' || urlPath === '/gesture-test.html') return PAGE;
  if (urlPath === '/model.task') return MODEL_PATH;
  if (urlPath.startsWith('/tasks-vision/')) {
    const file = path.normalize(path.join(TASKS_DIR, urlPath.slice('/tasks-vision/'.length)));
    if (file.startsWith(TASKS_DIR + path.sep)) return file;
  }
  return null;
}

function serve() {
  return new Promise((resolve) => {
    const server = http.createServer((req, res) => {
      const file = resolveFile(decodeURIComponent(new URL(req.url, 'http://x').pathname));
      if (!file || !fs.existsSync(file)) {
        res.writeHead(404).end();
        return;
      }
      res.writeHead(200, { 'Content-Type': TYPES[path.extname(file)] || 'application/octet-stream' });
      fs.createReadStream(file).pipe(res);
    });
    server.listen(0, '127.0.0.1', () => resolve(server));
  });
}

app.whenReady().then(async () => {
  if (!fs.existsSync(MODEL_PATH)) {
    console.log('[gesture-test] descargando el modelo (una sola vez)…');
    await download(MODEL_URL, MODEL_PATH);
  }
  console.log('[gesture-test] modelo:', MODEL_PATH, `${Math.round(fs.statSync(MODEL_PATH).size / 1024)} KB`);
  const server = await serve();
  const origin = `http://127.0.0.1:${server.address().port}`;

  // Cámara solo para nuestra página local.
  session.defaultSession.setPermissionRequestHandler((wc, permission, cb) => {
    cb(permission === 'media' && wc.getURL().startsWith(origin));
  });

  const win = new BrowserWindow({
    width: 980,
    height: 720,
    title: 'H.E.R.M.I.S — prueba de gestos',
    webPreferences: { contextIsolation: true, sandbox: true, nodeIntegration: false },
  });
  win.webContents.on('console-message', (_e, _level, message) => {
    if (message.startsWith('HERMIS_GESTURE:')) console.log('[gesture-test]', message.slice(15));
  });
  await win.loadURL(`${origin}/gesture-test.html`);
}).catch((err) => {
  console.error('[gesture-test] error:', err && err.message);
  app.exit(1);
});

app.on('window-all-closed', () => app.quit());
