const { app, BrowserWindow, clipboard, ipcMain, protocol, screen, session, shell } = require('electron');
const crypto = require('crypto');
const https = require('https');
const path = require('path');
const fs = require('fs');
const os = require('os');
const { WebSocket } = require('ws');

const CONNECT_BACKOFF_MS = 1000;
const CONNECT_BACKOFF_MAX_MS = 30000;
const HELLO_TIMEOUT_MS = 5000;
const FILE_WATCH_DEBOUNCE_MS = 250;

// Gestos v1: el WASM de MediaPipe no carga desde file://, así que el
// renderer pide solo dos cosas fijas por este esquema: el wasm/bundle de
// node_modules/@mediapipe/tasks-vision y el modelo descargado una vez.
const MEDIA_SCHEME = 'hermis-media';
const MODEL_URL = 'https://storage.googleapis.com/mediapipe-models/gesture_recognizer/gesture_recognizer/float16/1/gesture_recognizer.task';
// SHA-256 del modelo pineado: si no coincide, el archivo se descarta.
const MODEL_SHA256 = '97952348cf6a6a4915c2ea1496b4b37ebabc50cbbf80571435643c455f2b0482';
const MODEL_FILE = 'gesture_recognizer.task';
const TASKS_DIR = path.join(__dirname, 'node_modules', '@mediapipe', 'tasks-vision');
const MEDIA_TYPES = { '.js': 'text/javascript', '.mjs': 'text/javascript', '.wasm': 'application/wasm', '.task': 'application/octet-stream' };

// Antes de que la app esté lista: esquema estándar, seguro, con fetch y CORS
// (la página es file:// y el import de módulos ES exige CORS explícito).
protocol.registerSchemesAsPrivileged([
  { scheme: MEDIA_SCHEME, privileges: { standard: true, secure: true, supportFetchAPI: true, corsEnabled: true } },
]);

let win = null;
let sock = null;
let authed = false;
let backoffMs = CONNECT_BACKOFF_MS;
let reconnectTimer = null;
let helloTimer = null;
let lastEndpoint = null;
let fileWatcher = null;
let gatewayClient = null;
const { createGatewayClient } = require('./gateway_client');

function dataDirOverride() {
  const i = process.argv.indexOf('--data-dir');
  return i !== -1 && process.argv[i + 1] ? process.argv[i + 1] : null;
}

function defaultHermesHome() {
  if (process.env.HERMES_HOME) return process.env.HERMES_HOME;
  if (process.platform === 'win32' && process.env.LOCALAPPDATA) {
    return path.join(process.env.LOCALAPPDATA, 'hermes');
  }
  return path.join(os.homedir(), '.hermes');
}

function overlayFilePath() {
  const dir = dataDirOverride();
  if (dir) return path.join(dir, 'overlay.json');
  return path.join(defaultHermesHome(), 'plugin-data', 'hermis', 'overlay.json');
}

// El modelo vive en el data dir del plugin (sobrevive updates; nunca se commitea).
function gestureModelPath() {
  const dir = dataDirOverride() || path.join(defaultHermesHome(), 'plugin-data', 'hermis');
  return path.join(dir, MODEL_FILE);
}

function downloadGestureModel(dest) {
  return new Promise((resolve, reject) => {
    fs.mkdirSync(path.dirname(dest), { recursive: true });
    const tmp = `${dest}.part`;
    https.get(MODEL_URL, (res) => {
      if (res.statusCode !== 200) {
        res.resume();
        reject(new Error(`descarga del modelo: HTTP ${res.statusCode}`));
        return;
      }
      const out = fs.createWriteStream(tmp);
      const hash = crypto.createHash('sha256');
      res.on('data', (chunk) => hash.update(chunk));
      res.pipe(out);
      out.on('finish', () => out.close(() => {
        const got = hash.digest('hex');
        if (got !== MODEL_SHA256) {
          fs.rmSync(tmp, { force: true });
          reject(new Error(`modelo de gestos con hash inesperado: ${got}`));
          return;
        }
        try { fs.renameSync(tmp, dest); resolve(); } catch (e) { reject(e); }
      }));
      out.on('error', reject);
    }).on('error', reject);
  });
}

