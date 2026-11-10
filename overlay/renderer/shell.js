/**
 * shell.js — H.E.R.M.I.S overlay shell
 * Portado de Lumen OS (gabogabucho/Lumen-os, os/shell/shell.js): <lumen-orb>,
 * <lumen-window> y notificaciones. Sin sesión ni WS propio (viven en el main
 * de Electron) ni apps de Lumen. El adaptador traduce x-lumen-desktop v2:
 * morph de modo (Día 2) y componentes de superficie (email_list, table,
 * cards, image, web, artifact).
 */

'use strict';

const ORB_SIZE = 96;
const ORB_CORE_SIZE = 52; // r=38 in 140 viewBox → 76/140 * 96 ≈ 52px
const ORB_RIGHT = 32;
const ORB_BOTTOM = 72;
const BAR_WIDTH = 520;
const BAR_HEIGHT = 64;
// Orbe facetado dentro de la esfera del morph: misma geometría que <lumen-orb>
// pero con ids propios (el <lumen-orb> está oculto durante la intro y sus
// gradientes no se pueden referenciar con display: none).
const MORPH_ORB_SVG = `
  <svg class="morph-orb" viewBox="0 0 140 140" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
    <defs>
      <radialGradient id="morphCoreGrad" cx="35%" cy="30%" r="68%">
        <stop offset="0%" stop-color="#dff8ff" stop-opacity="0.98"/>
        <stop offset="28%" stop-color="#7ddcff" stop-opacity="0.95"/>
        <stop offset="62%" stop-color="#1c8fff" stop-opacity="1"/>
        <stop offset="100%" stop-color="#0a3c9a" stop-opacity="1"/>
      </radialGradient>
      <radialGradient id="morphAuraGrad" cx="50%" cy="50%" r="50%">
        <stop offset="0%" stop-color="#5ac8fa" stop-opacity="0.55"/>
        <stop offset="100%" stop-color="#5ac8fa" stop-opacity="0"/>
      </radialGradient>
      <filter id="morphGlow">
        <feGaussianBlur stdDeviation="5" result="coloredBlur"/>
        <feMerge>
          <feMergeNode in="coloredBlur"/>
          <feMergeNode in="SourceGraphic"/>
        </feMerge>
      </filter>
    </defs>
    <circle cx="70" cy="70" r="52" fill="url(#morphAuraGrad)" opacity="0.95" filter="url(#morphGlow)"/>
    <circle cx="70" cy="70" r="38" fill="url(#morphCoreGrad)" filter="url(#morphGlow)"/>
    <circle cx="70" cy="70" r="38" fill="none" stroke="rgba(255,255,255,0.38)" stroke-width="1.2"/>
    <g fill="rgba(255,255,255,0.10)" stroke="rgba(255,255,255,0.08)" stroke-width="0.8">
      <polygon points="70,30 45,46 58,70 82,66 95,44"/>
      <polygon points="45,46 34,72 52,95 70,84 58,70"/>
      <polygon points="95,44 106,72 88,96 70,84 82,66"/>
      <polygon points="52,95 70,110 88,96 70,84"/>
    </g>
    <polyline points="70,30 58,70 45,46 82,66 95,44 70,84 52,95 88,96 106,72" fill="none"
      stroke="rgba(220,245,255,0.35)" stroke-width="1" stroke-linecap="round" stroke-linejoin="round"/>
    <circle cx="70" cy="70" r="11" fill="rgba(235,250,255,0.95)"/>
    <ellipse cx="56" cy="50" rx="11" ry="7" transform="rotate(-25 56 50)" fill="rgba(255,255,255,0.9)"/>
    <circle cx="88" cy="50" r="2.8" fill="rgba(255,255,255,0.9)"/>
    <circle cx="94" cy="84" r="1.8" fill="rgba(255,255,255,0.9)"/>
  </svg>`;
// La barra de chat del boceto (pantalla 1) mide 520x64. El morph anima
// width/height/border-radius reales (píldora → esfera) para no deformar la
// forma en óvalo; BAR_SCALE_* quedan por compatibilidad.
const BAR_SCALE_X = 520 / ORB_SIZE;
const BAR_SCALE_Y = 64 / ORB_SIZE;
const INTRO_MS = 2400;
const INTRO_TEXT = '¿Qué hacemos hoy?';
const BAR_HINT = 'Pregúntale algo a Hermes…';
const WINDOW_MARGIN = 20;
const WINDOW_WIDTH = 480;
const WINDOW_HEIGHT = 320;
// Un gráfico necesita espacio: la superficie artifact es más grande.
const ARTIFACT_WIDTH = 720;
const ARTIFACT_HEIGHT = 520;
const NOTIF_LIFETIME_MS = 4000;
const NOTIF_LEVELS = ['info', 'success', 'error'];

// =============================================
// Gestos v1 (MediaPipe, todo local): la cámara se prende SOLO con el modo
// piloto y los gestos activos; los cuadros nunca se muestran ni salen de la PC.
// Referencia del loop: overlay/dev/gesture-test.js (prueba que funcionó).
// =============================================
const GESTURE_MEDIA_BASE = 'hermis-media://tasks-vision';
const GESTURE_MODEL_URL = 'hermis-media://model/gesture_recognizer.task';
const GESTURE_SCORE_MIN = 0.7;
const SWIPE_THRESHOLD = 0.18;  // en la prueba 0.28 casi no disparaba
const SWIPE_WINDOW_MS = 350;
const SWIPE_COOLDOWN_MS = 700;
const FIST_HOLD_MS = 500;
const PALM_HOLD_MS = 700;
const HOLD_COOLDOWN_MS = 1500;
const TOAST_LIFETIME_MS = 1600;

function generateId(prefix = 'win') {
  return `${prefix}_${Math.random().toString(36).slice(2, 9)}`;
}

const DEFAULT_OPACITY = 84;

function getSavedOpacity() {
  try {
    const val = parseInt(localStorage.getItem('hermis_opacity') || '', 10);
    if (!Number.isNaN(val) && val >= 50 && val <= 98) return val;
  } catch (e) { /* ignore */ }
  return DEFAULT_OPACITY;
}

function getSavedTheme() {
  try {
    return localStorage.getItem('hermis_theme') === 'dark' ? 'dark' : 'light';
  } catch (e) {
    return 'light';
  }
}

function applyPanelStyle(opacityPct = getSavedOpacity(), theme = getSavedTheme()) {
  const clamped = Math.max(20, Math.min(98, Number(opacityPct) || DEFAULT_OPACITY));
  const alpha = (clamped / 100).toFixed(2);
  const root = document.documentElement;
  if (theme === 'dark') {
    root.style.setProperty('--lumen-panel-bg', `rgba(17, 24, 39, ${alpha})`);
    root.style.setProperty('--lumen-text', '#F1F5F9');
    root.style.setProperty('--lumen-text-muted', '#94A3B8');
    root.dataset.theme = 'dark';
  } else {
    root.style.setProperty('--lumen-panel-bg', `rgba(244, 246, 250, ${alpha})`);
    root.style.setProperty('--lumen-text', '#1D1D1F');
    root.style.setProperty('--lumen-text-muted', '#64748B');
    root.dataset.theme = 'light';
  }
}

