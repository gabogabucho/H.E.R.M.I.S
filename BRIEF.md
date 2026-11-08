# H.E.R.M.I.S — Brief

> Un plugin de Hermes que agrega el **Modo Piloto Automático**: tu escritorio se convierte en un **OS para agentes**. No le escribís: le hablás, y Hermes dibuja en pantalla y maneja tus apps.

- Boceto visual: [`docs/boceto.html`](docs/boceto.html) (abrilo en el navegador)
- Investigación técnica: [`docs/RESEARCH.md`](docs/RESEARCH.md)
- Plan: [`ROADMAP.md`](ROADMAP.md)

> **Estado: en desarrollo (Día 1).** Propuesta aprobada por el equipo (#5).

## La idea

Todos los sistemas operativos se diseñaron para humanos, y la IA vino después, encima. H.E.R.M.I.S da vuelta eso **sin reinstalar nada**.

Hermes trabaja normal hasta que le decís **"Hey Hermes, modo piloto automático"**. Ahí **cambia de forma**: aparece una barra que se comprime en una **bola** (el orbe), y a partir de ese momento Hermes:

- **te habla** en vez de escribirte, con respuestas cortas;
- **DIBUJA** en pantalla lo que necesitás ver (correos, tablas, tarjetas, documentos) como superficies flotantes;
- **MANEJA** tus apps reales: abre, enfoca y acomoda ventanas.

Decís "salí del piloto automático" y vuelve a ser el Hermes de siempre.

La referencia es *Her* (2013): te sentás a charlar con "ella", y ella te muestra en pantalla lo necesario. La filosofía es la de [Lumen OS](https://github.com/gabogabucho/Lumen-os) ("no hay apps, hay superficies"), empaquetada como plugin, arriba del Windows que ya usás.

## Qué hace (la experiencia)

1. **Activación + morph.** "Hey Hermes" (el modelo `hey_hermes` viene incluido en Hermes, sin configurar nada) → "modo piloto automático" → la pantalla se oscurece, una barra se comprime en el orbe → "¿Qué hacemos hoy?" → la capa se vuelve transparente y vuelve tu escritorio.
2. **Mostrar: Hermes DIBUJA.** Si pedís algo para *ver*, Hermes lo dibuja como superficie flotante sin abrir ninguna app. Puede ser un dato que trajo con cualquiera de sus tools o skills (correos, una tabla, una lista), o un **artefacto** que ya sabe generar (un gráfico o un dashboard en HTML o SVG).
3. **Hacer: Hermes MANEJA.** Si pedís algo para *hacer* (abrir Excel, dividir la pantalla), Hermes maneja tus apps reales.
4. **Contexto.** Hermes sabe qué hay en pantalla. Por eso "abrí el tercero" o "cerrá eso" funcionan.
5. **El orbe está vivo.** Muestra si está escuchando, pensando, actuando o hablando.
6. **Salida.** "Salí del piloto automático" → el orbe vuelve a ser barra y desaparece.

## Nuestro diferencial (y lo que NO es)

Hermes Desktop ya trae un **HUD**, una barra de chat flotante siempre arriba, y **Pets**, mascotas que flotan y reaccionan al agente. Por eso "algo flotando sobre el escritorio" **no es diferencial por sí solo**. Lo nuestro es:

| HUD / Pets de Hermes | H.E.R.M.I.S |
|---|---|
| Un chat o una mascota flotando | Un **lienzo**: el agente dibuja superficies con datos |
| Vos escribís | **Modo voz**: el agente cambia de comportamiento |
| No toca tus ventanas | **Acomoda tus ventanas reales** (dividir, maximizar, cuadrícula) |
| Estados genéricos | El orbe muestra **escuchando / hablando** con eventos de voz reales |

## Por qué es un plugin y no un prompt

- **Una capa de render propia** (Electron, transparente, siempre arriba, los clics pasan donde no hay nada dibujado), conectada a Hermes por WebSocket local.
- **Tools con código propio**: dibujar superficies y acomodar ventanas con la API de Win32.
- **Cambio de modo real**: el plugin inyecta instrucciones de modo (`register_system_prompt_section` / `pre_llm_call`) para que Hermes responda corto y por voz y muestre los datos en superficies.
- **Hooks**: `pre_llm_call` le pasa a Hermes qué hay en pantalla (desde un cache, nunca capturando en el momento); los hooks de tool animan el orbe.
- **Estado persistente**: el modo activo, las superficies y las ventanas, entre turnos.

## Lo que NO construimos (Hermes ya lo trae) — verificado en `docs/RESEARCH.md`

| Necesidad | Lo provee Hermes |
|---|---|
| Escucha siempre activa | Wake word **"hey hermes"**: único modelo incluido en Hermes (`tools/wakewords/hey_hermes.tflite`, Windows x64, sin key) |
| Voz a texto / respuesta hablada | Voice mode: faster-whisper local + Edge TTS gratis |
| Clics, teclado, leer la UI | Tool `computer_use` (cua-driver, UIAutomation) |
| Listar ventanas y apps, enfocar | `computer_use` → `list_windows`, `list_apps`, `focus_app` (lo llamamos con `ctx.dispatch_tool`) |
| Gmail | Skill bundled `google-workspace` (OAuth de Hermes) |
| Eventos de voz para el orbe | El gateway emite `voice.status`, `voice.partial`, `wake.detected` |
| Escribir dentro de una app | `computer_use` (teclado y clics) |
| Gráficos, dashboards, diagramas | Hermes ya genera **artefactos** HTML y SVG en sus respuestas (bloques ` ```html ` / ` ```svg `); Hermes Desktop los muestra en un `iframe sandbox="allow-scripts"` |

Limitación verificada: el plugin **no puede encender la voz ni la wake word globales** (`ctx.set_config` solo escribe la configuración del propio plugin). Se activan una vez, en la instalación, y el modo vive arriba de eso.

## Principio: el plugin es una INTERFAZ, no una fuente de datos

> Decisión del 8/11. Ahorramos trabajo usando lo que Hermes ya sabe hacer.

H.E.R.M.I.S le da a Hermes **dónde mostrar** y **cómo acomodar**, nunca **de dónde sacar** las cosas. Son tres piezas y nada más:

1. **Un lienzo**: superficies flotantes sobre el escritorio.
2. **Un acomodador de ventanas**: `layout_windows` y `launch_app`, lo único que `computer_use` no hace.
3. **Un modo voz**: respuestas cortas, el orbe, el morph.

Reglas que salen de esto:

- **Las instrucciones del modo enseñan nuestra interfaz, no qué herramienta usar.** Explican qué superficie conviene según el *tipo de dato* (mensajes → `email_list`, filas → `table`, ítems → `cards`, texto largo → `document`) y qué hay en pantalla. Nunca nombran Gmail, IMAP, skills ni apps: Hermes ya sabe cómo conseguir cada cosa.
- **Si Hermes ya lo hace, no lo reescribimos.** Leer correos (skill `google-workspace`), escribir en una app (`computer_use`) y generar gráficos (artefactos HTML/SVG) son de Hermes. Nosotros solo los llevamos a la pantalla.
- **Los artefactos pasan solos.** Con el modo activo, el hook `post_llm_call` (recibe la respuesta final como `assistant_response`) detecta los bloques ` ```html ` / ` ```svg ` que Hermes ya escribe y los dibuja como superficie `artifact`. No hace falta pedirle nada al modelo.
- **Gmail es contenido de la demo, no del plugin.** "Mostrame mis correos" funciona porque Hermes trae los datos con su skill y elige `email_list` porque son mensajes. Con Outlook, Slack o un CSV funciona igual.

Por eso se sacaron el plan B por IMAP (pedía contraseñas del `.env`, contra las reglas del catálogo) y `type_in_window` (duplicaba `computer_use` y le hacía correr a Hermes un comando de shell con texto del usuario).

## Arquitectura

```
"Hey Hermes…" ──▶ Hermes (wake word + STT + LLM + TTS + computer_use)
                 │
                 ├─ tools del plugin
                 │    ├─ autopilot(on|off)               ── cambia el modo + dispara el morph
                 │    ├─ render_surface(surface, data)   ─┐
                 │    ├─ close_surface(id)                │  WebSocket local
                 │    ├─ list_surfaces()                  │  (127.0.0.1 + token)
                 │    ├─ layout_windows(apps, layout)     │  Win32 propio
                 │    └─ launch_app(name)                 ▼
                 ├─ system prompt del modo + pre_llm_call (contexto de pantalla)
                 ├─ post_llm_call: artefactos html/svg de la respuesta → superficie artifact
                 └─ hooks pre/post_tool_call ──────────▶ Overlay Electron (aparte)
                                                          ├─ orbe de Lumen + morph
                                                          ├─ superficies
                 gateway WS (voice.status, wake.detected) ─┘ (estados escuchando/hablando)
```

- **Overlay**: proceso Electron aparte, lanzado con `npx electron@<versión fija>` (sin binarios en el repo). El Desktop Plugin SDK **no puede** crear ventanas fuera de la app de Hermes (verificado).
- **Shell**: se porta el de Lumen OS (~70% tal cual: orbe con 4 estados, ventanas, notificaciones, clics que pasan a través).
- **Plan de respaldo del orbe**: si el review del catálogo rechaza Electron, el orbe pasa a ser una **Pet** personalizada de Hermes (canal oficial, siempre arriba, sin morph propio).

### Protocolo: `x-lumen-desktop v2`

El agente **no escribe HTML**: manda **datos** y el overlay tiene los componentes.

```json
{ "type": "mode",   "autopilot": true }
{ "type": "render", "surface": "email_list", "id": "email_list-1", "data": { "items": [...] } }
{ "type": "render", "surface": "notification", "data": { "text": "Listo", "level": "success" } }
{ "type": "close",  "id": "email_list-1 | all" }
{ "type": "state",  "orb": "listening | thinking | acting | speaking | idle" }
```

- `render` con un `id` que ya está en pantalla **actualiza** esa superficie en lugar de crear otra. Las `notification` no llevan `id`.
- El modo se avisa **solo** con `mode`. El overlay ignora los tipos que no conoce.

Superficies: `notification`, `document`, `email_list`, `table`, `cards`, `web`, `image` y `artifact`.

- `artifact` `{kind: "html"|"svg", title?, content}` es lo mismo que Hermes ya genera en el chat. Se dibuja aislado como en Hermes Desktop: `iframe` con `sandbox="allow-scripts"` (sin `allow-same-origin`), sin red y sin acceso al overlay. Reemplaza a `custom`.

## Demo (menos de 90 segundos), borrador

1. Hermes normal en pantalla → "**Hey Hermes, modo piloto automático**" → **morph** a orbe → "¿Qué hacemos hoy?"
2. "Mostrame mis últimos 10 correos" → se dibuja la superficie
3. "Abrí el de Juan" → Hermes sabe cuál es por el contexto
4. "Poneme el Excel de notas a la izquierda y los trabajos a la derecha" → acomoda las ventanas
5. "Salí del piloto automático" → el orbe vuelve a ser barra

> Spotify queda **afuera** de la demo hasta tener un primer acercamiento.

## Decisiones

| Tema | Decisión | Estado |
|---|---|---|
| Concepto | Modo Piloto Automático: el escritorio como OS para agentes | ✅ aprobado (#5) |
| Orbe | **Opción B**: orbe propio en nuestro overlay, con morph | ✅ aprobado (#5) |
| Respaldo del orbe | Pet personalizada de Hermes | ✅ aprobado (#5) |
| HUD de Hermes | No se toca (prohibido por el catálogo); el morph es nuestro | ✅ |
| Renderer | Electron aparte, `npx` con versión fija | ✅ |
| Protocolo | `x-lumen-desktop v2` + mensaje `mode` | ✅ |
| Wake word | **"Hey Hermes"**: es el único modelo incluido en Hermes y anda sin configurar nada. "Hey Jarvis" es opcional: hay que bajar `hey_jarvis_v0.1.tflite` de openWakeWord y poner su **ruta absoluta** en `wake_word.openwakeword.model` (con `model: hey_jarvis` a secas Hermes se cae; revisar la licencia del modelo) | ✅ (#1) |
| Alcance del plugin | **Interfaz, no fuentes de datos**: lienzo + ventanas + modo voz. Nada de Gmail/IMAP en el código; artefactos de Hermes al overlay vía `post_llm_call` (ver "Principio") | ✅ (8/11) |
| Guion de la demo | Borrador de arriba | ⏳ issue abierto |
| Spotify | Fuera de la demo por ahora | ⏳ issue abierto |

## Riesgos

- **Electron en el catálogo**: `npx electron` baja un binario al instalar. Hay precedentes (`spotify-desktop`, `snyk`), pero puede generar preguntas en el review → respaldo: build en GitHub Actions con atestación, o el orbe como Pet.
- **WS del gateway para el orbe**: falta confirmar el puerto y la autenticación para conectarse como cliente y recibir `voice.status`.
- **Estado "hablando"**: no está claro si `voice.status` lo distingue; si no, se aproxima con los hooks de turno.
- **Gmail en la demo**: "últimos 10 correos" depende de la skill `google-workspace` de Hermes → hay que probarlo de punta a punta con la cuenta conectada. Si falla, se cambia el ejemplo del guion por otra fuente que Hermes ya tenga; el plugin no cambia.
- **Windows (UIPI)**: no se pueden manejar ventanas que corren como administrador → en la demo, nada elevado.
- **Catálogo** ([reglas](https://hermes-agent.nousresearch.com/docs/developer-guide/plugins/catalog-submission)):
  - El repo tiene que ser **público** antes de enviar (se hace al final).
  - Sin binarios en el repo y sin código que se actualiza solo.
  - Declarar en la `description`: procesos en segundo plano (overlay + WebSocket), red y shell.
  - Capabilities declaradas = las que el plugin registra de verdad.
  - Credenciales solo con `agent.secret_scope.get_secret()`; dependencias con piso y techo.
  - Hay un borrador de `plugin-catalog/hermis.yaml` en `docs/RESEARCH.md`.

## Entrega

- **Fecha límite:** miércoles 11/11/2026, 17:00 EST (19:00 hora de Argentina)
- PR al catálogo de plugins de Hermes (`NousResearch/hermes-agent`, archivo `plugin-catalog/hermis.yaml`)
- Video en X etiquetando a @NousResearch (menos de 90 segundos)
- Formulario: https://form.typeform.com/to/FwJLvOln
