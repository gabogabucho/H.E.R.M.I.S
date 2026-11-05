# H.E.R.M.I.S — Roadmap

**Fecha límite: miércoles 11/11/2026, 17:00 EST (19:00 hora de Argentina).**
Regla: cada día termina con algo que **se ve funcionando**. Si una fase se atrasa, se recorta alcance, no se corre la entrega.

> **Bloqueo actual:** no se escribe código hasta que el equipo apruebe la propuesta del Modo Piloto Automático (issue "Propuesta: Modo Piloto Automático").

---

## Día 0 · Jue 5/11 — Concepto, investigación y spike ⏳

- [x] Reglas del hackathon y guía de plugins leídas
- [x] Concepto: Modo Piloto Automático, el escritorio como OS para agentes
- [x] Boceto: morph, intro, superficie de correos, ventanas divididas
- [x] Brief y roadmap
- [x] Investigación técnica (`docs/RESEARCH.md`): qué trae Hermes y qué construimos
- [x] Reglas del catálogo confirmadas
- [x] Decisión del orbe: opción B (orbe propio con morph), Pet de Hermes como respaldo
- [ ] **Aprobación del equipo** de la propuesta
- [ ] Hermes instalado en Windows: `/voice on`, `/wake on` con `wake_word.openwakeword.model: hey_jarvis`, `hermes computer-use doctor` en verde
- [ ] Confirmar puerto y autenticación del WS del gateway (para `voice.status` / `wake.detected`)

**Validación:** decís "hey jarvis", Hermes te responde por voz y hace un clic con computer use.

---

## Día 1 · Vie 6/11 — Esqueleto + el primer dibujo

- [ ] `plugin.yaml` + `pyproject.toml` (dependencias con piso y techo) + `__init__.py` con `register(ctx)`
- [ ] Servidor WebSocket local (127.0.0.1 + token) levantado por el plugin
- [ ] Overlay Electron (`npx electron@<versión fija>`): transparente, pantalla completa, siempre arriba, los clics pasan donde no hay nada dibujado
- [ ] Shell de Lumen portado: orbe + contenedor de superficies + adaptador de mensajes
- [ ] Tool `render_surface` con `notification` y `document`
- [ ] `hermes plugins doctor --ci` y `hermes plugins validate . --install-deps` en verde

**Validación:** le escribís "mostrame un doc con X" → aparece flotando sobre el escritorio.

---

## Día 2 · Sáb 7/11 — Modo Piloto Automático + superficies

- [ ] Tool `autopilot(on|off)` + estado persistente del modo
- [ ] Instrucciones del modo (`register_system_prompt_section` / `pre_llm_call`): respuestas cortas por voz, datos en superficies
- [ ] **Morph**: barra → esfera al entrar, esfera → barra al salir
- [ ] Superficies `email_list`, `table`, `cards`, `web`, `image`, `custom` (aislada)
- [ ] `close_surface` + `list_surfaces`, con estado persistente (`plugin_data_dir`)
- [ ] Flujo Gmail con la skill `google-workspace`: "últimos 10 correos" → `email_list`

**Validación:** "Hey Jarvis, modo piloto automático" → morph → "mostrame mis últimos 10 correos" → se dibuja la lista.

---

## Día 3 · Dom 8/11 — Manejar el escritorio

- [ ] Listar y enfocar ventanas delegando en `computer_use` (`ctx.dispatch_tool`)
- [ ] `layout_windows` (dividir, maximizar, cuadrícula) con la API de Win32
- [ ] `launch_app` (buscar y abrir apps)
- [ ] Hook `pre_llm_call` con el contexto de pantalla desde un cache (superficies + ventanas)
- [ ] "Abrí el de Juan" resuelve la referencia gracias al contexto

**Validación:** "Excel de notas a la izquierda, trabajos a la derecha" → hecho.

---

## Día 4 · Lun 9/11 — El orbe vivo + demo completa

- [ ] Overlay como cliente del WS del gateway: `voice.status` → escuchando, `wake.detected` → intro
- [ ] Hooks `pre/post_tool_call` → actuando; turnos → pensando / hablando
- [ ] Intro inmersiva (se oscurece → orbe → "¿Qué hacemos hoy?" → se vuelve transparente)
- [ ] `/hermis` como slash command: estado, activar/desactivar el modo y un chequeo de instalación (voz, wake word, computer use)
- [ ] La demo completa corre de punta a punta al menos una vez
- [ ] *(Opcional, si sobra tiempo)* primer acercamiento a Spotify

**Validación:** el guion entero de la demo funciona sin tocar el teclado.

---

## Día 5 · Mar 10/11 — Confiabilidad y pulido

- [ ] Manejo de errores: el overlay se cae → el plugin reconecta; las tools siempre devuelven JSON
- [ ] Tests del protocolo y de las tools
- [ ] README con instalación y la disclosure completa (procesos en segundo plano, red, shell)
- [ ] Decidir: `npx electron` o build en GitHub Actions con atestación
- [ ] Grabar tomas de la demo (varias)

**Validación:** instalación limpia en otro perfil de Hermes → funciona.

---

## Día 6 · Mié 11/11 — Entrega (antes de las 19:00 hora de Argentina)

- [ ] Hacer el repo **público**
- [ ] `hermes plugins validate . --install-deps` en el commit final y SHA de 40 caracteres
- [ ] PR a `NousResearch/hermes-agent` con `plugin-catalog/hermis.yaml` (borrador en `docs/RESEARCH.md`)
- [ ] Edición final del video (menos de 90 segundos)
- [ ] Post en X etiquetando a @NousResearch
- [ ] Formulario: https://form.typeform.com/to/FwJLvOln
- [ ] Margen: todo enviado antes de las 15:00 hora de Argentina

---

## Plan de respaldo

- **Electron rechazado o frágil** → el orbe pasa a ser una Pet personalizada de Hermes y las superficies se muestran en un pane del Desktop Plugin SDK. Se pierde el morph y el dibujo sobre el escritorio, pero el modo sigue funcionando.
- **Gmail falla** → IMAP, o datos de ejemplo para la superficie.

## Fuera de alcance (para después del hackathon)

- macOS y Linux (la base de Electron y del protocolo ya es multiplataforma; falta el gestor de ventanas)
- Superficies editables (el usuario edita y Hermes recibe los cambios)
- Múltiples monitores
- Generar superficies nuevas en tiempo de ejecución
- Spotify (hasta tener el primer acercamiento)
