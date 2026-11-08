/**
 * artifact-security-test.js — verificación de seguridad de la superficie
 * artifact (se corre con Electron, nunca en producción):
 *
 *   cd overlay && npx electron dev/artifact-security-test.js
 *
 * Carga un harness con las mismas webPreferences del overlay (contextIsolation,
 * sandbox, sin nodeIntegration y con el preload real, para que window.hermis
 * exista), dibuja un artefacto hostil por el mismo camino que shell.js
 * (iframe sandbox="allow-scripts" + artifact-frame.html + postMessage) y
 * verifica que el artefacto NO pueda:
 *   - leer window.parent / window.top (document) ni window.hermis;
 *   - hacer fetch (connect-src 'none' de la CSP del frame);
 *   - abrir ventanas (sandbox sin allow-popups);
 *   - navegar el overlay (sin allow-top-navigation; se verifica la URL real).
 * Sale con código 0 si todo passa, 1 si algo falla.
 */
'use strict';

const { app, BrowserWindow } = require('electron');
const path = require('path');

const EXPECTED_ESCAPED = ['parent_document', 'parent_hermis', 'top_document', 'fetch_external', 'window_open'];
const RESULT_PREFIX = 'HERMIS_ARTIFACT_SECURITY_RESULT:';

let win = null;
let settled = false;
let loadedUrl = null;

function finish(ok, detail) {
  if (settled) return;
  settled = true;
  console.log(ok ? '[security-test] PASS' : '[security-test] FAIL', detail || '');
  app.exit(ok ? 0 : 1);
}

app.whenReady().then(() => {
  win = new BrowserWindow({
    width: 900,
    height: 700,
    show: false,
    webPreferences: {
      preload: path.join(__dirname, '..', 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });
  const topUrl = win.webContents.getURL();

  win.webContents.on('console-message', (event) => {
    console.log('[renderer]', event.message);
    if (!event.message.startsWith(RESULT_PREFIX)) return;
    let results;
    try {
      results = JSON.parse(event.message.slice(RESULT_PREFIX.length));
    } catch (e) {
      finish(false, 'reporte no parseable: ' + e.message);
      return;
    }
    const problems = [];
    for (const name of EXPECTED_ESCAPED) {
      const r = results[name];
      if (!r) {
        problems.push(`${name}: sin resultado`);
      } else if (!r.escaped) {
        problems.push(`${name}: ESCAPÓ (${r.detail})`);
      }
    }
    if (!results.parent_navigation) problems.push('parent_navigation: sin resultado');
    setTimeout(() => {
      const url = win.isDestroyed() ? loadedUrl : win.webContents.getURL();
      if (url !== loadedUrl) {
        problems.push(`parent_navigation: el overlay navegó a ${url}`);
      }
      finish(problems.length === 0, problems.length ? problems.join(' | ') : 'el artefacto no pudo escapar');
    }, 800);
  });

  win.webContents.on('did-fail-load', (_e, code, desc, url) => {
    finish(false, `no se pudo cargar ${url}: ${code} ${desc}`);
  });
  win.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
  // Igual que el overlay real: no se deja navegar; el chequeo de URL del main
  // verifica que el intento del artefacto no haya tenido efecto.
  win.webContents.on('will-navigate', (e) => e.preventDefault());

  win.loadFile(path.join(__dirname, 'artifact-security-harness.html'))
    .then(() => { loadedUrl = win.webContents.getURL(); })
    .catch((e) => {
      finish(false, 'loadFile falló: ' + e.message);
    });

  setTimeout(() => finish(false, 'timeout sin reporte del artefacto'), 20000);
});

app.on('window-all-closed', () => {
  // El test decide su propia salida con app.exit(); no cerrar antes de tiempo.
});
