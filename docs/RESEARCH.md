# H.E.R.M.I.S — Investigación técnica (Hermes Agent)

**Fecha:** 2026-11-05 · **Método:** docs oficiales + código fuente de `NousResearch/hermes-agent` (v0.22.7, branch `main`) vía `gh api` + `webfetch`. Cada hallazgo está marcado **VERIFICADO** (URL o path de archivo) o **INFERIDO** (deducción no confirmada por doc/código directo).

---

## TL;DR

- **El Desktop Plugin SDK NO reemplaza a nuestro Electron.** Los plugins desktop viven solo DENTRO de la ventana de Hermes Desktop (panes, statusbar, palette…); no pueden crear ventanas del SO ni overlays always-on-top — esas features del core no están expuestas al SDK. VERIFICADO.
- **Electron sí es viable para el catálogo**, con disclosure: hay precedentes — `spotify-desktop` ("Electron status-bar player plus a dashboard-API backend") y el plugin oficial `snyk`, que corre por `npx` con versión pineada. Nada de binarios commiteados; `npm i electron` + `npx electron` pineado pasa como patrón aceptado. VERIFICADO el precedente, INFERIDO la aceptación exacta del combo.
- **Nos ahorramos construir**: wake word (frase default "jarvis", Win x64 ok), STT/TTS (faster-whisper local en Win x64 + Edge TTS gratis), clics/teclado/leer UI (`computer_use` sobre cua-driver/UIAutomation), **listar ventanas y enfocar apps** (acciones `list_windows`/`list_apps`/`focus_app`), y todo el lado Gmail (skill google-workspace con OAuth gestionada por Hermes). VERIFICADO.
- **Seguimos construyendo**: el overlay Electron + WebSocket (nadie en el catálogo hace overlay a nivel SO — es nuestro diferencial), `layout_windows` (no hay move/resize de ventanas en Hermes) y `launch_app` (no está en el core; THEIA lo agrega como tools propias — precedente válido). VERIFICADO.
- **La bola se anima con eventos reales**: el gateway emite `voice.status`, `voice.partial`, `voice.interrupted` y `wake.detected` por WebSocket; el overlay puede conectarse como cliente. En Python no hay hooks de voz (solo `pre_transcription`). VERIFICADO los eventos, INFERIDO la conexión del overlay como cliente.

> **Revisión (Claude Code, 2026-11-05).** Verifiqué contra el código de `NousResearch/hermes-agent@main`:
> - ✅ `computer_use` no tiene acciones de mover, redimensionar ni lanzar apps (`tools/computer_use/schema.py`).
> - ✅ "Native-only features stay in Electron: … always-on-top overlays…" (`website/docs/user-guide/desktop.md`).
> - ✅ `ctx.set_config` escribe solo en el subárbol `settings` del plugin (`hermes_cli/plugins.py:278`).
> - ✅ Existen `meeting-overlay`, `spotify-desktop`, `hermes-windows-computer-use` y `orbit-desktop` en `plugin-catalog/`. El último release es v0.22.7 (2026-11-03).
>
> ❌ **Error del informe:** la frase por defecto de la wake word es **"hey hermes"**, no "jarvis" (`hermes_cli/config_defaults.py:1257`; la doc dice *"Porcupine's default keyword is \"jarvis\""*). Para "hey jarvis" gratis: `wake_word.openwakeword.model: hey_jarvis`, un modelo incluido en openWakeWord (`config_defaults.py:1266`). Corregir donde el informe dice "default jarvis".
>
> ⚠️ **El informe no destaca esto:** Hermes Desktop ya trae un **HUD** (⌘/Ctrl+Shift+H). Saca el chat a una barra flotante, sin marco y siempre arriba, con clics que pasan a través, *"sobre lo que estés trabajando"*. Su posición en pantalla es contexto: "esto", "acá" y "esa página" se refieren a lo que tiene debajo. **Un overlay flotante sobre el escritorio, solo, NO es diferencial.** El diferencial es que **el agente dibuja superficies de datos** (correos, tablas, tarjetas) y **acomoda ventanas reales**; el HUD es un chat, no un lienzo. Esto hay que dejarlo explícito en el pitch y en la demo.

---

## Lo que nos ahorramos

