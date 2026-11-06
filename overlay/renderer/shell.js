/**
 * shell.js — H.E.R.M.I.S overlay shell (Día 1)
 * Portado de Lumen OS (gabogabucho/Lumen-os, os/shell/shell.js): <lumen-orb>,
 * <lumen-window> y notificaciones. Sin sesión ni WS propio (viven en el main
 * de Electron) ni apps de Lumen. El adaptador traduce x-lumen-desktop v2.
 */

'use strict';

const ORB_SIZE = 96;
const WINDOW_MARGIN = 20;
const WINDOW_WIDTH = 480;
const WINDOW_HEIGHT = 320;
const NOTIF_LIFETIME_MS = 4000;
const NOTIF_LEVELS = ['info', 'success', 'error'];
// Superficies del Día 2 sin componente propio: se muestran genéricas y seguras.
const GENERIC_SURFACES = ['email_list', 'table', 'cards', 'web', 'image', 'custom'];

function generateId(prefix = 'win') {
  return `${prefix}_${Math.random().toString(36).slice(2, 9)}`;
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
  }

  _attachEvents() {
    const header = this.querySelector('.window-header');
    const closeBtn = this.querySelector('.window-close');

    if (header) {
      header.addEventListener('mousedown', (e) => this._startDrag(e));
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

// =============================================
// <lumen-shell>
// =============================================
class LumenShell extends HTMLElement {
  constructor() {
    super();
    this.windows = new Map();
    this._interactive = false;
    this.autopilot = false;
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
      <div id="windows-container"></div>
      <div id="notifications-container"></div>
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
        this.setAutopilot(!!msg.autopilot);
        break;
      default:
        console.log('[shell] mensaje desconocido, ignorado:', msg.type);
    }
  }

  _handleRender(surface, data, id) {
    if (!data || typeof data !== 'object') return;
    if (surface === 'notification') {
      this.showNotification(data.text, data.level);
      return;
    }
    const surfaceId = typeof id === 'string' && id ? id : null;
    if (surface === 'document') {
      this.openDocument(surfaceId || generateId('doc'), data);
      return;
    }
    if (GENERIC_SURFACES.includes(surface)) {
      this.openGeneric(surfaceId || generateId('surface'), surface, data);
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
    const record = { el: winEl, kind: 'document' };
    this._setWindowBody(record, 'document', data);
    const pos = this._computePosition();
    winEl.setPosition(pos.x, pos.y);
    this.querySelector('#windows-container').appendChild(winEl);
    this.windows.set(id, record);
    console.log('[shell] surface document dibujada:', id);
    return id;
  }

  // Superficies del Día 2 sin componente: título + datos como texto plano
  // (textContent, nunca HTML) en una ventana normal.
  openGeneric(id, surface, data) {
    if (this.windows.has(id)) {
      this.updateWindow(id, 'generic', { surface, data });
      return id;
    }
    const winEl = document.createElement('lumen-window');
    winEl.setAttribute('window-id', id);
    winEl.setAttribute('title', data.title || surface);
    winEl.addEventListener('window-close', (e) => this.closeWindow(e.detail.id));
    const record = { el: winEl, kind: 'generic' };
    this._setWindowBody(record, 'generic', data);
    const pos = this._computePosition();
    winEl.setPosition(pos.x, pos.y);
    this.querySelector('#windows-container').appendChild(winEl);
    this.windows.set(id, record);
    console.log('[shell] surface genérica dibujada:', surface, id);
    return id;
  }

  _setWindowBody(record, kind, data) {
    const old = record.el.querySelector('.document-body, .generic-body');
    if (old) old.remove();
    if (kind === 'document') {
      const body = document.createElement('div');
      body.className = 'document-body';
      body.innerHTML = this._markdownToHtml(data.body_markdown || '');
      record.el.appendChild(body);
    } else {
      const body = document.createElement('pre');
      body.className = 'generic-body';
      body.textContent = this._genericText(data);
      record.el.appendChild(body);
    }
    record.kind = kind;
  }

  _genericText(data) {
    try {
      return JSON.stringify(data, null, 2);
    } catch (e) {
      return String(data);
    }
  }

  _markdownToHtml(md) {
    try {
      return DOMPurify.sanitize(marked.parse(String(md)));
    } catch (e) {
      console.warn('[shell] markdown falló, muestro texto plano:', e.message);
      const pre = document.createElement('pre');
      pre.textContent = String(md);
      return pre.innerHTML;
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
  }

  closeWindow(id) {
    const record = this.windows.get(id);
    if (!record) return;
    record.el.remove();
    this.windows.delete(id);
  }

  setShellState(state) {
    const orb = this.querySelector('lumen-orb');
    if (orb && typeof state === 'string') orb.state = state;
  }

  // mode: por ahora solo se muestra en el orbe (clase CSS); el morph es del Día 2.
  setAutopilot(on) {
    this.autopilot = on;
    console.log('[shell] autopilot:', this.autopilot);
    const orb = this.querySelector('lumen-orb');
    if (orb) orb.classList.toggle('autopilot', on);
  }

  _computePosition() {
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    const orbZone = { left: vw - ORB_SIZE - 120, top: vh - ORB_SIZE - 140, right: vw, bottom: vh };
    const candidates = [
      { x: WINDOW_MARGIN, y: WINDOW_MARGIN },
      { x: vw - WINDOW_WIDTH - WINDOW_MARGIN, y: WINDOW_MARGIN },
      { x: WINDOW_MARGIN, y: (vh - WINDOW_HEIGHT) / 2 },
      { x: (vw - WINDOW_WIDTH) / 2, y: WINDOW_MARGIN },
      { x: WINDOW_MARGIN, y: vh - WINDOW_HEIGHT - WINDOW_MARGIN - 40 },
      { x: (vw - WINDOW_WIDTH) / 2, y: (vh - WINDOW_HEIGHT) / 2 },
    ];
    const existing = Array.from(this.windows.values()).map((r) => ({
      left: parseInt(r.el.style.left || 0, 10),
      top: parseInt(r.el.style.top || 0, 10),
      right: parseInt(r.el.style.left || 0, 10) + WINDOW_WIDTH,
      bottom: parseInt(r.el.style.top || 0, 10) + WINDOW_HEIGHT,
    }));
    const overlaps = (rect, other) => !(
      rect.right < other.left + 40 ||
      rect.left > other.right - 40 ||
      rect.bottom < other.top + 40 ||
      rect.top > other.bottom - 40
    );
    for (const cand of candidates) {
      const rect = { left: cand.x, top: cand.y, right: cand.x + WINDOW_WIDTH, bottom: cand.y + WINDOW_HEIGHT };
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
