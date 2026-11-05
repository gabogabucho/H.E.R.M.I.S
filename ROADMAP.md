# H.E.R.M.I.S — Roadmap

**Fecha límite: miércoles 11/11/2026, 17:00 EST (19:00 hora de Argentina).**
Regla: cada día termina con algo que **se ve funcionando**. Si una fase se atrasa, se recorta alcance, no se corre la entrega.

---

## Día 0 · Jue 5/11 — Concepto y spike ⏳

- [x] Reglas del hackathon y guía de plugins leídas
- [x] Concepto definido: el escritorio como OS para agentes
- [x] Boceto: intro, superficie de correos, ventanas divididas
- [x] Brief y roadmap
- [ ] Hermes instalado en Windows: `/voice on`, `/wake on`, `hermes computer-use doctor` en verde
- [ ] Confirmar el formato de la entrada en el catálogo (la página de envío dio 404)

**Validación:** Hermes te responde por voz y hace un clic con computer use.

---

## Día 1 · Vie 6/11 — Esqueleto + el primer dibujo

- [ ] `plugin.yaml` + `__init__.py` con `register(ctx)`
- [ ] Servidor WebSocket local (127.0.0.1 + token) levantado por el plugin
- [ ] Overlay Electron: transparente, pantalla completa, siempre arriba, los clics pasan donde no hay nada dibujado
- [ ] Shell de Lumen portado: bola + contenedor de superficies
- [ ] Tool `render_surface` con `notification` y `document`
- [ ] `hermes plugins doctor --ci` y `hermes plugins validate` en verde

**Validación:** le escribís "mostrame un doc con X" → aparece flotando sobre el escritorio.

---

## Día 2 · Sáb 7/11 — Superficies + presencia

- [ ] Superficies `email_list`, `table`, `cards`, `web`, `image`, `custom` (aislada)
- [ ] `close_surface` + `list_surfaces`, con estado persistente (`plugin_data_dir`)
- [ ] Hooks → estados de la bola: `pre_llm_call` → pensando, `pre_tool_call` → actuando, al terminar → reposo
- [ ] Flujo Gmail: "últimos 10 correos" → superficie `email_list`

**Validación:** por voz, "mostrame mis últimos 10 correos" → se dibuja la lista.

---

## Día 3 · Dom 8/11 — Manejar el escritorio

- [ ] `list_windows`, `focus_window`, `layout_windows` (dividir, maximizar, cuadrícula) con la API de Win32
- [ ] `launch_app` (buscar y abrir apps)
- [ ] Hook `pre_llm_call` que inyecta el contexto de pantalla: superficies + ventanas abiertas
- [ ] "Abrí el de Juan" resuelve la referencia gracias al contexto

**Validación:** "Excel de notas a la izquierda, trabajos a la derecha" → hecho.

---

## Día 4 · Lun 9/11 — Modo OS

- [ ] `/hermis on|off`: activa la voz, la wake word, computer use y el overlay con un solo comando
- [ ] Intro inmersiva (se oscurece → bola → "¿Qué hacemos hoy?" → se vuelve transparente)
- [ ] La demo completa corre de punta a punta al menos una vez
- [ ] *(Opcional, si sobra tiempo)* primer acercamiento a Spotify; ver issue abierto

**Validación:** el guion entero de la demo funciona sin tocar el teclado.

---

## Día 5 · Mar 10/11 — Confiabilidad y pulido

- [ ] Manejo de errores: el overlay se cae → el plugin reconecta; las tools siempre devuelven JSON
- [ ] Tests del protocolo y de las tools
- [ ] Empaquetado del overlay (ejecutable ya armado o `npx`) y README con la instalación
- [ ] Grabar tomas de la demo (varias)

**Validación:** instalación limpia en otra máquina o en otro perfil de Hermes → funciona.

---

## Día 6 · Mié 11/11 — Entrega (antes de las 19:00 hora de Argentina)

- [ ] Edición final del video (menos de 90 segundos)
- [ ] PR al catálogo de plugins de Hermes
- [ ] Post en X etiquetando a @NousResearch
- [ ] Formulario: https://form.typeform.com/to/FwJLvOln
- [ ] Margen: todo enviado antes de las 15:00 hora de Argentina

---

## Fuera de alcance (para después del hackathon)

- macOS y Linux (la base de Electron y del protocolo ya es multiplataforma; falta el gestor de ventanas)
- Superficies editables (el usuario edita y Hermes recibe los cambios)
- Múltiples monitores
- Generar superficies nuevas en tiempo de ejecución