| Componente planeado | ¿Hermes ya lo provee? | Cómo | V/I | Fuente |
|---|---|---|---|---|
| Wake word "hey hermes"/"jarvis" | ✅ Sí | `wake_word.phrase` (default "jarvis"); motores openWakeWord (Win x64), sherpa (ARM64), Porcupine (key) | V | `website/docs/user-guide/features/wake-word.md` |
| STT (voz a texto) | ✅ Sí | Voice mode con faster-whisper **local** en Win x64 (excluido solo ARM64/Intel Mac); nube: groq/openai/mistral/xai/elevenlabs/deepinfra | V | `website/docs/user-guide/features/voice-mode.md` |
| TTS (respuesta hablada) | ✅ Sí | `tts.provider: edge` default, gratis sin key; + elevenlabs/openai/piper/etc. | V | ídem |
| Clics, teclado, leer la UI | ✅ Sí | Tool `computer_use` (cua-driver Rust v0.21.0 vía MCP stdio; Windows: UIAutomation + SendInput) | V | `tools/computer_use/schema.py` |
| Listar ventanas/apps | ✅ Sí | Acciones `list_windows`, `list_apps` del tool `computer_use` → nos ahorramos `list_windows` propio | V | ídem |
| Enfocar ventanas | ✅ Parcial | `focus_app` (+`raise_window`) en core; `computer_use_focus_window` existe como patrón THEIA | V | ídem + `plugin-catalog/hermes-windows-computer-use.yaml` |
| Gmail (leer correos) | ✅ Sí | Skill bundled `skills/productivity/google-workspace` (CLI GAPI, OAuth de Hermes) o conector hosted `hermes connectors connect gmail` | V | `skills/productivity/google-workspace/SKILL.md`, `tools/connectors/tool.py` |
| Estados de la bola por voz | 🟡 Parcial | Eventos gateway WS `voice.status`/`wake.detected` existen; NO hay hooks Python de voz | V/I | `tui_gateway/contracts/events.py` |
| Contexto de pantalla automático | ❌ No | El agente puede capturar con `computer_use`, pero nadie inyecta pantalla en cada turno → nuestro hook `pre_llm_call` sigue siendo aporte | I | `hermes_cli/plugins.py` |
| Overlay transparente always-on-top | ❌ No | El SDK desktop no crea ventanas del SO; los overlays del core (`apps/desktop/electron/hud-overlay.ts`) no están expuestos | V | `website/docs/user-guide/desktop.md` |
| `layout_windows` (split/grid) | ❌ No | No hay acciones de move/resize de ventanas → Win32 propio | V | `tools/computer_use/schema.py` |
| `launch_app` | ❌ No | No hay acción de lanzar apps en el core (THEIA la agrega como tool propia) | V | ídem |
| Superficies (bola + panes flotantes) | ❌ No | Shell de Lumen portable (~70% as-is) | V/I | `gabogabucho/Lumen-os/os/shell/` |

---

## 1. Desktop Plugin SDK (`desktop/plugin.js`)

- **Qué es Hermes Desktop:** Electron — `apps/desktop/electron/*.ts` (main) + `apps/desktop/src/` (renderer React), instaladores Windows/macOS. **VERIFICADO** (árbol del repo).
- **El SDK:** un plugin desktop es **un archivo ESM** `desktop/plugin.js` (en `$HERMES_HOME/desktop-plugins/<id>/` o dentro del paquete unificado `~/.hermes/plugins/<id>/desktop/plugin.js`). Solo puede importar `@hermes/plugin-sdk`, `react`, `react/jsx-runtime`. Hot-reload; 10 s de deadline de evaluación; corre en el renderer con autoridad total. **VERIFICADO** (`website/docs/developer-guide/desktop-plugin-sdk.md`, `apps/desktop/src/sdk/index.ts`).
- **Qué permite:** contribuir áreas del shell estilo VS Code — **panes** (dock o `placement: 'floating'`, que es una tarjeta arrastrable *dentro* de la ventana), routes, sidebar, status bar, title bar, palette ⌘K, keybinds, themes, composer, session rows, kanban badges, tool media renderers, settings pages. APIs: `ctx.register({area, id, data, render})`, `ctx.rest`/`ctx.socket`, `ctx.storage`/`ctx.files`, `ctx.os.{notify,openExternal,writeClipboard}`, `host.request` (JSON-RPC al gateway), `host.onEvent`, `host.composer`, `ctx.runAction` (solo acciones de vista). **VERIFICADO**.
- **¿Ventanas FUERA de la app (transparente/always-on-top/click-through)? NO.** `ctx.runAction` rechaza explícitamente abrir ventanas nuevas; la doc lo dice sin rodeos: *"Native-only features stay in Electron: global shortcuts, always-on-top overlays, OS-window inspection, external-terminal launch and the updater"*. El core tiene overlays (`apps/desktop/electron/hud-overlay.ts` con `setAlwaysOnTop(true,'screen-saver')`, y `wake-indicator-window.ts`) pero **no hay puerta SDK** hacia ellos. **VERIFICADO**.
- **¿Reemplaza o complementa a nuestro Electron? Complementa.** Para el overlay a nivel SO necesitamos un proceso Electron aparte, fuera del SDK. **VERIFICADO**.
- **Comunicación desktop plugin ↔ plugin Python:** paquete unificado — un mismo plugin instala `plugin.yaml` (mitad agente Python: tools/hooks) + `desktop/plugin.js` (mitad desktop) + `dashboard/plugin_api.py` (router FastAPI que corre en el proceso gateway). Desde JS: `ctx.rest('/board')` → `GET /api/plugins/<id>/board`; `ctx.socket('/events')` → WebSocket al mismo namespace. Push Python→desktop: `broadcast_plugin_event(plugin_id, event, payload)` (`hermes_cli/plugin_events.py`) llega como evento wire `plugin.<id>.<event>` vía `host.onEvent`. **VERIFICADO**.
- Nota de desarrollo: `hermes plugins doctor` advierte cuando la app Desktop corre una copia vieja del `plugin.js` (flujo "unified package"). **VERIFICADO**.