function updatePanelStyle(opts = {}) {
  let opacity = getSavedOpacity();
  let theme = getSavedTheme();
  if (typeof opts.opacity === 'number' && !Number.isNaN(opts.opacity)) {
    const raw = opts.opacity > 0 && opts.opacity <= 1 ? Math.round(opts.opacity * 100) : Math.round(opts.opacity);
    opacity = Math.max(20, Math.min(98, raw));
    try { localStorage.setItem('hermis_opacity', String(opacity)); } catch (e) { /* ignore */ }
  }
  if (opts.theme === 'dark' || opts.theme === 'light') {
    theme = opts.theme;
    try { localStorage.setItem('hermis_theme', theme); } catch (e) { /* ignore */ }
  }
  applyPanelStyle(opacity, theme);
}

// =============================================
// <lumen-orb>
// =============================================
class LumenOrb extends HTMLElement {
  constructor() {
    super();
    this._state = 'idle';
  }

  static get observedAttributes() {
    return ['state'];
  }

  get state() {
    return this._state;
  }

  set state(val) {
    if (this._state === val) return;
    this._state = val;
    this._updateStateClass();
  }

  attributeChangedCallback(name, oldVal, newVal) {
    if (name === 'state' && newVal !== oldVal) {
      this.state = newVal;
    }
  }

  connectedCallback() {
    this.innerHTML = this._render();
    this._updateStateClass();
    this.addEventListener('click', () => this._onClick());
  }

  _render() {
    return `
      <div class="orb-container">
        <svg class="orb-svg" viewBox="0 0 140 140" xmlns="http://www.w3.org/2000/svg">
          <defs>
            <radialGradient id="orbCoreGrad" cx="35%" cy="30%" r="68%">
              <stop offset="0%" stop-color="#dff8ff" stop-opacity="0.98"/>
              <stop offset="28%" stop-color="#7ddcff" stop-opacity="0.95"/>
              <stop offset="62%" stop-color="#1c8fff" stop-opacity="1"/>
              <stop offset="100%" stop-color="#0a3c9a" stop-opacity="1"/>
            </radialGradient>
            <radialGradient id="orbAuraGrad" cx="50%" cy="50%" r="50%">
              <stop offset="0%" stop-color="#5ac8fa" stop-opacity="0.55"/>
              <stop offset="100%" stop-color="#5ac8fa" stop-opacity="0"/>
            </radialGradient>
            <filter id="orbGlow">
              <feGaussianBlur stdDeviation="5" result="coloredBlur"/>
              <feMerge>
                <feMergeNode in="coloredBlur"/>
                <feMergeNode in="SourceGraphic"/>
              </feMerge>
            </filter>
          </defs>

          <circle class="orb-aura" cx="70" cy="70" r="52" filter="url(#orbGlow)" />
          <circle class="orb-core" cx="70" cy="70" r="38" />
          <circle class="orb-shell" cx="70" cy="70" r="38" />

          <polygon class="orb-facet facet-a" points="70,30 45,46 58,70 82,66 95,44" />
          <polygon class="orb-facet facet-b" points="45,46 34,72 52,95 70,84 58,70" />
          <polygon class="orb-facet facet-c" points="95,44 106,72 88,96 70,84 82,66" />
          <polygon class="orb-facet facet-d" points="52,95 70,110 88,96 70,84" />
          <polyline class="orb-lines" points="70,30 58,70 45,46 82,66 95,44 70,84 52,95 88,96 106,72" />

          <circle class="orb-nucleus" cx="70" cy="70" r="11" />

          <ellipse class="orb-highlight" cx="56" cy="50" rx="11" ry="7" transform="rotate(-25 56 50)" />
          <circle class="orb-spark spark-a" cx="88" cy="50" r="2.8" />
          <circle class="orb-spark spark-b" cx="94" cy="84" r="1.8" />
        </svg>
      </div>
    `;
  }

  _updateStateClass() {
    const container = this.querySelector('.orb-container');
    if (!container) return;
    container.className = 'orb-container';
    if (this._state) {
      container.classList.add(`orb-state-${this._state}`);
    }
  }

  _onClick() {
    this.dispatchEvent(new CustomEvent('orb-click', {
      bubbles: true,
      composed: true,
    }));
  }
}

// =============================================
// <lumen-window>
// =============================================
class LumenWindow extends HTMLElement {
  constructor() {
    super();
    this._x = 0;
    this._y = 0;
    this._width = WINDOW_WIDTH;
    this._height = WINDOW_HEIGHT;
    this._dragging = false;
    this._dragOffset = { x: 0, y: 0 };
  }

  static get observedAttributes() {
    return ['title', 'type', 'window-id'];
  }

  get windowId() {
    return this.getAttribute('window-id') || generateId('win');
  }

  connectedCallback() {
    this._render();
    this._attachEvents();
  }

  _render() {
    const title = this.getAttribute('title') || 'Ventana';
    this.style.width = `${this._width}px`;
    this.style.height = `${this._height}px`;

    this.innerHTML = `
      <div class="window-header">
        <span class="window-title">${escapeHtml(title)}</span>
        <button class="window-close" aria-label="Cerrar">×</button>
      </div>
      <div class="window-content">
        <slot></slot>
      </div>
    `;
    applyPanelStyle();
  }

  _attachEvents() {
    const header = this.querySelector('.window-header');
    const closeBtn = this.querySelector('.window-close');

    if (header) {
      header.addEventListener('mousedown', (e) => {
        if (e.target.closest('button')) return;
        this._startDrag(e);
      });
    }
    if (closeBtn) {
      closeBtn.addEventListener('click', () => this._close());
    }

    document.addEventListener('mousemove', (e) => this._onDrag(e));
    document.addEventListener('mouseup', () => this._stopDrag());
  }

  _startDrag(e) {
    this._dragging = true;
    this._dragOffset.x = e.clientX - this._x;
    this._dragOffset.y = e.clientY - this._y;
    this.style.zIndex = '60';
  }

  _onDrag(e) {
    if (!this._dragging) return;
    e.preventDefault();
    let nx = e.clientX - this._dragOffset.x;
    let ny = e.clientY - this._dragOffset.y;

    const vw = window.innerWidth;
    const vh = window.innerHeight;
    nx = Math.max(0, Math.min(nx, vw - this._width));
    ny = Math.max(0, Math.min(ny, vh - 100));

    this._x = nx;
    this._y = ny;
    this.style.left = `${nx}px`;
    this.style.top = `${ny}px`;
  }

  _stopDrag() {
    if (this._dragging) {
      this._dragging = false;
      this.style.zIndex = '50';
    }
  }

  _close() {
    this.dispatchEvent(new CustomEvent('window-close', {
      bubbles: true,
      composed: true,
      detail: { id: this.windowId },
    }));
  }

  setPosition(x, y) {
    this._x = x;
    this._y = y;
    this.style.left = `${x}px`;
    this.style.top = `${y}px`;
  }

  setSize(width, height) {
    this._width = width;
    this._height = height;
    this.style.width = `${width}px`;
    this.style.height = `${height}px`;
  }

  attributeChangedCallback(name, oldVal, newVal) {
    if (name === 'title' && oldVal !== newVal) {
      const el = this.querySelector('.window-title');
      if (el) el.textContent = newVal || 'Ventana';
    }
  }
}

