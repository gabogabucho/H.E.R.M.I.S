'use strict';

const crypto = require('crypto');
const fs = require('fs');
const net = require('net');
const os = require('os');
const path = require('path');
const { WebSocket } = require('ws');

const GATEWAY_BACKOFF_MS = 1000;
const GATEWAY_BACKOFF_MAX_MS = 30000;
const CONTROL_SOCKET_TIMEOUT_MS = 1500;

function defaultHermesHome(env = process.env, platform = process.platform) {
  if (env && env.HERMES_HOME) return env.HERMES_HOME;
  if (platform === 'win32' && env && env.LOCALAPPDATA) {
    return path.join(env.LOCALAPPDATA, 'hermes');
  }
  return path.join(os.homedir(), '.hermes');
}

function _home_hash(home, platform = process.platform) {
  const resolved = path.resolve(String(home || defaultHermesHome()));
  const normalized = platform === 'win32' ? resolved.toLowerCase() : resolved;
  return crypto.createHash('sha256').update(normalized, 'utf8').digest('hex').slice(0, 16);
}

function controlSocketPathForHome(home, platform = process.platform) {
  const resolvedHome = path.resolve(String(home || defaultHermesHome()));
  if (platform === 'win32') {
    return `\\\\.\\pipe\\hermes-gateway-${_home_hash(resolvedHome, platform)}`;
  }
  const redirectFile = path.join(resolvedHome, 'gateway.sock.path');
  try {
    const redirected = fs.readFileSync(redirectFile, 'utf8').trim();
    if (redirected) return redirected;
  } catch (_e) {
    // Ignore missing gateway.sock.path
  }
  return path.join(resolvedHome, 'gateway.sock');
}

function apiOriginToWs(origin) {
  const raw = String(origin || '').trim().replace(/\/+$/, '');
  if (!raw) return 'ws://127.0.0.1:8642';
  if (/^https:\/\//i.test(raw)) {
    return 'wss://' + raw.slice('https://'.length);
  }
  if (/^http:\/\//i.test(raw)) {
    return 'ws://' + raw.slice('http://'.length);
  }
  if (/^wss?:\/\//i.test(raw)) {
    return raw;
  }
  return `ws://${raw}`;
}

function appendTokenParam(wsUrl, token) {
  if (!token || typeof token !== 'string' || !token.trim()) return wsUrl;
  try {
    const parsed = new URL(wsUrl);
    if (!parsed.searchParams.has('token')) {
      parsed.searchParams.set('token', token.trim());
    }
    return parsed.toString();
  } catch (_e) {
    const sep = wsUrl.includes('?') ? '&' : '?';
    return `${wsUrl}${sep}token=${encodeURIComponent(token.trim())}`;
  }
}

function normalizeGatewayWsUrl(rawUrl, token = null) {
  const trimmed = String(rawUrl || '').trim();
  if (!trimmed) return null;
  const wsBase = apiOriginToWs(trimmed);
  try {
    const parsed = new URL(wsBase);
    if (!parsed.pathname || parsed.pathname === '/') {
      parsed.pathname = '/api/ws';
    }
    if (token && typeof token === 'string' && token.trim() && !parsed.searchParams.has('token')) {
      parsed.searchParams.set('token', token.trim());
    }
    return parsed.toString();
  } catch (_e) {
    const withPath = /\/api\/ws(\?|$)/.test(wsBase)
      ? wsBase
      : `${wsBase.replace(/\/+$/, '')}/api/ws`;
    return appendTokenParam(withPath, token);
  }
}

function readArgOption(argv, flag) {
  if (!Array.isArray(argv)) return null;
  const idx = argv.indexOf(flag);
  if (idx !== -1 && typeof argv[idx + 1] === 'string' && argv[idx + 1].trim()) {
    return argv[idx + 1].trim();
  }
  const prefix = `${flag}=`;
  for (const arg of argv) {
    if (typeof arg === 'string' && arg.startsWith(prefix)) {
      const val = arg.slice(prefix.length).trim();
      if (val) return val;
    }
  }
  return null;
}