## 2. Reglas del catálogo vs Electron

- **El catálogo** (`plugin-catalog/` en el repo de Hermes, ~979 entradas): un YAML por plugin; el usuario instala con `hermes plugins install <name>`; el PR solo agrega `plugin-catalog/<name>.yaml` con **SHA completo de 40 hex** obligatorio. Validación local = mismo check del CI: `hermes plugins validate /path --install-deps`. **VERIFICADO** (`plugin-catalog/README.md`).
- **Esquema exacto de la entrada** — campos: `name`, `repo`, `sha` (40-hex), `subdir`, `description`, `maintainer`, `tier` (official|verified|community), `category` (desktop|memory|platform|web|tools|voice|automation|models|general), `requires_hermes` (piso SemVer, nunca mayor al release actual), `docs_url`, `version`, `image`, `screenshots`, `readme`, `platforms`, `title`, `onboarding`, `known_issues`, `capabilities: {provides_tools, provides_hooks, provides_middleware, requires_env}`. **VERIFICADO**.
- **Ejemplo real, verbatim** (`plugin-catalog/meeting-overlay.yaml @ main`):

```yaml
name: meeting-overlay
repo: https://github.com/taxbax/meeting-overlay
sha: 2c7859f1407f516c543d4409abab98d9b2e8928a
description: "Disclosure — sends meeting transcripts to Nous inference with your Hermes login (fallback OpenRouter key from ~/.hermes/.env; optional OCTOPUS_DESK_URL); installs a launchd agent that records mic/system audio; writes and deletes under your Obsidian vault; macOS + source install only. Native desktop pane showing the live meeting transcript, answer, and daemon status."
maintainer: taxbax
tier: community
category: desktop
capabilities:
  provides_tools: []
  provides_hooks: []
  provides_middleware: []
  requires_env: []
platforms:
- macos
```

- **Reglas que afectan nuestro diseño:** sin binarios commiteados en el repo (regla 17; excepción explícita: build por GitHub Actions del propio repo con atestación); sin self-updating code; disclosure de procesos en background, llamadas de red y comandos de shell en la `description` (regla 13); capabilities declaradas = realidad registrada (el validate bloquea si difieren); secretos solo vía `agent.secret_scope.get_secret()`; dependencias con piso **y** techo. **VERIFICADO**.
- **¿Electron como dependencia npm + npx/node?** Hay precedente directo en el catálogo: `spotify-desktop` (Electron status-bar player + backend dashboard API) y `hermes-taskbar-badge` (app Electron que mapea la Badging API al taskbar de Windows). Además el plugin oficial `snyk` corre `snyk@1.1306.0` **pineado por npx** — el patrón "dependencia npm con versión pineada lanzada por npx" está aceptado. `npm i electron` descarga un binario en install-time (no commiteado), lo que la regla 17 permite; con disclosure correcta es INFERIDO que pasa review. **VERIFICADO** los precedentes, **INFERIDO** la aceptación del combo exacto.
- **Versión actual para `requires_hermes`:** último release **v0.22.7** (2026-11-03). Ejemplos del catálogo usan pisos como `>=0.19`, `>=0.21.5` → para nosotros `">=0.22"` (o `>=0.21.5` si no usamos APIs nuevas). Python requerido `>=3.11,<3.15`. **VERIFICADO** (`gh api .../releases/latest`, `pyproject.toml`).
- Python deps: `pyproject.toml` junto a `plugin.yaml` (gana sobre `python_dependencies` del manifest), con piso y techo. **VERIFICADO**.