customElements.define('lumen-orb', LumenOrb);
customElements.define('lumen-window', LumenWindow);

function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

// Único HTML permitido en el shell: markdown pasado por DOMPurify. El
// markdown puede venir de correos de terceros: se prohíbe <style> y el
// atributo style porque con la CSP 'unsafe-inline' un CSS inyectado podría
// tapar la pantalla o dibujar UI falsa. (El HTML de los artefactos conserva
// estilos y scripts: vive en el iframe sandbox con CSP propia.)
function markdownToHtml(md) {
  try {
    return DOMPurify.sanitize(marked.parse(String(md)), { FORBID_TAGS: ['style'], FORBID_ATTR: ['style'] });
  } catch (e) {
    console.warn('[shell] markdown falló, muestro texto plano:', e.message);
    const pre = document.createElement('pre');
    pre.textContent = String(md);
    return pre.innerHTML;
  }
}

function cellText(v) {
  return v === null || v === undefined ? '' : String(v);
}

function formatSender(raw) {
  const s = cellText(raw).trim();
  if (!s) return '';
  const m = s.match(/^\s*"?([^"<]+?)"?\s*<[^>]+>\s*$/);
  return m && m[1].trim() ? m[1].trim() : s.replace(/^"+|"+$/g, '');
}

function formatEmailDate(raw) {
  const s = cellText(raw).trim();
  if (!s) return '';
  // Si parece una fecha RFC-2822 / ISO larga (ej. "Sat, 07 Nov 2026 16:14:23 +0000"), formatearla limpia
  if (/^\w{3},\s+\d{1,2}\s+\w{3}\s+\d{4}\b/.test(s) || /^\d{4}-\d{2}-\d{2}T/.test(s)) {
    const d = new Date(s);
    if (!Number.isNaN(d.getTime())) {
      return d.toLocaleDateString('es-AR', { day: 'numeric', month: 'short' }) + ' ' +
        d.toLocaleTimeString('es-AR', { hour: '2-digit', minute: '2-digit', hour12: false });
    }
  }
  return s;
}

// =============================================
// Componentes de superficie del Día 2 (contrato schemas.py).
// Cada renderer dibuja con textContent (nunca HTML salvo markdown por
// DOMPurify) y devuelve false si los datos vienen mal formados: en ese caso
// la superficie cae a la vista genérica de texto en vez de romper.
// =============================================

function renderEmailList(body, data) {
  if (!Array.isArray(data.items) || !data.items.length) return false;
  const items = data.items.filter((it) => it && typeof it === 'object' &&
    ((typeof it.from === 'string' && it.from) || (typeof it.subject === 'string' && it.subject)));
  if (!items.length) return false;
  const list = document.createElement('div');
  list.className = 'email-list';
  items.forEach((item, i) => {
    const row = document.createElement('div');
    row.className = 'email-row';
    const num = document.createElement('span');
    num.className = 'email-num';
    num.textContent = String(i + 1);
    const main = document.createElement('div');
    main.className = 'email-main';
    const from = document.createElement('div');
    from.className = 'email-from';
    from.textContent = formatSender(item.from) || item.subject;
    if (item.from) from.title = item.from;
    main.appendChild(from);
    if (item.from && item.subject) {
      const subj = document.createElement('div');
      subj.className = 'email-subject';
      subj.textContent = item.subject;
      main.appendChild(subj);
    }
    if (typeof item.snippet === 'string' && item.snippet) {
      const snippet = document.createElement('div');
      snippet.className = 'email-snippet';
      snippet.textContent = item.snippet;
      main.appendChild(snippet);
    }
    const date = document.createElement('span');
    date.className = 'email-date';
    date.textContent = formatEmailDate(item.date);
    if (item.date) date.title = String(item.date);
    row.append(num, main, date);
    list.appendChild(row);
    // Un correo con body_markdown se expande en el lugar (numerados para
    // "abrí el tercero").
    if (typeof item.body_markdown === 'string' && item.body_markdown) {
      row.classList.add('expandable');
      const detail = document.createElement('div');
      detail.className = 'email-detail hidden';
      list.appendChild(detail);
      row.addEventListener('click', () => {
        if (!detail.firstChild) {
          const md = document.createElement('div');
          md.className = 'email-markdown document-body';
          md.innerHTML = markdownToHtml(item.body_markdown);
          detail.appendChild(md);
        }
        detail.classList.toggle('hidden');
      });
    }
  });
  body.appendChild(list);
  return true;
}

function renderTable(body, data) {
  const cols = Array.isArray(data.columns)
    ? data.columns.filter((c) => typeof c === 'string' && c)
    : null;
  if (!cols || !cols.length || !Array.isArray(data.rows) || !data.rows.length) return false;
  if (!data.rows.every((r) => Array.isArray(r) || (r && typeof r === 'object'))) return false;
  const table = document.createElement('table');
  table.className = 'surface-table';
  const head = table.createTHead().insertRow();
  for (const col of cols) {
    const th = document.createElement('th');
    th.textContent = col;
    head.appendChild(th);
  }
  const tbody = table.createTBody();
  for (const row of data.rows) {
    const tr = tbody.insertRow();
    if (Array.isArray(row)) {
      for (let i = 0; i < cols.length; i++) {
        tr.insertCell().textContent = cellText(row[i]);
      }
    } else {
      for (const col of cols) {
        tr.insertCell().textContent = cellText(row[col]);
      }
    }
  }
  body.appendChild(table);
  return true;
}

function renderCards(body, data) {
  if (!Array.isArray(data.items) || !data.items.length) return false;
  const items = data.items.filter((it) => it && typeof it === 'object' &&
    typeof it.title === 'string' && it.title);
  if (!items.length) return false;
  const grid = document.createElement('div');
  grid.className = 'cards-grid';
  for (const item of items) {
    const card = document.createElement('div');
    card.className = 'surface-card';
    if (typeof item.badge === 'string' && item.badge) {
      const badge = document.createElement('span');
      badge.className = 'card-badge';
      badge.textContent = item.badge;
      card.appendChild(badge);
    }
    const title = document.createElement('div');
    title.className = 'card-title';
    title.textContent = item.title;
    card.appendChild(title);
    if (typeof item.subtitle === 'string' && item.subtitle) {
      const subtitle = document.createElement('div');
      subtitle.className = 'card-subtitle';
      subtitle.textContent = item.subtitle;
      card.appendChild(subtitle);
    }
    if (typeof item.body === 'string' && item.body) {
      const text = document.createElement('div');
      text.className = 'card-body';
      text.textContent = item.body;
      card.appendChild(text);
    }
    grid.appendChild(card);
  }
  body.appendChild(grid);
  return true;
}

