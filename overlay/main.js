const { app, BrowserWindow, ipcMain, screen, shell } = require('electron');
const path = require('path');
const fs = require('fs');
const os = require('os');
const { WebSocket } = require('ws');

const CONNECT_BACKOFF_MS = 1000;
const CONNECT_BACKOFF_MAX_MS = 30000;
const HELLO_TIMEOUT_MS = 5000;
const FILE_WATCH_DEBOUNCE_MS = 250;

let win = null;
let sock = null;
let authed = false;
let backoffMs = CONNECT_BACKOFF_MS;
let reconnectTimer = null;
let helloTimer = null;
let lastEndpoint = null;
let fileWatcher = null;

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
  win.loadFile(path.join(__dirname, 'renderer', 'index.html'));
  win.showInactive();
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

if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.whenReady().then(() => {
    createWindow();
    watchOverlayFile();
    connect();
  });
  app.on('window-all-closed', () => app.quit());
}