## 3. Computer use en Windows

- **Un solo tool: `computer_use`**, con parámetro `action` enum: `capture`, `click`, `double_click`, `right_click`, `middle_click`, `drag`, `scroll`, `type`, `key`, `set_value`, `wait`, `list_apps`, `list_windows`, `focus_app`; más `raise_window` y `delivery_mode: background|foreground`. Modos de captura: `som` (overlay numerado + árbol de accesibilidad), `vision` (screenshot), `ax` (solo árbol). **VERIFICADO** (`tools/computer_use/schema.py`).
- **Driver:** cua-driver (binario Rust de `trycua/cua`, v0.21.0 pineada) servido por **MCP stdio**; en Windows usa UIAutomation + SendInput/PostMessage. Comandos: `hermes computer-use install/status/doctor` (con flags `--include/--skip/--json`). **VERIFICADO**.
- **¿Mueve/redimensiona ventanas? NO. ¿Lanza apps? NO.** Listar: sí (`list_windows`, `list_apps`). Enfocar: `focus_app`. cua-driver expone además tools MCP extra fuera del schema (`get_window_state`, `bring_to_front` — parseados en `tools/computer_use/cua_backend_parse.py`). **VERIFICADO** el schema, **INFERIDO** lo extra de MCP.
- **¿Un plugin puede llamarlas con `ctx.dispatch_tool`? SÍ.** `ctx.dispatch_tool("computer_use", {...})` invoca cualquier tool registrada (built-in o de otro plugin) pasando por el pipeline normal de approvals/credenciales. **VERIFICADO**.
- **Consecuencia para el plan:** nos ahorramos `list_windows` y el foco (dispatch a `computer_use`); `layout_windows` y `launch_app` siguen nuestros (precedente THEIA: el plugin `hermes-windows-computer-use` registra `computer_use_open_app`, `computer_use_focus_window`, `computer_use_get_active_window`, etc. vía `register_tool`). **VERIFICADO**.

## 4. Voz y wake word en Windows x64

- **Wake word funciona en Win x64**: openWakeWord (default `auto`), sherpa (ARM64), Porcupine (pide key). Frase por defecto: **"jarvis"**. Corre en CLI/TUI/Desktop (`wake_word.surface: auto|cli|tui|gui`); no corre en gateway. Troubleshooting Windows específico: si "escucha pero recibe silencio", fijar `wake_word.input_device`. **VERIFICADO** (`website/docs/user-guide/features/wake-word.md`).
- **Voice mode funciona en Win x64**: STT local faster-whisper soportado (excluido solo en Win ARM64 e Intel Mac); TTS default `edge` gratis sin key; conversación continua con barge-in; streaming. **VERIFICADO** (`voice-mode.md`).
- **Keys de config.yaml** (`hermes_cli/config_defaults.py`, `cli-config.yaml.example`):
  - `wake_word.{enabled, surface, input_device, capture, provider(auto|openwakeword|sherpa|porcupine), phrase, sensitivity, confirmation_frames, start_new_session, profile_routing, openwakeword.model, porcupine.keyword}`
  - `stt.{provider(local|groq|openai|mistral|xai|elevenlabs|deepinfra), streaming, language, local.model}`
  - `tts.{provider(edge|elevenlabs|openai|neutts|minimax|mistral|gemini|xai|kittentts|piper)}`
  - `voice.{record_key, stop_phrases, barge_in, barge_in_*, client_direct, voice_chat_mode(chained|gpt_live), gpt_live.*}`
  **VERIFICADO**.