function queryControlSocket(socketPath, payload, timeoutMs = CONTROL_SOCKET_TIMEOUT_MS) {
  return new Promise((resolve) => {
    let settled = false;
    let buffer = '';
    let timer = null;
    let socket = null;

    const finish = (result) => {
      if (settled) return;
      settled = true;
      if (timer) {
        clearTimeout(timer);
        timer = null;
      }
      if (socket) {
        try {
          socket.destroy();
        } catch (_e) {
          // Ignore destroy errors
        }
      }
      resolve(result);
    };

    try {
      socket = net.createConnection({ path: socketPath });
    } catch (_e) {
      finish(null);
      return;
    }

    socket.on('error', () => {
      finish(null);
    });

    timer = setTimeout(() => {
      finish(null);
    }, timeoutMs);

    socket.on('connect', () => {
      try {
        socket.write(`${JSON.stringify(payload)}\n`);
      } catch (_e) {
        finish(null);
      }
    });

    socket.on('data', (chunk) => {
      buffer += chunk.toString('utf8');
      const newlineIdx = buffer.indexOf('\n');
      if (newlineIdx !== -1) {
        const line = buffer.slice(0, newlineIdx).trim();
        try {
          finish(line ? JSON.parse(line) : null);
        } catch (_e) {
          finish(null);
        }
      }
    });

    socket.on('end', () => {
      if (!settled) {
        const line = buffer.trim();
        try {
          finish(line ? JSON.parse(line) : null);
        } catch (_e) {
          finish(null);
        }
      }
    });

    socket.on('close', () => {
      finish(null);
    });
  });
}

async function resolveGatewayTarget(options = {}) {
  const env = options.env || process.env;
  const argv = options.argv || process.argv;
  const platform = options.platform || process.platform;
  const timeoutMs = Number.isFinite(options.timeoutMs) ? options.timeoutMs : CONTROL_SOCKET_TIMEOUT_MS;

  let overlayInfo = options.overlayInfo || null;
  if (!overlayInfo && typeof options.readOverlayInfo === 'function') {
    try {
      overlayInfo = options.readOverlayInfo();
    } catch (_e) {
      overlayInfo = null;
    }
  } else if (!overlayInfo && typeof options.overlayFilePath === 'string' && options.overlayFilePath) {
    try {
      overlayInfo = JSON.parse(fs.readFileSync(options.overlayFilePath, 'utf8'));
    } catch (_e) {
      overlayInfo = null;
    }
  }

  const explicitToken =
    options.gatewayToken ||
    readArgOption(argv, '--gateway-token') ||
    env.HERMES_GATEWAY_TOKEN ||
    env.HERMES_API_TOKEN ||
    (overlayInfo && typeof overlayInfo.gateway_token === 'string' ? overlayInfo.gateway_token : null) ||
    null;

  const explicitUrl =
    options.gatewayUrl ||
    readArgOption(argv, '--gateway-url') ||
    env.HERMES_GATEWAY_WS_URL ||
    env.HERMES_GATEWAY_URL ||
    (overlayInfo && typeof overlayInfo.gateway_url === 'string' ? overlayInfo.gateway_url : null) ||
    null;

  if (explicitUrl && String(explicitUrl).trim()) {
    return {
      url: normalizeGatewayWsUrl(explicitUrl, explicitToken),
      protocols: [],
    };
  }

  const hermesHome = options.hermesHome || defaultHermesHome(env, platform);
  const socketPath = options.controlSocketPath || controlSocketPathForHome(hermesHome, platform);

  const identifyResp = await queryControlSocket(
    socketPath,
    { protocol: 1, verb: 'identify', id: 1 },
    timeoutMs
  );

  if (
    identifyResp &&
    identifyResp.ok === true &&
    identifyResp.result &&
    typeof identifyResp.result.api_origin === 'string' &&
    identifyResp.result.api_origin.trim()
  ) {
    const result = identifyResp.result;
    const profile_id =
      (Array.isArray(result.served_profiles) &&
        result.served_profiles[0] &&
        result.served_profiles[0].profile_id) ||
      result.hermes_home ||
      path.resolve(String(hermesHome));
    const instance_id = result.instance_id;

    const ticketResp = await queryControlSocket(
      socketPath,
      {
        protocol: 1,
        verb: 'session-ticket',
        id: 1,
        params: {
          profile_id,
          instance_id,
          purpose: 'interactive',
        },
      },
      timeoutMs
    );

    const wsUrl = `${apiOriginToWs(result.api_origin)}/api/ws`;
    if (
      ticketResp &&
      ticketResp.ok === true &&
      ticketResp.result &&
      typeof ticketResp.result.ticket === 'string' &&
      ticketResp.result.ticket.trim()
    ) {
      return {
        url: wsUrl,
        protocols: ['hermes-gateway-v1', `hermes-gateway-ticket.${ticketResp.result.ticket.trim()}`],
      };
    }

    return {
      url: appendTokenParam(wsUrl, explicitToken),
      protocols: [],
    };
  }

  const port = env.HERMES_API_PORT || env.HERMES_GATEWAY_PORT || 8642;
  const fallbackUrl = appendTokenParam(`ws://127.0.0.1:${port}/api/ws`, explicitToken);
  return {
    url: fallbackUrl,
    protocols: [],
  };
}