// Solo rutas fijas: nada de servir archivos arbitrarios del disco.
function resolveMediaFile(url) {
  if (url.hostname === 'tasks-vision') {
    const rel = decodeURIComponent(url.pathname).replace(/^\/+/, '');
    const file = path.normalize(path.join(TASKS_DIR, rel));
    return file.startsWith(TASKS_DIR + path.sep) ? file : null;
  }
  if (url.hostname === 'model') return gestureModelPath();
  return null;
}

function registerMediaProtocol() {
  protocol.handle(MEDIA_SCHEME, (request) => {
    let file = null;
    try { file = resolveMediaFile(new URL(request.url)); } catch (e) { file = null; }
    if (!file || !fs.existsSync(file)) {
      return new Response(null, { status: 404 });
    }
    return new Response(fs.readFileSync(file), {
      headers: {
        'Content-Type': MEDIA_TYPES[path.extname(file)] || 'application/octet-stream',
        // La página vive en file:// (origen null): CORS explícito para módulos ES.
        'Access-Control-Allow-Origin': '*',
      },
    });
  });
}

function readOverlayInfo() {
  try {
    const info = JSON.parse(fs.readFileSync(overlayFilePath(), 'utf8'));
    if (typeof info.host === 'string' && Number.isInteger(info.port) && typeof info.token === 'string') {
      return info;
    }
    console.warn('[overlay] overlay.json incompleto, ignorado');
  } catch (e) {
    console.warn('[overlay] overlay.json todavía no está:', e.code || e.message);
  }
  return null;
}

function endpointKey(info) {
  return `${info.host}:${info.port}|${info.token}`;
}

function sendStatus(status) {
  if (win && !win.isDestroyed()) win.webContents.send('hermis:status', status);
}

function forward(msg) {
  const label = msg && msg.type === 'render'
    ? `render:${msg.surface}`
    : (msg && msg.type) || 'desconocido';
  console.log('[overlay] plugin → renderer:', label);
  if (win && !win.isDestroyed()) win.webContents.send('hermis:message', msg);
}

function sendToPlugin(msg) {
  if (sock && authed && sock.readyState === WebSocket.OPEN) {
    try {
      sock.send(JSON.stringify(msg));
      return true;
    } catch (e) {
      console.warn('[overlay] error enviando al plugin ws:', e.message);
      return false;
    }
  }
  return false;
}

function scheduleReconnect() {
  if (reconnectTimer) return;
  console.log(`[overlay] reconectando en ${backoffMs}ms`);
  reconnectTimer = setTimeout(() => {
    reconnectTimer = null;
    connect();
  }, backoffMs);
  backoffMs = Math.min(CONNECT_BACKOFF_MAX_MS, backoffMs * 2);
}

function connect() {
  if (sock) return;
  const info = readOverlayInfo();
  if (!info) {
    watchOverlayFile();
    scheduleReconnect();
    return;
  }
  const key = endpointKey(info);
  if (key !== lastEndpoint) {
    backoffMs = CONNECT_BACKOFF_MS;
    lastEndpoint = key;
  }
  console.log(`[overlay] conectando a ws://${info.host}:${info.port}`);
  sendStatus('connecting');
  let s;
  try {
    s = new WebSocket(`ws://${info.host}:${info.port}`);
  } catch (e) {
    console.warn('[overlay] no se pudo abrir el socket:', e.message);
    scheduleReconnect();
    return;
  }
  sock = s;
  authed = false;
  s.on('open', () => {
    console.log('[overlay] ws abierto, mandando hello');
    s.send(JSON.stringify({ type: 'hello', token: info.token }));
    helloTimer = setTimeout(() => {
      console.warn('[overlay] hello_ok no llegó a tiempo');
      s.terminate();
    }, HELLO_TIMEOUT_MS);
  });
  s.on('message', (raw) => {
    let msg;
    try {
      msg = JSON.parse(raw.toString());
    } catch (e) {
      console.warn('[overlay] mensaje no JSON, ignorado');
      return;
    }
    if (!authed) {
      if (msg && msg.type === 'hello_ok') {
        authed = true;
        clearTimeout(helloTimer);
        helloTimer = null;
        backoffMs = CONNECT_BACKOFF_MS;
        console.log('[overlay] hello_ok: autenticado');
        sendStatus('connected');
      }
      return;
    }
    forward(msg);
  });
  s.on('close', (code) => {
    console.log(`[overlay] ws cerrado (código ${code})`);
    sendStatus(`closed:${code}`);
    sock = null;
    authed = false;
    clearTimeout(helloTimer);
    helloTimer = null;
    if (code === 4401) lastEndpoint = null;
    scheduleReconnect();
  });
  s.on('error', (e) => {
    console.warn('[overlay] ws error:', e.message);
  });
}