- **¿Un plugin puede activar/configurar voz? NO directamente.** `ctx.set_config()` solo alcanza `plugins.entries.<id>.settings` (namespace propio del plugin) — no puede encender voice/wake global. **VERIFICADO**.
- **Hooks/eventos de estado de voz:** el gateway emite por WS `voice.status {state}` (idle/listening/transcribing…), `voice.partial` (STT en vivo), `voice.transcript`, `voice.interrupted` (barge-in), `wake.detected {phrase, profile, start_new_session}`. Un cliente UI se suscribe con `host.onEvent('voice.status', fn)`. **PERO** en Python los hooks de plugin NO incluyen estados de voz: lo más cercano es `pre_transcription`. **VERIFICADO** (`tui_gateway/contracts/events.py`, `VALID_HOOKS` en `hermes_cli/plugins.py`).
- **Para la bola:** el overlay Electron puede conectarse como **cliente al WebSocket del gateway** (el mismo stream que consumen TUI/Desktop) y recibir `voice.status`/`wake.detected` sin inventar nada. **INFERIDO** (falta confirmar auth/puerto del WS local — ver riesgos).

## 5. Gmail

- **Cuatro caminos, ninguno requiere que construyamos correo:**
  1. Skill bundled `skills/productivity/google-workspace` — CLI `GAPI` con `gmail get/send/...` y sintaxis de búsqueda de Gmail; OAuth gestionada por Hermes (`google_token.json` del perfil); deps en el extra `[google]`. **VERIFICADO**.
  2. Plugin de catálogo `gmail` (`plugin-catalog/gmail.yaml` → `guberm/hermes-gmail-desktop-plugin`): mailbox UI desktop que usa el OAuth Google ya configurado. **VERIFICADO**.
  3. Conector hosted: `hermes connectors connect gmail` (Nous account). **VERIFICADO** (`tools/connectors/tool.py`).
  4. IMAP/SMTP genérico (App Password) vía gateway de email. **VERIFICADO** (`website/docs/user-guide/messaging/email.md`).
- **No hay tools `gmail_*` nombradas**: el agente lee correos con la skill/comandos. Para `email_list` solo necesitamos dibujar los datos que Hermes entrega. **VERIFICADO**.
- Si quisiéramos OAuth propio algún día: el manifest soporta un bloque `oauth:` gestionado por Hermes (`hermes auth add <plugin>:<id>`, token refrescado por el host, llamado vía `credentialed_provider_request`). **VERIFICADO** (guía de plugins).

## 6. Developer guide — lo útil para nosotros

- **Plugin LLM Access:** `ctx.llm` con credenciales del host y fail-closed trust gate; `complete`/`complete_structured`; pedir el modelo del propio agente requiere capability (`llm.side_question`, etc.). Nos sirve solo si la bola necesita razonar por su cuenta — para el MVP, no. **VERIFICADO**.
- **Observer Hooks:** payloads keyword-only; los callbacks deben aceptar `**kwargs` (el validate lo exige). Retornos que cambian el flujo: `pre_llm_call` → `{"context": ...}` (inyección de contexto — exactamente lo que necesitamos para "qué hay en pantalla") o `{"action": "block"}`; `pre_tool_call` → block/modify args (fail-closed); `transform_tool_result`/`transform_llm_output`. Timeout default de callback: 30 s → el contexto de pantalla tiene que salir de un cache, no de capturas en caliente. Lista completa de hooks (47) en `VALID_HOOKS` (`hermes_cli/plugins.py:109-204`): incluye `pre_tool_call`, `post_tool_call`, `on_stream_start/delta/end`, `on_session_start/end`, `pre_transcription`, `gateway_platform_event`, etc. **VERIFICADO**.
- **Middleware:** `ctx.register_middleware` interviene el pipeline de tools — no lo necesitamos para el MVP. **VERIFICADO**.
- **Event Hooks:** eventos del gateway vía drop-in `~/.hermes/hooks/<name>/` (HOOK.yaml + handler.py) o `hooks:` en config.yaml — alternativa a los hooks Python; no necesaria si el overlay escucha el WS del gateway. **VERIFICADO**.
- **Application declarations:** aplica a servidores MCP declarados en paquetes portables (`app`, `requires`, `liveness`, `trust`, costs/spend_limit) — no aplica a nuestro diseño (nuestras tools son nativas Python). **VERIFICADO**.
- **Extending the Dashboard:** extensión web del dashboard (tabs, shell slots, themes) vía `dashboard/manifest.json` + `plugin_api.py` — el mismo backend FastAPI que usaría un desktop plugin; opcional para nosotros. **VERIFICADO**.
- **ctx Python útil** (`hermes_cli/plugins.py`): `register_tool/hook/command/cli_command/middleware/computer_use_provider`, `dispatch_tool(name, args)`, `call_mcp`, `get_config/set_config` (namespaced), `state`, `plugin_data_dir`/`plugin_db`, `secret_scope.get_secret`, `emit/subscribe`, `llm.complete`, `register_system_prompt_section`, `has_plugin`, `session_surface`, `profile_name`. **No existe** `ctx.set_status`. **VERIFICADO**.