// Solo https: y data:image/... (la CSP lo refleja).
function isAllowedImageUrl(url) {
  return typeof url === 'string' && (/^https:\/\/\S+$/i.test(url) || /^data:image\//i.test(url));
}

function renderImage(body, data) {
  const src = typeof data.src === 'string' && data.src ? data.src : data.url;
  if (!isAllowedImageUrl(src)) return false;
  const img = document.createElement('img');
  img.className = 'surface-image';
  img.src = src;
  img.alt = typeof data.alt === 'string' ? data.alt : '';
  img.loading = 'lazy';
  body.classList.add('image-body');
  body.appendChild(img);
  return true;
}

// La página no se embebe (los iframes suelen estar bloqueados): tarjeta con
// título, dominio y botón que abre en el navegador vía IPC (validado en main).
function renderWeb(body, data) {
  const url = typeof data.url === 'string' && data.url ? data.url : '';
  if (!/^https?:\/\/\S+$/i.test(url)) return false;
  let domain = url;
  try {
    domain = new URL(url).hostname;
  } catch (e) {
    // url ya validada por el regex; no debería pasar
  }
  const card = document.createElement('div');
  card.className = 'web-card';
  const title = document.createElement('div');
  title.className = 'web-title';
  title.textContent = typeof data.title === 'string' && data.title ? data.title : domain;
  const dom = document.createElement('div');
  dom.className = 'web-domain';
  dom.textContent = domain;
  const link = document.createElement('div');
  link.className = 'web-url';
  link.textContent = url;
  const btn = document.createElement('button');
  btn.className = 'web-open';
  btn.type = 'button';
  btn.textContent = 'Abrir en el navegador';
  btn.addEventListener('click', () => {
    window.hermis.openExternal(url).catch((e) => console.warn('[shell] no se pudo abrir:', e && e.message));
  });
  card.append(title, dom, link, btn);
  body.appendChild(card);
  return true;
}

// Artefacto HTML/SVG (lo mismo que Hermes ya genera en el chat), aislado
// igual que Hermes Desktop: HTML en <iframe sandbox="allow-scripts"> (sin
// allow-same-origin) cargando artifact-frame.html, que tiene su propia CSP
// (el srcdoc heredaría la CSP del overlay y bloquearía los scripts inline).
// El contenido viaja por postMessage y se escribe con document.write, así
// la CSP del frame se mantiene. SVG: DOMPurify con el perfil SVG.
function renderArtifact(body, data) {
  if (!data || (data.kind !== 'html' && data.kind !== 'svg')) return false;
  if (typeof data.content !== 'string' || !data.content) return false;
  if (data.kind === 'svg') {
    let clean;
    try {
      clean = DOMPurify.sanitize(data.content, { USE_PROFILES: { svg: true, svgFilters: true } });
    } catch (e) {
      console.warn('[shell] DOMPurify falló para el svg:', e.message);
      return false;
    }
    if (!clean.trim()) return false;
    const holder = document.createElement('div');
    holder.className = 'artifact-svg';
    holder.innerHTML = clean;
    body.classList.add('artifact-body', 'artifact-svg-body');
    body.appendChild(holder);
    return true;
  }
  const frame = document.createElement('iframe');
  frame.className = 'surface-frame artifact-frame';
  frame.setAttribute('sandbox', 'allow-scripts');
  frame.addEventListener('load', () => {
    // Origen opaco (sin allow-same-origin): targetOrigin '*' es lo único posible.
    frame.contentWindow.postMessage({ type: 'hermis-artifact', kind: 'html', content: data.content }, '*');
  });
  frame.src = 'artifact-frame.html';
  body.classList.add('artifact-body', 'artifact-html-body');
  body.appendChild(frame);
  return true;
}

// Onboarding: checklist que arma el plugin con chequeos de solo lectura. Cada
// paso pendiente trae su comando y un botón "Copiar" (no ejecuta nada).
const SETUP_ICONS = { ok: '✓', warn: '!', info: 'i' };

function renderSetup(body, data) {
  if (!Array.isArray(data.items) || !data.items.length) return false;
  if (typeof data.subtitle === 'string' && data.subtitle) {
    const sub = document.createElement('div');
    sub.className = 'setup-subtitle';
    sub.textContent = data.subtitle;
    body.appendChild(sub);
  }
  const list = document.createElement('div');
  list.className = 'setup-list';
  for (const item of data.items) {
    if (!item || typeof item !== 'object' || typeof item.label !== 'string') continue;
    const status = ['ok', 'warn', 'info'].includes(item.status) ? item.status : 'info';
    const row = document.createElement('div');
    row.className = `setup-item setup-${status}`;
    const icon = document.createElement('span');
    icon.className = 'setup-icon';
    icon.textContent = SETUP_ICONS[status];
    const text = document.createElement('div');
    text.className = 'setup-text';
    const label = document.createElement('div');
    label.className = 'setup-label';
    label.textContent = item.label;
    text.appendChild(label);
    if (typeof item.detail === 'string' && item.detail) {
      const detail = document.createElement('div');
      detail.className = 'setup-detail';
      detail.textContent = item.detail;
      text.appendChild(detail);
    }
    if (typeof item.fix === 'string' && item.fix && status !== 'ok') {
      const fix = document.createElement('div');
      fix.className = 'setup-fix';
      const code = document.createElement('code');
      code.textContent = item.fix;
      const copy = document.createElement('button');
      copy.type = 'button';
      copy.className = 'setup-copy';
      copy.textContent = 'Copiar';
      copy.addEventListener('click', () => {
        window.hermis.copyText(item.fix).then((ok) => {
          copy.textContent = ok ? 'Copiado' : 'No se pudo';
          setTimeout(() => { copy.textContent = 'Copiar'; }, 1500);
        }).catch(() => { copy.textContent = 'No se pudo'; });
      });
      fix.append(code, copy);
      text.appendChild(fix);
    }
    row.append(icon, text);
    list.appendChild(row);
  }
  body.appendChild(list);
  const refresh = document.createElement('button');
  refresh.type = 'button';
  refresh.className = 'web-open setup-refresh';
  refresh.textContent = 'Volver a revisar';
  refresh.addEventListener('click', () => {
    refresh.textContent = 'Revisando…';
    window.hermis.refreshSetup().catch(() => { refresh.textContent = 'Volver a revisar'; });
  });
  body.appendChild(refresh);
  return true;
}

const SURFACE_RENDERERS = {
  setup: renderSetup,
  email_list: renderEmailList,
  table: renderTable,
  cards: renderCards,
  image: renderImage,
  web: renderWeb,
  artifact: renderArtifact,
};

const SURFACE_TITLES = {
  setup: 'Configuración',
  email_list: 'Correos',
  table: 'Tabla',
  cards: 'Tarjetas',
  image: 'Imagen',
  web: 'Enlace',
  artifact: 'Artefacto',
};

// =============================================
// <lumen-shell>
// =============================================
class LumenShell extends HTMLElement {
  constructor() {
    super();
    this.windows = new Map();
    this._introPlaying = false;
    this._interactive = false;
    this.autopilot = false;
    this._morphAnims = [];
    this._morphTimers = [];
    this.gesturesEnabled = false;
    this._gesturesActive = false;
    this._gesturesHidden = false;
    this._frontWindowId = null;
    this._gestureRuntime = null;
    this._desktopShown = false;  // ✋ sin superficies: escritorio real mostrado
  }

  connectedCallback() {
    this._render();
    this._trackInteractive();
    window.hermis.onMessage((msg) => this._handleMessage(msg));
    window.hermis.onStatus((status) => console.log('[shell] conexión:', status));
  }

  _render() {
    this.innerHTML = `
      <lumen-orb id="orb" state="idle"></lumen-orb>
      <div id="camera-indicator" class="camera-indicator hidden" title="Cámara activa (procesamiento local)"></div>
      <div id="windows-container"></div>
      <div id="notifications-container"></div>
      <div id="morph-layer" class="hidden">
        <div class="morph-veil"></div>
        <div class="morph-shape">${MORPH_ORB_SVG}</div>
        <div class="morph-bar-label">${escapeHtml(BAR_HINT)}</div>
        <div class="morph-text"></div>
      </div>
    `;
  }

  // Adaptador del protocolo x-lumen-desktop v2 al dispatcher de superficies.
  _handleMessage(msg) {
    if (!msg || typeof msg !== 'object') return;
    switch (msg.type) {
      case 'render':
        this._handleRender(msg.surface, msg.data, msg.id);
        break;
      case 'close':
        this._handleClose(msg.id);
        break;
      case 'state':
        this.setShellState(msg.orb);
        break;
      case 'mode':
        if (msg.opacity !== undefined || msg.theme !== undefined) {
          updatePanelStyle({ opacity: msg.opacity, theme: msg.theme });
        }
        this.setAutopilot(!!msg.autopilot);
        break;
      case 'gestures':
        this.setGesturesEnabled(!!msg.enabled);
        break;
      case 'intro':
      case 'wake':
        this._handleIntro();
        break;
      case 'style':
        updatePanelStyle({ opacity: msg.opacity, theme: msg.theme });
        break;
      default:
        console.log('[shell] mensaje desconocido, ignorado:', msg.type);
    }
  }

  _handleRender(surface, data, id) {
    if (!data || typeof data !== 'object') return;
    if (data.opacity !== undefined || data.theme !== undefined) {
      updatePanelStyle({ opacity: data.opacity, theme: data.theme });
    }
    if (surface === 'notification') {
      this.showNotification(data.text, data.level);
      return;
    }
    const surfaceId = typeof id === 'string' && id ? id : null;
    if (surface === 'document') {
      this.openDocument(surfaceId || generateId('doc'), data);
      return;
    }
    if (SURFACE_RENDERERS[surface]) {
      this.openSurface(surfaceId || generateId('surface'), surface, data);
      return;
    }
    console.log('[shell] surface desconocida, ignorada:', surface);
  }

  // close de una superficie por id, o de todas con id "all".
  _handleClose(id) {
    if (id === 'all') {
      for (const record of this.windows.values()) record.el.remove();
      this.windows.clear();
      const container = this.querySelector('#notifications-container');
      if (container) container.replaceChildren();
      console.log('[shell] close all: superficies cerradas');
      return;
    }
    this.closeWindow(id);
  }

  showNotification(text, level = 'info') {
    const container = this.querySelector('#notifications-container');
    if (!container) return;
    const el = document.createElement('div');
    el.className = `lumen-notification level-${NOTIF_LEVELS.includes(level) ? level : 'info'}`;
    const span = document.createElement('span');
    span.className = 'notification-text';
    span.textContent = text;
    const close = document.createElement('button');
    close.className = 'notification-close';
    close.setAttribute('aria-label', 'Cerrar');
    close.textContent = '×';
    close.addEventListener('click', () => el.remove());
    el.append(span, close);
    container.appendChild(el);
    setTimeout(() => el.remove(), NOTIF_LIFETIME_MS);
  }

  openDocument(id, data) {
    if (this.windows.has(id)) {
      this.updateWindow(id, 'document', data);
      return id;
    }
    const winEl = document.createElement('lumen-window');
    winEl.setAttribute('window-id', id);
    winEl.setAttribute('title', data.title || 'Documento');
    winEl.addEventListener('window-close', (e) => this.closeWindow(e.detail.id));
    winEl.addEventListener('mousedown', () => this._setFrontWindow(id));
    const record = { el: winEl, kind: 'document' };
    const pos = this._computePosition();
    winEl.setPosition(pos.x, pos.y);
    this.querySelector('#windows-container').appendChild(winEl);
    this._setWindowBody(record, 'document', data);
    this.windows.set(id, record);
    this._ensureSurfacesVisible();
    this._setFrontWindow(id);
    console.log('[shell] surface document dibujada:', id);
    return id;
  }

  // Superficies del Día 2 con componente propio. Con el mismo id se
  // actualizan en el lugar; datos mal formados caen a la vista genérica.
  // El artefacto es más grande: un gráfico necesita espacio.
  openSurface(id, surface, data) {
    if (this.windows.has(id)) {
      this.updateWindow(id, surface, data);
      return id;
    }
    const winEl = document.createElement('lumen-window');
    winEl.setAttribute('window-id', id);
    winEl.setAttribute('title', data.title || SURFACE_TITLES[surface] || surface);
    winEl.addEventListener('window-close', (e) => this.closeWindow(e.detail.id));
    winEl.addEventListener('mousedown', () => this._setFrontWindow(id));
    const record = { el: winEl, kind: surface };
    if (surface === 'artifact') winEl.setSize(ARTIFACT_WIDTH, ARTIFACT_HEIGHT);
    const pos = this._computePosition(winEl._width, winEl._height);
    winEl.setPosition(pos.x, pos.y);
    this.querySelector('#windows-container').appendChild(winEl);
    this._setWindowBody(record, surface, data);
    this.windows.set(id, record);
    this._ensureSurfacesVisible();
    this._setFrontWindow(id);
    console.log('[shell] surface dibujada:', surface, id);
    return id;
  }

  // Si el usuario ocultó todo con ✋, una superficie nueva vuelve a verse:
  // Hermes la dibujó porque quiere mostrarla.
  _ensureSurfacesVisible() {
    if (!this._gesturesHidden) return;
    this._gesturesHidden = false;
    const container = this.querySelector('#windows-container');
    if (container) container.classList.remove('hidden');
  }

  _setWindowBody(record, kind, data) {
    const container = record.el.querySelector('.window-content') || record.el;
    const old = container.querySelector('.surface-body');
    if (old) old.remove();
    const body = document.createElement('div');
    body.className = 'surface-body';
    let rendered = false;
    if (kind === 'document') {
      body.classList.add('document-body');
      body.innerHTML = markdownToHtml(data.body_markdown || '');
      rendered = true;
    } else if (SURFACE_RENDERERS[kind]) {
      rendered = SURFACE_RENDERERS[kind](body, data);
    }
    if (!rendered) {
      body.classList.add('generic-body');
      body.textContent = this._genericText(data);
    }
    container.appendChild(body);
    record.kind = kind;
  }

  _genericText(data) {
    try {
      return JSON.stringify(data, null, 2);
    } catch (e) {
      return String(data);
    }
  }

  updateWindow(id, kind, data) {
    const record = this.windows.get(id);
    if (!record) return;
    console.log('[shell] surface actualizada en el lugar:', id);
    if (typeof data.title === 'string' && data.title) {
      record.el.setAttribute('title', data.title);
    }
    this._setWindowBody(record, kind, data);
    this._setFrontWindow(id);
  }

  closeWindow(id) {
    const record = this.windows.get(id);
    if (!record) return;
    record.el.remove();
    this.windows.delete(id);
    if (this._frontWindowId === id) {
      this._frontWindowId = Array.from(this.windows.keys()).pop() || null;
    }
  }

  // Wake word dentro del modo: solo pulso de escucha. La intro completa (velo +
  // texto) es para la entrada al modo; repetirla taparía las superficies abiertas.
  _handleIntro() {
    if (!this.autopilot) return;
    this.setShellState('listening');
  }

  // =============================================
  // Gestos con cámara (v1): ✊ cierra la de adelante, deslizar enfoca la
  // anterior/siguiente, ✋ oculta/muestra todas. La cámara vive SOLO mientras
  // el modo piloto y los gestos están activos; el punto junto al orbe lo
  // indica por privacidad. El modelo se descarga una vez (main.js).
  // =============================================
  setGesturesEnabled(enabled) {
    if (enabled === this.gesturesEnabled) return;
    this.gesturesEnabled = enabled;
    console.log('[shell] gestures:', enabled);
    this._syncGestures();
  }

  _syncGestures() {
    const want = this.autopilot && this.gesturesEnabled;
    if (want && !this._gesturesActive) {
      this._startGestures();
    } else if (!want && this._gesturesActive) {
      this._stopGestures();
    }
  }

  async _startGestures() {
    if (this._gesturesActive) return;
    this._gesturesActive = true;
    try {
      const prep = await window.hermis.gesturesStart();
      if (!prep || !prep.ok) throw new Error((prep && prep.message) || 'modelo no disponible');
      if (!this._gesturesWanted()) return;
      const { FilesetResolver, GestureRecognizer } = await import(`${GESTURE_MEDIA_BASE}/vision_bundle.mjs`);
      const fileset = await FilesetResolver.forVisionTasks(`${GESTURE_MEDIA_BASE}/wasm`);
      const options = (delegate) => ({
        baseOptions: { modelAssetPath: GESTURE_MODEL_URL, delegate },
        runningMode: 'VIDEO',
        numHands: 1,
      });
      let recognizer;
      try {
        recognizer = await GestureRecognizer.createFromOptions(fileset, options('GPU'));
      } catch (err) {
        console.warn('[gestos] GPU no disponible; uso CPU:', err.message);
        recognizer = await GestureRecognizer.createFromOptions(fileset, options('CPU'));
      }
      if (!this._gesturesWanted()) {
        try { recognizer.close(); } catch (e) { /* ya liberado */ }
        return;
      }
      // Sin append al DOM: nadie ve los cuadros, solo el reconocedor.
      const video = document.createElement('video');
      video.muted = true;
      video.playsInline = true;
      video.srcObject = await navigator.mediaDevices.getUserMedia({ video: { width: 640, height: 480 } });
      await video.play();
      this._gestureRuntime = {
        recognizer, video, lastTime: -1, raf: 0,
        trail: [], fistSince: 0, palmSince: 0, holdCooldown: 0, swipeCooldown: 0,
      };
      this._updateCameraIndicator();
      this._gestureLoop();
      console.log('[gestos] cámara activa', video.videoWidth + 'x' + video.videoHeight);
    } catch (err) {
      console.warn('[gestos] no se pudo iniciar:', err.message);
      this._toast('✋ Gestos: cámara no disponible', 'error');
      this._stopGestures();
      return;
    }
    if (!this._gesturesWanted()) this._stopGestures();
  }

  _gesturesWanted() {
    return this._gesturesActive && this.autopilot && this.gesturesEnabled;
  }

  _stopGestures() {
    this._gesturesActive = false;
    const rt = this._gestureRuntime;
    this._gestureRuntime = null;
    if (rt) {
      cancelAnimationFrame(rt.raf);
      if (rt.video && rt.video.srcObject) {
        for (const track of rt.video.srcObject.getTracks()) track.stop();
      }
      try { rt.recognizer.close(); } catch (e) { /* ya liberado */ }
    }
    this._updateCameraIndicator();
    console.log('[gestos] cámara apagada');
  }

  _updateCameraIndicator() {
    const dot = this.querySelector('#camera-indicator');
    if (dot) dot.classList.toggle('hidden', !this._gesturesActive);
  }

  _gestureLoop() {
    const rt = this._gestureRuntime;
    if (!rt) return;
    rt.raf = requestAnimationFrame(() => this._gestureLoop());
    const { video, recognizer } = rt;
    if (video.readyState < 2 || video.currentTime === rt.lastTime) return;
    rt.lastTime = video.currentTime;
    const now = performance.now();
    let result;
    try {
      result = recognizer.recognizeForVideo(video, now);
    } catch (e) {
      return;
    }
    const top = result.gestures && result.gestures[0] ? result.gestures[0][0] : null;
    const hand = result.landmarks && result.landmarks[0];
    if (!hand) {
      rt.trail.length = 0;
      rt.fistSince = 0;
      rt.palmSince = 0;
      return;
    }
    // Deslizamientos: trayectoria x de la muñeca (landmark 0), espejada tal
    // como se ve en pantalla (convención de gesture-test.js).
    rt.trail.push({ t: now, x: 1 - hand[0].x });
    while (rt.trail.length && now - rt.trail[0].t > SWIPE_WINDOW_MS) rt.trail.shift();
    if (rt.trail.length > 1 && now > rt.swipeCooldown) {
      const dx = rt.trail[rt.trail.length - 1].x - rt.trail[0].x;
      if (Math.abs(dx) > SWIPE_THRESHOLD) {
        this._focusSurface(dx > 0 ? 1 : -1);
        rt.swipeCooldown = now + SWIPE_COOLDOWN_MS;
        rt.trail.length = 0;
        rt.fistSince = 0;
        rt.palmSince = 0;  // mano en movimiento no es una pose sostenida
      }
    }
    const name = top && top.score > GESTURE_SCORE_MIN ? top.categoryName : 'None';
    if (name === 'Closed_Fist') {
      if (!rt.fistSince) rt.fistSince = now;
      if (now - rt.fistSince >= FIST_HOLD_MS && now > rt.holdCooldown) {
        this._closeFrontSurface();
        rt.holdCooldown = now + HOLD_COOLDOWN_MS;
        rt.fistSince = 0;
        rt.palmSince = 0;
      }
    } else {
      rt.fistSince = 0;
    }
    if (name === 'Open_Palm') {
      if (!rt.palmSince) rt.palmSince = now;
      if (now - rt.palmSince >= PALM_HOLD_MS && now > rt.holdCooldown) {
        this._toggleSurfacesHidden();
        rt.holdCooldown = now + HOLD_COOLDOWN_MS;
        rt.palmSince = 0;
        rt.fistSince = 0;
      }
    } else {
      rt.palmSince = 0;
    }
  }

  // Regla de los gestos: con superficies visibles actúan sobre ellas; sin ninguna
  // (o con todas ocultas), sobre las ventanas reales. El plugin lo hace con Win32
  // y solo minimiza, nunca cierra apps.
  _surfacesVisible() {
    return this.windows.size > 0 && !this._gesturesHidden;
  }

  _windowGesture(action, label) {
    try { window.hermis.gestureWindow(action); } catch (e) { console.warn('[gestos] no se pudo avisar al plugin:', e.message); }
    this._toast(label);
  }

  // Foco local: deslizar trae la superficie anterior/siguiente al frente.
  _focusSurface(dir) {
    if (!this._surfacesVisible()) {
      this._windowGesture(dir > 0 ? 'next' : 'prev', dir > 0 ? '➡️ Ventana siguiente' : '⬅️ Ventana anterior');
      return;
    }
    const ids = Array.from(this.windows.keys());
    if (!ids.length) return;
    let idx = ids.indexOf(this._frontWindowId);
    if (idx === -1) idx = ids.length - 1;
    idx = (idx + dir + ids.length) % ids.length;
    this._setFrontWindow(ids[idx]);
    this._toast(dir > 0 ? '➡️ Siguiente' : '⬅️ Anterior');
  }

  _setFrontWindow(id) {
    const record = this.windows.get(id);
    if (!record) return;
    this._frontWindowId = id;
    for (const [wid, rec] of this.windows) rec.el.style.zIndex = wid === id ? '55' : '50';
  }

  // ✊: la de adelante se cierra localmente y también por el plugin
  // (gesture.close → close_surface), así Hermes sabe qué quedó en pantalla.
  _closeFrontSurface() {
    if (!this._surfacesVisible()) {
      this._windowGesture('minimize', '✊ Minimizar ventana');
      return;
    }
    let id = this._frontWindowId;
    if (!id || !this.windows.has(id)) id = Array.from(this.windows.keys()).pop() || null;
    if (!id) return;
    try { window.hermis.gestureClose(id); } catch (e) { console.warn('[gestos] no se pudo avisar al plugin:', e.message); }
    this.closeWindow(id);
    this._toast('✊ Cerrar');
  }

  // ✋: con superficies, toggle local de todas (notificaciones no, son efímeras);
  // sin ninguna, escritorio real: minimiza todo y otra palma lo restaura.
  _toggleSurfacesHidden() {
    if (this.windows.size === 0) {
      this._desktopShown = !this._desktopShown;
      this._windowGesture('desktop', this._desktopShown ? '✋ Escritorio' : '✋ Restaurar ventanas');
      return;
    }
    this._gesturesHidden = !this._gesturesHidden;
    const container = this.querySelector('#windows-container');
    if (container) container.classList.toggle('hidden', this._gesturesHidden);
    this._toast(this._gesturesHidden ? '✋ Ocultar' : '✋ Mostrar');
  }

  _toast(text, level = 'info') {
    const container = this.querySelector('#notifications-container');
    if (!container) return;
    const el = document.createElement('div');
    el.className = `gesture-toast level-${NOTIF_LEVELS.includes(level) ? level : 'info'}`;
    el.textContent = text;
    container.appendChild(el);
    setTimeout(() => el.remove(), TOAST_LIFETIME_MS);
  }

  setShellState(state) {
    const orb = this.querySelector('lumen-orb');
    if (orb && typeof state === 'string') orb.state = state;
  }

  // mode: morph de barra ↔ orbe. El orbe solo se ve con el piloto automático
  // activo; si el valor no cambia no se repite la animación. La capa del morph
  // es pointer-events: none, así los clics siguen pasando al escritorio.
  setAutopilot(on) {
    if (on === this.autopilot) return;
    this.autopilot = on;
    console.log('[shell] autopilot:', on);
    // Salir del modo apaga la cámara (si el usuario salta el velo no importa).
    this._syncGestures();
    this._cancelMorph();
    const orb = this.querySelector('lumen-orb');
    if (!orb) return;
    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (on) {
      if (reduced) {
        orb.classList.add('autopilot');
        return;
      }
      this._playIntro(orb);
      return;
    }
    const center = this._orbCenter();
    orb.classList.remove('autopilot');
    if (!reduced) this._playOutro(center);
  }

  _orbCenter() {
    return {
      x: window.innerWidth - ORB_RIGHT - ORB_SIZE / 2,
      y: window.innerHeight - ORB_BOTTOM - ORB_SIZE / 2,
    };
  }

  _animate(el, keyframes, opts) {
    const anim = el.animate(keyframes, opts);
    this._morphAnims.push(anim);
    return anim;
  }

  _later(ms, fn) {
    this._morphTimers.push(setTimeout(fn, ms));
  }

  _cancelMorph() {
    for (const anim of this._morphAnims || []) {
      try { anim.cancel(); } catch (e) { /* ya cancelada */ }
    }
    for (const t of this._morphTimers || []) clearTimeout(t);
    this._introPlaying = false;
    if (this.autopilot) {
      const activeOrb = this.querySelector('lumen-orb');
      if (activeOrb) activeOrb.classList.add('autopilot');
      if (activeOrb) activeOrb.style.opacity = '';
    }
    this._morphAnims = [];
    this._morphTimers = [];
    const layer = this.querySelector('#morph-layer');
    if (layer) layer.classList.add('hidden');
  }

  // Intro inmersiva (~3 s, boceto pantallas 1 y 2): velo → barra de chat en el
  // centro → se comprime en el orbe → viaja a su lugar abajo a la derecha,
  // texto "¿Qué hacemos hoy?" y el velo se desvanece.
  _playIntro(orb) {
    const layer = this.querySelector('#morph-layer');
    const veil = layer.querySelector('.morph-veil');
    const shape = layer.querySelector('.morph-shape');
    const label = layer.querySelector('.morph-bar-label');
    const text = layer.querySelector('.morph-text');
    this._introPlaying = true;
    orb.classList.remove('autopilot');
    orb.style.opacity = '0';
    text.textContent = INTRO_TEXT;
    layer.classList.remove('hidden');

    const c = this._orbCenter();
    const dx = c.x - window.innerWidth / 2;
    const dy = c.y - window.innerHeight / 2;

    // Velo: aparece suave
    this._animate(veil, [{ opacity: 0 }, { opacity: 1 }], { duration: 300, fill: 'forwards', easing: 'ease-out' });

    // Forma: píldora 520×64 → esfera 88×88 en el centro → esfera 52×52 en la esquina
    this._animate(shape, [
      { width: `${BAR_WIDTH}px`, height: `${BAR_HEIGHT}px`, borderRadius: '32px',
        transform: 'translate(-50%, -50%) scale(0.96)', opacity: 0, offset: 0 },
      { width: `${BAR_WIDTH}px`, height: `${BAR_HEIGHT}px`, borderRadius: '32px',
        transform: 'translate(-50%, -50%) scale(1)', opacity: 1, offset: 0.12 },
      { width: `${BAR_WIDTH}px`, height: `${BAR_HEIGHT}px`, borderRadius: '32px',
        transform: 'translate(-50%, -50%) scale(1)', opacity: 1, offset: 0.34 },
      { width: '88px', height: '88px', borderRadius: '999px',
        transform: 'translate(-50%, -50%) scale(1.04)', opacity: 1, offset: 0.54 },
      { width: '80px', height: '80px', borderRadius: '999px',
        transform: 'translate(-50%, -50%) scale(1)', opacity: 1, offset: 0.66 },
      { width: `${ORB_CORE_SIZE}px`, height: `${ORB_CORE_SIZE}px`, borderRadius: '999px',
        transform: `translate(calc(-50% + ${dx}px), calc(-50% + ${dy}px)) scale(1)`, opacity: 1, offset: 1.0 },
    ], { duration: INTRO_MS, easing: 'cubic-bezier(0.45, 0, 0.2, 1)', fill: 'forwards' });

    // Orbe facetado: aparece mientras la barra se cierra y gira hasta quedar
    // derecho al llegar a la esquina (igual que <lumen-orb>, sin salto).
    const facets = shape.querySelector('.morph-orb');
    if (facets) {
      this._animate(facets, [
        { opacity: 0, transform: 'translate(-50%, -50%) rotate(-60deg)', offset: 0 },
        { opacity: 0, transform: 'translate(-50%, -50%) rotate(-60deg)', offset: 0.36 },
        { opacity: 1, transform: 'translate(-50%, -50%) rotate(-20deg)', offset: 0.56 },
        { opacity: 1, transform: 'translate(-50%, -50%) rotate(0deg)', offset: 1.0 },
      ], { duration: INTRO_MS, easing: 'cubic-bezier(0.45, 0, 0.2, 1)', fill: 'forwards' });
    }

    // Etiqueta de la barra: se ve mientras la píldora está abierta
    this._animate(label, [
      { opacity: 0 },
      { opacity: 1, offset: 0.12 },
      { opacity: 1, offset: 0.30 },
      { opacity: 0, offset: 0.40 },
    ], { duration: INTRO_MS, fill: 'forwards' });

    // Texto "¿Qué hacemos hoy?": aparece cuando la esfera se forma en el centro
    this._later(1200, () => {
      this._animate(text, [
        { opacity: 0, transform: 'translateY(10px)' },
        { opacity: 1, transform: 'translateY(0)' },
      ], { duration: 420, fill: 'forwards', easing: 'cubic-bezier(0.22, 1, 0.36, 1)' });
    });

    // Handoff: cross-fade al orbe real sin salto de tamaño
    this._later(INTRO_MS + 50, () => {
      orb.classList.add('autopilot');
      this._animate(orb, [{ opacity: 0 }, { opacity: 1 }], { duration: 260, fill: 'forwards', easing: 'ease-out' });
      this._animate(shape, [{ opacity: 1 }, { opacity: 0 }], { duration: 260, fill: 'forwards', easing: 'ease-in' });
    });
    this._later(INTRO_MS + 320, () => {
      orb.style.opacity = '';
      this._animate(veil, [{ opacity: 1 }, { opacity: 0 }], { duration: 500, fill: 'forwards', easing: 'ease-in' });
      this._animate(text, [
        { opacity: 1, transform: 'translateY(0)' },
        { opacity: 0, transform: 'translateY(-6px)' },
      ], { duration: 400, fill: 'forwards', easing: 'ease-in' });
    });
    this._later(INTRO_MS + 860, () => {
      layer.classList.add('hidden');
      this._introPlaying = false;
    });
  }

  // Salida: el orbe viaja al centro, se despliega en barra píldora y se desvanece.
  _playOutro(center) {
    const layer = this.querySelector('#morph-layer');
    const shape = layer.querySelector('.morph-shape');
    layer.classList.remove('hidden');
    const dx = center.x - window.innerWidth / 2;
    const dy = center.y - window.innerHeight / 2;
    // El orbe se expande desde la esquina hacia el centro formando la píldora y se desvanece
    this._animate(shape, [
      { width: `${ORB_CORE_SIZE}px`, height: `${ORB_CORE_SIZE}px`, borderRadius: '999px',
        transform: `translate(calc(-50% + ${dx}px), calc(-50% + ${dy}px)) scale(1)`, opacity: 1, offset: 0 },
      { width: '88px', height: '88px', borderRadius: '999px',
        transform: `translate(-50%, -50%) scale(1)`, opacity: 1, offset: 0.35 },
      { width: `${BAR_WIDTH}px`, height: `${BAR_HEIGHT}px`, borderRadius: '32px',
        transform: 'translate(-50%, -50%) scale(1)', opacity: 0.85, offset: 0.70 },
      { width: `${BAR_WIDTH}px`, height: `${BAR_HEIGHT}px`, borderRadius: '32px',
        transform: 'translate(-50%, -50%) scale(0.96)', opacity: 0, offset: 1.0 },
    ], { duration: 720, easing: 'cubic-bezier(0.22, 1, 0.36, 1)', fill: 'forwards' });
    const facets = shape.querySelector('.morph-orb');
    if (facets) {
      this._animate(facets, [
        { opacity: 1, transform: 'translate(-50%, -50%) rotate(0deg)', offset: 0 },
        { opacity: 1, transform: 'translate(-50%, -50%) rotate(30deg)', offset: 0.35 },
        { opacity: 0, transform: 'translate(-50%, -50%) rotate(60deg)', offset: 0.55 },
        { opacity: 0, transform: 'translate(-50%, -50%) rotate(60deg)', offset: 1.0 },
      ], { duration: 720, easing: 'cubic-bezier(0.22, 1, 0.36, 1)', fill: 'forwards' });
    }
    this._later(780, () => layer.classList.add('hidden'));
  }

  _computePosition(width = WINDOW_WIDTH, height = WINDOW_HEIGHT) {
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    const orbZone = { left: vw - ORB_SIZE - 120, top: vh - ORB_SIZE - 140, right: vw, bottom: vh };
    const candidates = [
      { x: WINDOW_MARGIN, y: WINDOW_MARGIN },
      { x: vw - width - WINDOW_MARGIN, y: WINDOW_MARGIN },
      { x: WINDOW_MARGIN, y: (vh - height) / 2 },
      { x: (vw - width) / 2, y: WINDOW_MARGIN },
      { x: WINDOW_MARGIN, y: vh - height - WINDOW_MARGIN - 40 },
      { x: (vw - width) / 2, y: (vh - height) / 2 },
    ];
    const existing = Array.from(this.windows.values()).map((r) => ({
      left: parseInt(r.el.style.left || 0, 10),
      top: parseInt(r.el.style.top || 0, 10),
      right: parseInt(r.el.style.left || 0, 10) + (r.el._width || WINDOW_WIDTH),
      bottom: parseInt(r.el.style.top || 0, 10) + (r.el._height || WINDOW_HEIGHT),
    }));
    const overlaps = (rect, other) => !(
      rect.right < other.left + 40 ||
      rect.left > other.right - 40 ||
      rect.bottom < other.top + 40 ||
      rect.top > other.bottom - 40
    );
    for (const cand of candidates) {
      const rect = { left: cand.x, top: cand.y, right: cand.x + width, bottom: cand.y + height };
      if (overlaps(rect, orbZone)) continue;
      if (existing.some((er) => overlaps(rect, er))) continue;
      return cand;
    }
    const n = this.windows.size;
    return { x: WINDOW_MARGIN + (n % 5) * 32, y: WINDOW_MARGIN + (n % 5) * 32 };
  }

  // Click-through: el overlay ignora el mouse salvo sobre elementos interactivos.
  _trackInteractive() {
    document.addEventListener('mousemove', (e) => {
      const el = document.elementFromPoint(e.clientX, e.clientY);
      const interactive = !!(el && el.closest('lumen-orb, lumen-window, .lumen-notification'));
      if (interactive === this._interactive) return;
      this._interactive = interactive;
      window.hermis.setInteractive(interactive);
    });
  }
}

customElements.define('lumen-shell', LumenShell);