function watchOverlayFile() {
  if (fileWatcher) return;
  let timer = null;
  try {
    fileWatcher = fs.watch(path.dirname(overlayFilePath()), () => {
      clearTimeout(timer);
      timer = setTimeout(() => {
        const info = readOverlayInfo();
        if (!info) return;
        if (sock) {
          if (endpointKey(info) !== lastEndpoint) {
            console.log('[overlay] overlay.json cambió (puerto/token): reconectando');
            sock.terminate();
          }
        } else if (reconnectTimer) {
          clearTimeout(reconnectTimer);
          reconnectTimer = null;
          backoffMs = CONNECT_BACKOFF_MS;
          console.log('[overlay] overlay.json disponible: conectando ya');
          connect();
        }
      }, FILE_WATCH_DEBOUNCE_MS);
    });
    fileWatcher.on('error', () => {
      try {
        fileWatcher.close();
      } catch (e) {
        // ya cerrado
      }
      fileWatcher = null;
    });
  } catch (e) {
    console.warn('[overlay] no se pudo vigilar overlay.json:', e.message);
    fileWatcher = null;
  }
}

function watchRendererFiles() {
  let reloadTimer = null;
  try {
    fs.watch(path.join(__dirname, 'renderer'), () => {
      clearTimeout(reloadTimer);
      reloadTimer = setTimeout(() => {
        if (!win || win.isDestroyed()) return;
        win.webContents.once('did-finish-load', () => {
          if (sock) {
            backoffMs = CONNECT_BACKOFF_MS;
            sock.terminate();
          }
        });
        win.webContents.reloadIgnoringCache();
      }, 250);
    });
  } catch (e) {
    // opcional
  }
}