## 7. Competencia / inspiración

- **`outsourc-e/hermes-workspace`** (6.8k★): web UI "zero-fork" que se conecta al gateway (:8642) y dashboard (:9119) de Hermes; no es plugin ni fork. Su **PR #41** (de `gabogabucho`, merged 2026-04-12) agrega el evento `artifact.created` → tab "Artifacts" en el Inspector (title/kind/path), con filosofía documentada en `docs/agent-authored-ui-state.md`: *shell delgado — el agente emite, el cliente renderiza*. **Reutilizable como semántica/contrato, NO como UI**: no hay superficies flotantes ni layout del agente. **VERIFICADO** (repo + archivos del PR).
- **En el catálogo (lo más cercano):**
  - `orbit-desktop` — "Your workspace, shaped by your agent": el competidor filosófico más cercano, pero solo Linux y todo vive dentro de su propio browser-desktop, no sobre el SO. **VERIFICADO**.
  - `meeting-overlay` — pane nativo con transcripción; macOS only, in-app. **VERIFICADO**.
  - `nine-balance-widget` — widget flotante pero DENTRO de la ventana de Hermes Desktop. `perf-hud`, `home-dashboard`, `sticky-notes`, `sketch-pad`, `echarts-in-chat` (generative UI dentro del chat). **VERIFICADO**.
  - `spotify-desktop` — Electron status-bar player + backend dashboard API (precedente clave para nosotros). `hermes-taskbar-badge` — badge de taskbar Windows. **VERIFICADO**.
  - THEIA `hermes-windows-computer-use` — 37+ tools de computer-use Windows (incluye `computer_use_open_app`, `computer_use_focus_window`, `computer_use_get_active_window`); control por captura+acción, sin UI. Suite `hermes-windows-ops/process/tasks/ports/...`. **VERIFICADO**.
- **Comunidad:** hermes-webui (19.4k★), fathah/hermes-desktop (14.5k★), awesome-hermes-agent (sección "surfaces"), oh-my-hermes (5.1k★), Hermes-CN-Desktop (Tauri, Windows-first). **Nadie hace overlay de UI generativa a nivel SO en Windows dirigido por Hermes.** **VERIFICADO** las búsquedas, **INFERIDO** el gap.
- **Posicionamiento:** los jueces ya tienen referencias "más que un prompt" (THEIA, orbit-desktop). Nuestro moat: el agente **dibuja sobre el sistema operativo** (superficies flotantes fuera de toda app) y **manipula ventanas reales** — el SDK oficial no puede hacer ninguna de las dos por diseño. La voz/wake word de Hermes ya usa "jarvis" como default: el imaginario Jarvis es parte del pitch oficial de Nous. **VERIFICADO**.

## 8. Reuso de Lumen OS

Auditoría de `gabogabucho/Lumen-os` (privado, leído vía `gh api`): `os/shell/shell.js` (25.5 KB, 875 líneas), `shell.css` (9.3 KB, 424 líneas), `apps/` (browser, document, filesystem, profile, settings), `docs/protocol.md`.

- **shell.js:** vanilla JS + Web Components, **cero dependencias, cero APIs Electron/Tauri, cero localStorage**. Componentes: `<lumen-orb>` (SVG, 4 estados CSS: idle/thinking/speaking/acting — exactamente los estados que planeamos), `<lumen-window>` (drag por header, clamp a viewport), cliente WebSocket propio con reconexión cada 3 s, dispatcher `_handleSurface()` (switch de surfaces), notificaciones con auto-dismiss, posicionador de ventanas. **VERIFICADO**.
- **shell.css:** glassmorphism (`backdrop-filter: blur(20px) saturate(180%)`), radius 18px, **ya usa `pointer-events: none` en la raíz y `auto` en interactivos** — el patrón click-through del overlay ya está resuelto. Solo tema light (sin dark). **VERIFICADO**.
- **Protocolo (`docs/protocol.md`)** — ya se llama "x-lumen-desktop (v2 — Surfaces)": envelope real `{"type":"desktop_event","payload":{"surface":"document","data":{...}}}` y el orb como surface `{"surface":"orb","state":"idle|thinking|speaking|acting"}`. Semánticamente **idéntico** a lo que planeamos; sintácticamente distinto (nosotros: `{"type":"render"}` al toplevel y `{"type":"state","orb":...}`). `notification {text, level:"success"}` coincide 1:1. Adaptador de envelope: ~30 líneas. **VERIFICADO**.
- **Portabilidad:**

