const { app, BrowserWindow, ipcMain, screen } = require('electron');
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

function overlayFilePath() {
  const dir = dataDirOverride();
  if (dir) return path.join(dir, 'overlay.json');
  const home = process.env.HERMES_HOME || path.join(os.homedir(), '.hermes');
  return path.join(home, 'plugin-data', 'hermis', 'overlay.json');
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
        if (endpointKey(info) !== lastEndpoint && sock) {
          console.log('[overlay] overlay.json cambió (puerto/token): reconectando');
          sock.terminate();
        }
      }, FILE_WATCH_DEBOUNCE_MS);
    });
    fileWatcher.on('error', () => {});
  } catch (e) {
    console.warn('[overlay] no se pudo vigilar overlay.json:', e.message);
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
  win.webContents.on('console-message', (event, level, message) => {
    console.log('[renderer]', typeof message === 'string' ? message : event.message);
  });
  win.loadFile(path.join(__dirname, 'renderer', 'index.html'));
  win.showInactive();
}

ipcMain.on('hermis:interactive', (_e, interactive) => {
  if (win && !win.isDestroyed()) {
    win.setIgnoreMouseEvents(!interactive, { forward: !interactive });
  }
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