function createWindow() {
  const { workArea } = screen.getPrimaryDisplay();
  win = new BrowserWindow({
    x: workArea.x,
    y: workArea.y,
    width: workArea.width,
    height: workArea.height,
    frame: false,
    transparent: true,
    resizable: false,
    movable: false,
    alwaysOnTop: true,
    skipTaskbar: true,
    focusable: false,
    hasShadow: false,
    fullscreenable: false,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });
  win.setAlwaysOnTop(true, 'screen-saver');
  win.setIgnoreMouseEvents(true, { forward: true });
  // El overlay no navega: un <a href> del contenido nunca reemplaza la ventana.
  win.webContents.on('will-navigate', (e, url) => {
    e.preventDefault();
    if (/^https?:\/\//i.test(url)) shell.openExternal(url);
  });
  win.webContents.setWindowOpenHandler(({ url }) => {
    if (/^https?:\/\//i.test(url)) shell.openExternal(url);
    return { action: 'deny' };
  });
  win.webContents.on('console-message', (event) => {
    console.log('[renderer]', event.message);
  });
  const ready = win.loadFile(path.join(__dirname, 'renderer', 'index.html'));
  win.showInactive();
  return ready;
}

ipcMain.on('hermis:interactive', (_e, interactive) => {
  if (win && !win.isDestroyed()) {
    win.setIgnoreMouseEvents(!interactive, { forward: !interactive });
  }
});

// La validación vive en main: el renderer nunca decide qué se abre afuera.
ipcMain.handle('hermis:open-external', (_e, url) => {
  if (typeof url === 'string' && /^https?:\/\//i.test(url)) {
    return shell.openExternal(url);
  }
  console.warn('[overlay] open-external rechazado (solo http/https):', typeof url);
});

// Onboarding: el botón "Copiar" solo escribe texto en el portapapeles; nunca ejecuta nada.
ipcMain.handle('hermis:copy-text', (_e, text) => {
  if (typeof text !== 'string' || !text || text.length > 4096) return false;
  clipboard.writeText(text);
  return true;
});

// Onboarding: "Volver a revisar" pide al plugin que recalcule el checklist.
ipcMain.handle('hermis:setup-refresh', () => sendToPlugin({ type: 'setup.refresh' }));

// Gestos: el renderer pide preparar el modelo (descarga única) antes de prender la cámara.
ipcMain.handle('hermis:gestures-start', async () => {
  try {
    const target = gestureModelPath();
    if (!fs.existsSync(target)) {
      console.log('[overlay] descargando el modelo de gestos (una sola vez)…');
      await downloadGestureModel(target);
    }
    return { ok: true };
  } catch (e) {
    console.warn('[overlay] modelo de gestos no disponible:', e.message);
    return { ok: false, message: e.message };
  }
});

// Gesto ✊: el renderer indica la superficie de adelante; main la reenvía al plugin.
ipcMain.on('hermis:gesture-close', (_e, id) => {
  if (typeof id !== 'string' || !id.trim()) return;
  sendToPlugin({ type: 'gesture.close', id: id.trim() });
});

// Sin superficies en pantalla, el gesto va a las ventanas reales (lo hace el plugin con Win32).
const GESTURE_WINDOW_ACTIONS = new Set(['minimize', 'next', 'prev', 'desktop']);
ipcMain.on('hermis:gesture-window', (_e, action) => {
  if (!GESTURE_WINDOW_ACTIONS.has(action)) return;
  sendToPlugin({ type: 'gesture.window', action });
});

// Privacidad: cámara solo para la página propia del overlay y solo video.
// Los cuadros se procesan en el proceso del overlay; nunca salen de la PC.
// Comparar textos de URL file:// fallaba en Windows (c: vs C:, codificación) y
// negaba la cámara. Se reconoce la página por el objeto de la ventana, solo el
// frame principal (nunca los iframes de artefactos) y la ruta renderer/index.html.
function isOverlayPage(wc, details) {
  if (!win || win.isDestroyed() || !wc || wc.id !== win.webContents.id) return false;
  if (details && details.isMainFrame === false) return false;
  let url = (details && details.requestingUrl) || '';
  try { url = decodeURIComponent(url); } catch (e) { /* url tal cual */ }
  return url.replace(/\\/g, '/').toLowerCase().endsWith('/renderer/index.html');
}

function registerPermissions() {
  session.defaultSession.setPermissionRequestHandler((wc, permission, callback, details) => {
    if (permission === 'media' && isOverlayPage(wc, details)) {
      const types = details && Array.isArray(details.mediaTypes) ? details.mediaTypes : ['video'];
      callback(types.length > 0 && types.every((t) => t === 'video'));
      return;
    }
    callback(false);
  });
}

if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.whenReady().then(async () => {
    registerMediaProtocol();
    registerPermissions();
    await createWindow();
    watchOverlayFile();
    watchRendererFiles();
    connect();
  });
  app.whenReady().then(() => {
    gatewayClient = createGatewayClient({
      readOverlayInfo,
      hermesHome: defaultHermesHome(),
      sendToPlugin,
      forwardToRenderer: forward,
    });
    gatewayClient.start();
  });
  app.on('before-quit', () => {
    if (gatewayClient) {
      gatewayClient.stop();
      gatewayClient = null;
    }
  });
  app.on('window-all-closed', () => app.quit());
}