| Componente | Veredicto |
|---|---|
| Orb (JS+CSS, 4 estados) | ✅ Portable as-is |
| Ventana flotante / contenedor de surfaces | ✅ Portable as-is |
| Notificaciones + animaciones | ✅ Portable as-is |
| CSS visual (glassmorphism) | ✅ Portable as-is (ajustar `body` a transparente) |
| WS client + dispatcher de surfaces | 🟡 Con adaptación (traductor de envelope + URL) |
| Renderer document/markdown | 🟡 Con adaptación (quitar save→API de Lumen) |
| Surface web (iframe sandboxeado) | 🟡 Con adaptación (revisar sandbox en Electron) |
| Resolución de sesión / API Lumen Agent | 🔴 Rewrite |
| Apps filesystem / profile / settings | 🔴 Descartar (acopladas a la API del OS) |
| `email_list`, `table`, `cards` | 🔴 Nuevos (no existen en Lumen) |
| `LumenVoice` (Web Speech) | 🔴 Descartar (Hermes ya trae STT/TTS) |

- **Balance:** ~70% portable as-is, ~25% con adaptación, ~5% rewrite. El costo real está en las surfaces nuevas (`email_list`, `table`, `cards`) y en el host Electron, no en portar la shell. **VERIFICADO**.

---

## Recomendación de arquitectura

**Híbrido: plugin Python + Electron aparte + desktop/plugin.js opcional.**

| Opción | Veredicto | Tradeoffs |
|---|---|---|
| **Solo Desktop SDK** | ❌ Descartada | Bloqueo duro VERIFICADO: sin ventanas del SO, sin always-on-top, sin click-through. Sería "otra app más", no un OS para agentes. A favor: consent UI, settings form, distribución trivial. |
| **Solo Electron "agnóstico"** (sin plugin Hermes) | ❌ Descartada | Sin tools/hooks el agente no puede dibujar ni actuar; no pasa el bar de "más que un prompt". |
| **Híbrido** (recomendada) | ✅ | Plugin Python (`plugin.yaml` + `tools.py` + hooks + servidor WS local 127.0.0.1) que registra `render_surface`, `close_surface`, `list_surfaces`, `layout_windows`, `launch_app` y el hook `pre_llm_call` (contexto de pantalla cacheado). Overlay Electron aparte (transparente, always-on-top, click-through) lanzado con `npx electron@<pin>` — disclose en la description (regla 13), fallback: build GH Actions con atestación (regla 17). El paquete unificado permite agregar un `desktop/plugin.js` mínimo (pane con estado del overlay + settings form) sin costo extra. |

Detalles que salen gratis con la arquitectura híbrida:

- **Estados de la bola sin hooks de voz:** el overlay se conecta como cliente al WS del gateway → `voice.status` (listening/transcribing), `wake.detected` (intro inmersiva), `voice.partial`; `pre_llm_call`/`post_tool_call` (Python → `broadcast_plugin_event` o el propio WS del plugin) cubren pensando/actuando. **INFERIDO** la parte del cliente gateway.
- **Protocolo:** mantener `x-lumen-desktop v2` como lo planeamos y portar el dispatcher de Lumen con un adaptador de envelope (~30 líneas). El agente manda datos, el overlay renderiza — misma filosofía que el PR #41 de hermes-workspace validó en producción.
- **Computer use por delegación:** `list_windows`/foco via `ctx.dispatch_tool("computer_use", ...)`; solo `layout_windows` y `launch_app` con Win32 propio.
- **Email:** cero código de correo — `email_list` es solo un componente de superficie que recibe datos.

## Esquema de la entrada del catálogo — `plugin-catalog/hermis.yaml`

```yaml
name: hermis
repo: https://github.com/gabogabucho/H.E.R.M.I.S
sha: <SHA COMPLETO DE 40 HEX del commit pineado>   # obligatorio
subdir: .
description: >-
  Turns your Windows 11 desktop into an agent OS: Hermes draws floating data
  surfaces over your real desktop (orb + surfaces; the agent sends data, not
  HTML), manages real windows (split/maximize/grid) and launches apps.
  Disclosure: ships a transparent always-on-top Electron overlay launched via
  pinned `npx electron@<version>` (npm install downloads the Electron binary;
  nothing packaged in-repo), a background local WebSocket server bound to
  127.0.0.1, and local-only Python tools/hooks. Voice, wake word and computer
  use come from Hermes itself.
maintainer: gabogabucho
tier: community
category: desktop
requires_hermes: ">=0.22"
version: 0.1.0
platforms:
- windows
docs_url: https://github.com/gabogabucho/H.E.R.M.I.S#readme
capabilities:
  provides_tools:
  - render_surface
  - close_surface
  - list_surfaces
  - layout_windows
  - launch_app
  provides_hooks:
  - pre_llm_call
  - pre_tool_call
  - post_tool_call
  provides_middleware: []
  requires_env: []
```