function mapGatewayEvent(eventType, payload = {}) {
  const pluginMessages = [];
  const rendererMessages = [];
  const safePayload = payload && typeof payload === 'object' ? payload : {};

  if (eventType === 'voice.status') {
    let rawState = String(safePayload.state ?? safePayload.status ?? '').trim().toLowerCase();
    if (!rawState && typeof safePayload.listening === 'boolean') {
      rawState = safePayload.listening ? 'listening' : 'idle';
    }
    if (rawState === 'listening' || rawState === 'recording') {
      pluginMessages.push({ type: 'voice.status', state: 'listening', listening: true });
      rendererMessages.push({ type: 'state', orb: 'listening' });
    } else if (
      rawState === 'transcribing' ||
      rawState === 'processing' ||
      rawState === 'idle' ||
      rawState === 'stopped' ||
      rawState === 'off'
    ) {
      pluginMessages.push({ type: 'voice.status', state: rawState, listening: false });
      rendererMessages.push({ type: 'state', orb: 'idle' });
    } else if (rawState === 'speaking') {
      pluginMessages.push({ type: 'voice.status', state: 'speaking', listening: false });
      rendererMessages.push({ type: 'state', orb: 'speaking' });
    }
  } else if (eventType === 'wake.detected') {
    const phrase =
      typeof safePayload.phrase === 'string' && safePayload.phrase.trim()
        ? safePayload.phrase.trim()
        : 'hey hermes';
    const start_new_session = Boolean(safePayload.start_new_session);
    pluginMessages.push({ type: 'wake.detected', phrase, start_new_session });
    rendererMessages.push({ type: 'intro', phrase, start_new_session });
    rendererMessages.push({ type: 'state', orb: 'listening' });
  }

  return { pluginMessages, rendererMessages };
}

function extractEventFromFrame(frame) {
  if (!frame || typeof frame !== 'object') return null;

  if (frame.method === 'event' && frame.params && typeof frame.params === 'object') {
    const params = frame.params;
    const type =
      typeof params.type === 'string' && params.type
        ? params.type
        : typeof params.event === 'string' && params.event
          ? params.event
          : null;
    if (!type) return null;
    const payload =
      params.payload && typeof params.payload === 'object' ? params.payload : params;
    return {
      type,
      session_id: typeof params.session_id === 'string' ? params.session_id : null,
      payload,
      raw: frame,
    };
  }

  const directType =
    typeof frame.event === 'string' && frame.event
      ? frame.event
      : typeof frame.type === 'string' && frame.type
        ? frame.type
        : null;
  if (!directType) return null;

  const payload =
    frame.payload && typeof frame.payload === 'object' ? frame.payload : frame;
  return {
    type: directType,
    session_id: typeof frame.session_id === 'string' ? frame.session_id : null,
    payload,
    raw: frame,
  };
}

function parseGatewayFrames(rawText) {
  if (rawText === null || rawText === undefined) return [];
  const text = Buffer.isBuffer(rawText) ? rawText.toString('utf8') : String(rawText);
  const lines = text.split(/\r?\n/);
  const events = [];

  for (const rawLine of lines) {
    const line = rawLine.trim();
    if (!line) continue;
    let parsed;
    try {
      parsed = JSON.parse(line);
    } catch (_e) {
      continue;
    }
    const extracted = extractEventFromFrame(parsed);
    if (!extracted) continue;
    const mapped = mapGatewayEvent(extracted.type, extracted.payload);
    events.push({
      type: extracted.type,
      session_id: extracted.session_id,
      payload: extracted.payload,
      raw: extracted.raw,
      pluginMessages: mapped.pluginMessages,
      rendererMessages: mapped.rendererMessages,
    });
  }

  return events;
}

