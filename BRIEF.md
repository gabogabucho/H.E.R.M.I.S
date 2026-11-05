# H.E.R.M.I.S — Brief

> Un plugin de Hermes que convierte tu escritorio en un **OS para agentes**.

Boceto visual: [`docs/boceto.html`](docs/boceto.html) (abrilo en el navegador)

## La idea

Todos los sistemas operativos se diseñaron para humanos, y la IA vino después, encima. H.E.R.M.I.S da vuelta eso **sin reinstalar nada**: lo activás y tu escritorio pasa a ser un espacio que maneja el agente. Vos hablás, Hermes actúa. Te muestra lo que necesitás y maneja tus apps como si fuera vos.

La referencia es *Her* (2013): te sentás a charlar con "ella", y ella te muestra en pantalla lo necesario o te da feedback.

Es la filosofía de [Lumen OS](https://github.com/gabogabucho/Lumen-os) ("no hay apps, hay superficies") empaquetada como plugin, arriba del Windows que ya usás.

## Qué hace (la experiencia)

1. **Despertar.** Decís la wake word, la pantalla se oscurece y aparece la bola con "¿Qué hacemos hoy?". Después la capa se vuelve transparente y vuelve tu escritorio.
2. **Mostrar: Hermes DIBUJA.** Si pedís algo para *ver* (correos, una tabla, un resumen), Hermes lo dibuja como superficie flotante sin abrir ninguna app.
3. **Hacer: Hermes MANEJA.** Si pedís algo para *hacer* (abrir Excel, dividir la pantalla, armar una playlist), Hermes maneja tus apps reales.
4. **Contexto.** Hermes siempre sabe qué hay en pantalla. Por eso "abrí el tercero" o "cerrá eso" funcionan.

## Por qué es un plugin y no un prompt

Los jueces premian lo que **no** se puede hacer con un prompt o una skill. Esto no se puede:

- **Una capa de render propia** (Electron, transparente, siempre arriba, los clics pasan donde no hay nada dibujado), conectada a Hermes por WebSocket.
- **Tools con código propio**: dibujar superficies y acomodar ventanas reales con la API de Win32.
- **Hooks**: `pre_llm_call` le pasa a Hermes qué hay en pantalla; los hooks de turno y de tool animan el estado de la bola (escuchando, pensando, actuando).
- **Estado persistente**: superficies y ventanas activas, entre turnos.

## Lo que NO construimos (Hermes ya lo trae)

| Necesidad | Lo provee Hermes |
|---|---|
| Escucha siempre activa | Wake word (openWakeWord / sherpa / Porcupine) |
| Voz a texto | Voice mode (faster-whisper local o en la nube, con conversación continua y la opción de interrumpirlo) |
| Respuesta hablada | TTS (Edge gratis, ElevenLabs, OpenAI…) |
| Clics, teclado, leer la UI | Computer use (`cua-driver`, Windows UIAutomation) |
| Gmail | Conexión que el usuario ya tiene |

Nosotros **orquestamos**: el plugin activa y configura todo esto con un solo comando.

## Arquitectura

```
Voz ──▶ Hermes (wake word + STT + LLM + TTS + computer use)
              │
              ├─ tools del plugin
              │    ├─ render_surface(surface, data)   ─┐
              │    ├─ close_surface(id)                │  WebSocket local
              │    ├─ layout_windows(apps, layout)     │  (127.0.0.1 + token)
              │    └─ launch_app(name)                 ▼
              ├─ hooks (pre_llm_call, pre/post_tool_call) ──▶ Overlay Electron
              └─ /hermis on|off                               (shell de Lumen: bola + superficies)
```

### Protocolo: `x-lumen-desktop v2`

El agente **no escribe HTML**: manda **datos** y el overlay tiene los componentes. Es más rápido, gasta menos tokens y no se rompe.

```json
{ "type": "render", "surface": "email_list", "data": { "items": [...] } }
{ "type": "render", "surface": "notification", "data": { "text": "Listo", "level": "success" } }
{ "type": "state",  "orb": "thinking" }
```

Superficies iniciales: `notification`, `document`, `email_list`, `table`, `cards`, `web`, `image`, y `custom` (HTML aislado, solo como salida de emergencia).

## Demo (menos de 90 segundos), borrador

1. Wake word → intro inmersiva → "¿Qué hacemos hoy?"
2. "Mostrame mis últimos 10 correos" → se dibuja la superficie
3. "Abrí el de Juan" → Hermes sabe cuál es por el contexto
4. "Poneme el Excel de notas a la izquierda y los trabajos a la derecha" → acomoda las ventanas

> Spotify queda **afuera** de la demo hasta tener un primer acercamiento (ver issues abiertos).

## Decisiones

| Tema | Decisión | Estado |
|---|---|---|
| Concepto | El escritorio como OS para agentes | ✅ |
| Modo visual | Capa transparente encima del escritorio + intro inmersiva | ✅ |
| Renderer | Electron | ✅ |
| Protocolo | `x-lumen-desktop v2` (superficies) | ✅ |
| Wake word | "hey hermes" / "jarvis" (Porcupine, pide key) / frase propia (sherpa) | ⏳ issue abierto |
| Guion de la demo | Borrador de arriba | ⏳ issue abierto |
| Spotify | Fuera de la demo por ahora. Primer acercamiento: computer use, con plan B en Web API o URI `spotify:` | ⏳ issue abierto |

## Riesgos

- **Spotify** muestra poco al computer use (árbol de accesibilidad pobre) → queda fuera de la demo hasta probarlo.
- **Empaquetar Electron** y lanzarlo desde el plugin en Python → hay que decidir: ejecutable ya armado o `npx electron`.
- **Catálogo** ([reglas](https://hermes-agent.nousresearch.com/docs/developer-guide/plugins/catalog-submission)): el PR a `NousResearch/hermes-agent` agrega solo `plugin-catalog/hermis.yaml`, que apunta a este repo con un **SHA completo de 40 caracteres**. Reglas que afectan el diseño:
  - **El repo tiene que ser PÚBLICO** (hoy es privado).
  - **No se permiten binarios en el repo**: nada de Electron ya empaquetado. Un componente nativo tiene que construirlo el GitHub Actions del propio repo, con atestación de build.
  - **Prohibido el código que se actualiza solo**: el plugin no puede descargar y reemplazar sus propios archivos.
  - **Hay que declarar todo**: procesos en segundo plano (el overlay y el servidor WebSocket), llamadas de red y comandos de shell.
  - **Las capabilities declaradas tienen que coincidir** con lo que el plugin registra de verdad.
  - **Las credenciales**, solo a través de `agent.secret_scope.get_secret()`.
  - **Dependencias** con un piso y un techo de versión (nada de `>=X` sin techo).
  - **Alternativa a evaluar**: el *Desktop Plugin SDK* (`desktop/plugin.js`) de Hermes podría reemplazar o complementar a Electron.
- **Windows**: computer use no puede manejar ventanas que corren como administrador (UIPI).

## Entrega

- **Fecha límite:** miércoles 11/11/2026, 17:00 EST (19:00 hora de Argentina)
- PR al catálogo de plugins de Hermes
- Video en X etiquetando a @NousResearch (menos de 90 segundos)
- Formulario: https://form.typeform.com/to/FwJLvOln