Notas: capabilities deben coincidir EXACTO con lo registrado en `register()` (el validate bloquea el catálogo si difieren); correr `hermes plugins validate . --install-deps` antes del PR (es el mismo check del CI); `requires_hermes` es piso SemVer, nunca mayor al release actual (v0.22.7).

## Riesgos y preguntas abiertas

1. **UIPI (Windows):** computer use y nuestro `layout_windows` (Win32) no pueden controlar/mover ventanas que corren como administrador. Ya está en BRIEF; recordar en la demo (no abrir apps elevadas). INFERIDO para el Win32 propio.
2. **WS del gateway para la bola:** falta confirmar puerto y auth para que el overlay se conecte como cliente local y reciba `voice.status`/`wake.detected`. Verificar en `tui_gateway/` antes del Día 1. INFERIDO.
3. **`npx electron` vs build con atestación:** el download del binario de Electron en install-time puede levantar preguntas del review del catálogo. Decidir antes del Día 5; si dudan, GH Actions + `attest-build-provenance` está explícitamente permitido (regla 17). INFERIDO.
4. **`/hermis on|off` no puede encender voz/wake global:** `ctx.set_config` es namespaced al plugin. Alternativa: el comando guía la configuración (check `hermes computer-use doctor`, instrucciones de `/voice on`) o abrir issue pidiendo superficie de config al equipo. Impacto en ROADMAP Día 4.
5. **Estado "speaking" de la bola:** `voice.status` cubre idle/listening/transcribing; el momento exacto de "TTS hablando" hay que confirmarlo (o aproximarlo con `post_llm_call`). Verificar con el protocolo real.
6. **`pre_llm_call` con timeout de 30 s:** la inyección de contexto de pantalla debe leer un cache (superficies + lista de ventanas ya relevadas), nunca capturar en caliente.
7. **Repo privado → público** antes del PR al catálogo (regla). Ya está en BRIEF.
8. **Wake word en Desktop app (surface `gui`):** confirmar en la máquina real que "jarvis" despierta con Hermes Desktop en Windows (pendiente del Día 0 del ROADMAP).
9. **Flujo email real:** sin tools `gmail_*`, "últimos 10 correos" depende de que el agente use la skill google-workspace; probar el flujo punta a punta (Día 2) y tener IMAP como plan B.
10. **Hook ausente:** si la bola necesita estados de voz desde Python (sin depender del cliente gateway), pedirlo como issue upstream ("If a public hook you need is missing, open an issue" — política oficial del plugin system).

### Fuentes principales

- Docs: `https://hermes-agent.nousresearch.com/docs/developer-guide/plugins` (+ Desktop Plugin SDK en `/docs/developer-guide/desktop-plugin-sdk`, Observer Hooks, Middleware, LLM Access, Application declarations, Extending the Dashboard), `/docs/developer-guide/plugins/catalog-submission`, `/docs/user-guide/features/{computer-use,voice-mode,wake-word,desktop,hooks}`, `/docs/plugins` (marketplace, 977 plugins).
- Código (`NousResearch/hermes-agent` @ main, v0.22.7): `plugin-catalog/README.md`, `plugin-catalog/{meeting-overlay,spotify-desktop,hermes-windows-computer-use,gmail}.yaml`, `tools/computer_use/schema.py`, `hermes_cli/plugins.py` (`VALID_HOOKS`), `hermes_cli/config_defaults.py`, `tui_gateway/contracts/events.py`, `apps/desktop/src/sdk/index.ts`, `apps/desktop/electron/hud-overlay.ts`, `website/docs/**`.
- Comunidad: `https://github.com/outsourc-e/hermes-workspace` (+ PR #41), `https://github.com/0xNyk/awesome-hermes-agent`.
- Lumen OS: `gabogabucho/Lumen-os` — `os/shell/shell.js`, `os/shell/shell.css`, `docs/protocol.md`.