class GatewayClient {
  constructor(options = {}) {
    this.options = options;
    this.sendToPlugin = typeof options.sendToPlugin === 'function' ? options.sendToPlugin : () => {};
    this.forwardToRenderer =
      typeof options.forwardToRenderer === 'function' ? options.forwardToRenderer : () => {};
    this.onStatus = typeof options.onStatus === 'function' ? options.onStatus : () => {};
    this.WebSocketImpl = options.WebSocketImpl || WebSocket;
    this.backoffMinMs = Number.isFinite(options.backoffMinMs) ? options.backoffMinMs : GATEWAY_BACKOFF_MS;
    this.backoffMaxMs = Number.isFinite(options.backoffMaxMs) ? options.backoffMaxMs : GATEWAY_BACKOFF_MAX_MS;

    this.sock = null;
    this.stopped = false;
    this.connecting = false;
    this.backoffMs = this.backoffMinMs;
    this.reconnectTimer = null;
  }

  start() {
    this.stopped = false;
    this._connect();
  }

  stop() {
    this.stopped = true;
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    if (this.sock) {
      const s = this.sock;
      this.sock = null;
      try {
        s.removeAllListeners();
        s.on('error', () => {});
        s.terminate();
      } catch (_e) {
        // Ignore termination errors
      }
    }
  }

  _scheduleReconnect() {
    if (this.stopped || this.reconnectTimer) return;
    const delay = this.backoffMs;
    this.backoffMs = Math.min(this.backoffMaxMs, this.backoffMs * 2);
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      this._connect();
    }, delay);
  }

  async _connect() {
    if (this.stopped || this.sock || this.connecting) return;
    this.connecting = true;
    let target;
    try {
      target = await resolveGatewayTarget(this.options);
    } catch (_e) {
      this.connecting = false;
      this._scheduleReconnect();
      return;
    }
    this.connecting = false;
    if (this.stopped || this.sock) return;

    if (!target || !target.url) {
      this._scheduleReconnect();
      return;
    }

    let ws;
    try {
      ws =
        Array.isArray(target.protocols) && target.protocols.length > 0
          ? new this.WebSocketImpl(target.url, target.protocols)
          : new this.WebSocketImpl(target.url);
    } catch (_e) {
      this._scheduleReconnect();
      return;
    }

    this.sock = ws;

    ws.on('open', () => {
      if (this.stopped) return;
      this.backoffMs = this.backoffMinMs;
      this.onStatus('connected');
    });

    ws.on('message', (raw) => {
      if (this.stopped) return;
      this.handleMessage(raw);
    });

    ws.on('close', (code) => {
      if (this.sock === ws) {
        this.sock = null;
      }
      if (!this.stopped) {
        this.onStatus(`closed:${code}`);
        this._scheduleReconnect();
      }
    });

    ws.on('error', () => {
      // Handled via close event
    });
  }

  handleMessage(raw) {
    const events = parseGatewayFrames(raw);
    for (const evt of events) {
      let deliveredToPlugin = false;
      for (const pluginMsg of evt.pluginMessages) {
        try {
          if (this.sendToPlugin(pluginMsg) === true) {
            deliveredToPlugin = true;
          }
        } catch (_e) {
          // Ignore send errors
        }
      }
      if (!deliveredToPlugin) {
        for (const rendererMsg of evt.rendererMessages) {
          try {
            this.forwardToRenderer(rendererMsg);
          } catch (_e) {
            // Ignore forward errors
          }
        }
      }
    }
    return events;
  }
}

function createGatewayClient(options = {}) {
  return new GatewayClient(options);
}

module.exports = {
  GATEWAY_BACKOFF_MS,
  GATEWAY_BACKOFF_MAX_MS,
  defaultHermesHome,
  _home_hash,
  controlSocketPathForHome,
  apiOriginToWs,
  normalizeGatewayWsUrl,
  queryControlSocket,
  resolveGatewayTarget,
  mapGatewayEvent,
  parseGatewayFrames,
  GatewayClient,
  createGatewayClient,
};
