"""Tests del plugin H.E.R.M.I.S (Día 1–2) + cliente WS en vivo (`--listen` / `--demo`).

- Tests:  python -m unittest discover -s tests -v
- Listen: python tests/test_skeleton.py --listen
- Demo:   python tests/test_skeleton.py --demo
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosedError

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "hermis", ROOT / "__init__.py", submodule_search_locations=[str(ROOT)]
)
hermis = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
sys.modules["hermis"] = hermis
_spec.loader.exec_module(hermis)  # type: ignore[union-attr]
schemas, tools, ws_server = hermis.schemas, hermis.tools, hermis.ws_server
overlay_launcher = hermis.overlay_launcher
win32_windows = hermis.win32_windows


class SkeletonTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        os.environ["HERMIS_OVERLAY_AUTOSTART"] = "0"
        with ws_server._lock:
            ws_server._STATE["data_dir_override"] = self.tmp
            ws_server._STATE["thread"] = None
            ws_server._STATE["loop"] = None
            ws_server._STATE["port"] = None
            ws_server._STATE["token"] = None
            ws_server._clients.clear()
        ws_server._ready.clear()
        # Estos tests prueban el modo ya configurado; el onboarding tiene los suyos.
        ws_server.save_state({"autopilot": False, "seq": 0, "surfaces": {}, "onboarded": True})
        # Nunca leer las ventanas reales del escritorio de quien corre los tests.
        windows = patch.object(win32_windows, "list_open_windows", return_value=[])
        windows.start()
        self.addCleanup(windows.stop)

    def test_first_autopilot_shows_setup_once(self) -> None:
        ws_server.save_state({"autopilot": False, "seq": 0, "surfaces": {}})
        sent: list[dict] = []
        fake = {"title": "Configuración de H.E.R.M.I.S", "subtitle": "Todo listo.",
                "items": [{"id": "overlay", "label": "Overlay", "status": "ok", "detail": "Listo."}]}
        with patch.object(tools, "_safe_broadcast", side_effect=lambda m: (sent.append(m), (1, None))[1]), \
             patch.object(hermis.setup_checks, "surface_data", return_value=fake):
            tools.autopilot({"state": "on"})
            first = [m for m in sent if m.get("surface") == "setup"]
            self.assertEqual(first, [{"type": "render", "surface": "setup", "id": "hermis-setup", "data": fake}])
            # Persistido: si el overlay arranca después, la sincronización al conectar lo dibuja.
            self.assertIn("hermis-setup", ws_server.load_state()["surfaces"])
            self.assertTrue(ws_server.load_state()["onboarded"])
            sent.clear()
            tools.autopilot({"state": "off"})
            tools.autopilot({"state": "on"})
            self.assertFalse([m for m in sent if m.get("surface") == "setup"])
            # /hermis setup lo vuelve a abrir cuando el usuario quiera.
            tools.show_setup()
            self.assertEqual(sent[-1]["surface"], "setup")

    def test_setup_refresh_message_redraws_checklist(self) -> None:
        with patch.object(tools, "show_setup") as show:
            ws_server._handle_client_message(json.dumps({"type": "setup.refresh"}))
            for _ in range(50):
                if show.called:
                    break
                time.sleep(0.02)
            show.assert_called_once()

    def test_schema_and_validation(self) -> None:
        self.assertEqual(schemas.AUTOPILOT_SCHEMA["name"], "autopilot")
        self.assertEqual(schemas.RENDER_SURFACE_SCHEMA["name"], "render_surface")
        self.assertEqual(schemas.CLOSE_SURFACE_SCHEMA["name"], "close_surface")
        self.assertEqual(schemas.LIST_SURFACES_SCHEMA["name"], "list_surfaces")
        self.assertEqual(schemas.LAYOUT_WINDOWS_SCHEMA["name"], "layout_windows")
        self.assertEqual(schemas.LAUNCH_APP_SCHEMA["name"], "launch_app")

        bad_cases = [
            None,
            {},
            {"surface": "unknown", "data": {}},
            {"surface": "notification", "data": "not-a-dict"},
            {"surface": "notification", "data": {}},
            {"surface": "notification", "data": {"text": "   "}},
            {"surface": "notification", "data": {"text": "hola", "level": "warn"}},
            {"surface": "document", "data": {}},
            {"surface": "document", "data": {"title": 123}},
            {"surface": "document", "data": {"title": "ok"}, "id": "   "},
            {"surface": "email_list", "data": {}},
            {"surface": "email_list", "data": {"items": [{}]}},
            {"surface": "table", "data": {"columns": [], "rows": []}},
            {"surface": "table", "data": {"columns": ["A"], "rows": ["bad"]}},
            {"surface": "cards", "data": {"items": []}},
            {"surface": "web", "data": {"url": "ftp://bad"}},
            {"surface": "image", "data": {}},
            {"surface": "artifact", "data": {"content": "<p>Hola</p>"}},
            {"surface": "artifact", "data": {"kind": "js", "content": "<p>Hola</p>"}},
            {"surface": "artifact", "data": {"kind": "html", "content": "   "}},
        ]
        for payload in bad_cases:
            res = json.loads(tools.render_surface(payload))  # type: ignore[arg-type]
            self.assertFalse(res["ok"], f"esperaba ok=False para {payload!r}")

        self.assertFalse(json.loads(tools.autopilot(None))["ok"])  # type: ignore[arg-type]
        self.assertFalse(json.loads(tools.autopilot({"state": "maybe"}))["ok"])
        self.assertFalse(json.loads(tools.close_surface(None))["ok"])  # type: ignore[arg-type]
        self.assertFalse(json.loads(tools.close_surface({"id": "  "}))["ok"])

    def test_tools_return_json_on_unexpected_errors(self) -> None:
        # Windows suele bloquear el reemplazo atómico de state.json (antivirus, indexador).
        locked = PermissionError(13, "Access is denied")
        calls = [
            lambda: tools.autopilot({"state": "on"}),
            lambda: tools.render_surface({"surface": "document", "data": {"title": "x"}}),
            lambda: tools.close_surface({"id": "all"}),
            lambda: tools.layout_windows({"layout": "maximize", "windows": ["Excel"]}),
            lambda: tools.launch_app({"app": "notepad"}),
        ]
        with patch.object(ws_server, "save_state", side_effect=locked), \
             patch.object(tools, "_safe_broadcast", return_value=(0, None)), \
             patch.object(win32_windows, "apply_layout", return_value={"ok": True}), \
             patch.object(win32_windows, "launch_application", return_value={"ok": True}):
            for call in calls:
                out = json.loads(call())
                self.assertEqual(out["error"], "internal_error")
                self.assertFalse(out["ok"])
                self.assertIn("PermissionError", out["message"])
        with patch.object(ws_server, "load_state", side_effect=OSError("disk gone")):
            out = json.loads(tools.list_surfaces({}))
            self.assertEqual(out["error"], "internal_error")
        self.assertEqual(tools.autopilot.__name__, "autopilot")

    def test_autopilot_off_clears_the_overlay(self) -> None:
        sent: list[dict] = []
        with patch.object(tools, "_safe_broadcast", side_effect=lambda m: (sent.append(m), (1, None))[1]):
            tools.autopilot({"state": "on"})
            tools.render_surface({"surface": "document", "id": "doc", "data": {"title": "x"}})
            sent.clear()
            tools.autopilot({"state": "off"})
        self.assertEqual(sent, [{"type": "close", "id": "all"}, {"type": "mode", "autopilot": False}])
        self.assertEqual(ws_server.load_state().get("surfaces"), {})

    def test_day2_autopilot_surfaces_and_pre_llm_call(self) -> None:
        # Sin estado inicial, pre_llm_call no inyecta nada
        self.assertIsNone(tools.pre_llm_call())

        # Activar autopilot
        ap_on = json.loads(tools.autopilot({"state": "on"}))
        self.assertTrue(ap_on["ok"])
        self.assertTrue(ap_on["autopilot"])

        # Renderizar las superficies nuevas de Día 2
        emails = json.loads(tools.render_surface({
            "surface": "email_list",
            "id": "inbox",
            "data": {
                "title": "Últimos correos",
                "items": [
                    {"from": "Juan Pérez <juan@acme.com>", "subject": "Entrega TP", "body_markdown": "Hola, adjunto el TP final."},
                    {"from": "Ana Gómez <ana@acme.com>", "subject": "Reunión", "snippet": "Nos vemos a las 15hs"},
                ],
            },
        }))
        self.assertTrue(emails["ok"])
        self.assertEqual(emails["id"], "inbox")

        for surf, data in [
            ("table", {"title": "Notas", "columns": ["Alumno", "Nota"], "rows": [["Juan", "10"]]}),
            ("cards", {"title": "Tareas", "items": [{"title": "Día 2", "badge": "En curso"}]}),
            ("web", {"title": "Docs", "url": "https://hermes-agent.nousresearch.com"}),
            ("image", {"title": "Diagrama", "src": "https://example.com/arch.png", "alt": "Arq"}),
            ("artifact", {"title": "Gráfico", "kind": "html", "content": "<p>Hola</p>"}),
        ]:
            out = json.loads(tools.render_surface({"surface": surf, "data": data}))
            self.assertTrue(out["ok"], f"falló {surf}: {out}")
            self.assertTrue(out["id"].startswith(f"{surf}-"))

        listed = json.loads(tools.list_surfaces())
        self.assertTrue(listed["autopilot"])
        self.assertEqual(len(listed["surfaces"]), 6)

        # Verificar contexto inyectado por pre_llm_call ("Abrí el de Juan")
        hook_res = tools.pre_llm_call(turn_id="t1")
        self.assertIsInstance(hook_res, dict)
        ctx_text = hook_res["context"]  # type: ignore[index]
        self.assertIn("Modo Piloto Automático ACTIVO", ctx_text)
        self.assertIn("render_surface", ctx_text)
        self.assertIn("email_list", ctx_text)
        self.assertIn("artifact", ctx_text)
        self.assertIn("Juan Pérez", ctx_text)
        self.assertIn("Hola, adjunto el TP final.", ctx_text)
        # El modo enseña la interfaz, nunca fuentes de datos ni skills
        for forbidden in ("google-workspace", "Gmail", "IMAP", "EMAIL_ADDRESS", "EMAIL_PASSWORD", ".env", "type_in_window"):
            self.assertNotIn(forbidden, ctx_text)

        # Cerrar una superficie puntual y luego todas
        closed_one = json.loads(tools.close_surface({"id": "inbox"}))
        self.assertEqual(closed_one["closed"], ["inbox"])
        self.assertEqual(len(json.loads(tools.list_surfaces())["surfaces"]), 5)

        closed_all = json.loads(tools.close_surface({"id": "all"}))
        self.assertEqual(len(closed_all["closed"]), 5)
        self.assertEqual(json.loads(tools.list_surfaces())["surfaces"], [])

        # Apagar autopilot limpia todo y pre_llm_call vuelve a None
        ap_off = json.loads(tools.autopilot({"state": "off"}))
        self.assertFalse(ap_off["autopilot"])
        self.assertIsNone(tools.pre_llm_call())

    def test_broadcast_takes_over_dead_owner(self) -> None:
        # overlay.json apunta al puerto de un dueño caído: broadcast toma el relevo
        dead = socket.socket()
        dead.bind(("127.0.0.1", 0))
        dead_port = dead.getsockname()[1]
        dead.close()
        (Path(self.tmp) / "overlay.json").write_text(json.dumps(
            {"host": "127.0.0.1", "port": dead_port, "token": "x", "pid": os.getpid() + 4321},
        ), encoding="utf-8")

        delivered = ws_server.broadcast({"type": "render", "surface": "notification",
                                         "data": {"text": "nada", "level": "info"}})
        self.assertEqual(delivered, 0)
        info = json.loads((Path(self.tmp) / "overlay.json").read_text(encoding="utf-8"))
        self.assertEqual(info["pid"], os.getpid())
        self.assertNotEqual(info["port"], dead_port)

        async def scenario() -> None:
            async with connect(f"ws://{info['host']}:{info['port']}") as client:
                await client.send(json.dumps({"type": "hello", "token": info["token"]}))
                self.assertEqual(json.loads(await client.recv()), {"type": "hello_ok"})
                self.assertEqual(json.loads(await asyncio.wait_for(client.recv(), timeout=2.0)),
                                 {"type": "mode", "autopilot": False})
                self.assertEqual(ws_server.broadcast({"type": "render", "surface": "notification",
                                                      "data": {"text": "llegó", "level": "info"}}), 1)
                msg = json.loads(await asyncio.wait_for(client.recv(), timeout=2.0))
                self.assertEqual(msg["data"]["text"], "llegó")

        asyncio.run(scenario())

        # Luego de tomar el relevo, los reintentos no relanzan ni reescriben nada
        info2 = json.loads((Path(self.tmp) / "overlay.json").read_text(encoding="utf-8"))
        self.assertEqual(info2, info)

    def test_broadcast_no_takeover_on_invalid_token(self) -> None:
        # Servidor ajeno vivo que rechaza el token: no tomamos el relevo
        foreign_pid = os.getpid() + 4321
        results: dict[str, object] = {}

        async def scenario() -> None:
            from websockets.asyncio.server import serve

            async def reject(conn: object) -> None:
                hello = json.loads(await asyncio.wait_for(conn.recv(), timeout=2.0))
                if not isinstance(hello, dict) or hello.get("token") != "real":
                    await conn.close(code=4401, reason="token inválido")
                    return
                await conn.send(json.dumps({"type": "hello_ok"}))
                async for _ in conn:
                    pass

            async with serve(reject, "127.0.0.1", 0) as server:
                port = server.sockets[0].getsockname()[1]
                (Path(self.tmp) / "overlay.json").write_text(json.dumps(
                    {"host": "127.0.0.1", "port": port, "token": "wrong", "pid": foreign_pid},
                ), encoding="utf-8")
                loop = asyncio.get_running_loop()
                results["delivered"] = await loop.run_in_executor(
                    None, lambda: ws_server.broadcast({"type": "render", "surface": "notification",
                                                       "data": {"text": "x", "level": "info"}}))
                results["port"] = port

        asyncio.run(scenario())
        self.assertEqual(results["delivered"], 0)
        info = json.loads((Path(self.tmp) / "overlay.json").read_text(encoding="utf-8"))
        self.assertEqual(info["pid"], foreign_pid)
        self.assertEqual(info["port"], results["port"])
        with ws_server._lock:
            self.assertIsNone(ws_server._STATE["thread"])

    def test_broadcast_rewrites_overlay_json_when_we_have_server(self) -> None:
        # Nuestro servidor vive pero overlay.json fue tapado por un dueño muerto: re-publicamos
        ctx = MagicMock(plugin_data_dir=self.tmp)
        hermis.register(ctx)
        ours = json.loads((Path(self.tmp) / "overlay.json").read_text(encoding="utf-8"))
        dead = socket.socket()
        dead.bind(("127.0.0.1", 0))
        dead_port = dead.getsockname()[1]
        dead.close()
        (Path(self.tmp) / "overlay.json").write_text(json.dumps(
            {"host": "127.0.0.1", "port": dead_port, "token": "x", "pid": os.getpid() + 4321},
        ), encoding="utf-8")

        delivered = ws_server.broadcast({"type": "render", "surface": "notification",
                                         "data": {"text": "x", "level": "info"}})
        self.assertEqual(delivered, 0)
        info = json.loads((Path(self.tmp) / "overlay.json").read_text(encoding="utf-8"))
        self.assertEqual(info["pid"], os.getpid())
        self.assertEqual(info["port"], ours["port"])
        self.assertEqual(info["token"], ours["token"])

        async def scenario() -> None:
            async with connect(f"ws://{info['host']}:{info['port']}") as client:
                await client.send(json.dumps({"type": "hello", "token": info["token"]}))
                self.assertEqual(json.loads(await client.recv()), {"type": "hello_ok"})
                self.assertEqual(json.loads(await asyncio.wait_for(client.recv(), timeout=2.0)),
                                 {"type": "mode", "autopilot": False})

        asyncio.run(scenario())

    def test_sync_on_connect(self) -> None:
        # Estado previo sin overlay conectado: autopilot on + superficies persistidas
        ap_on = json.loads(tools.autopilot({"state": "on"}))
        self.assertTrue(ap_on["ok"])
        emails = json.loads(tools.render_surface({
            "surface": "email_list",
            "id": "inbox",
            "data": {"title": "Últimos correos", "items": [{"from": "Juan <j@x.com>", "subject": "Hola"}]},
        }))
        self.assertTrue(emails["ok"])
        table = json.loads(tools.render_surface({
            "surface": "table",
            "data": {"columns": ["Alumno"], "rows": [["Juan"]]},
        }))
        self.assertTrue(table["ok"])

        ctx = MagicMock(plugin_data_dir=self.tmp)
        hermis.register(ctx)
        info = json.loads((Path(self.tmp) / "overlay.json").read_text(encoding="utf-8"))
        uri = f"ws://{info['host']}:{info['port']}"

        async def scenario() -> None:
            async with connect(uri) as client:
                await client.send(json.dumps({"type": "hello", "token": info["token"]}))
                self.assertEqual(json.loads(await client.recv()), {"type": "hello_ok"})
                mode = json.loads(await asyncio.wait_for(client.recv(), timeout=2.0))
                self.assertEqual(mode, {"type": "mode", "autopilot": True})
                rend1 = json.loads(await asyncio.wait_for(client.recv(), timeout=2.0))
                self.assertEqual(rend1, {
                    "type": "render",
                    "surface": "email_list",
                    "id": "inbox",
                    "data": {"title": "Últimos correos", "items": [{"from": "Juan <j@x.com>", "subject": "Hola"}]},
                })
                rend2 = json.loads(await asyncio.wait_for(client.recv(), timeout=2.0))
                self.assertEqual(rend2["type"], "render")
                self.assertEqual(rend2["id"], table["id"])
                self.assertEqual(rend2["surface"], "table")

                # Un publisher recibe hello_ok y recién su ack: sin sincronización
                async with connect(uri) as pub:
                    await pub.send(json.dumps({"type": "hello", "token": info["token"], "role": "publisher"}))
                    self.assertEqual(json.loads(await pub.recv()), {"type": "hello_ok"})
                    await pub.send(json.dumps({
                        "type": "broadcast",
                        "payload": {"type": "render", "surface": "notification",
                                    "data": {"text": "sin sync", "level": "info"}},
                    }))
                    ack = json.loads(await asyncio.wait_for(pub.recv(), timeout=2.0))
                    self.assertEqual(ack, {"delivered": 1})

        asyncio.run(scenario())

    def test_ws_handshake_and_broadcast(self) -> None:
        ctx = MagicMock(plugin_data_dir=self.tmp)
        hermis.register(ctx)
        self.assertEqual(ctx.register_tool.call_count, 6)
        ctx.register_hook.assert_any_call("pre_llm_call", tools.pre_llm_call)
        self.assertEqual(ctx.register_hook.call_count, 5)

        info = json.loads((Path(self.tmp) / "overlay.json").read_text(encoding="utf-8"))
        self.assertEqual(info["host"], "127.0.0.1")
        uri = f"ws://{info['host']}:{info['port']}"

        async def scenario() -> None:
            async with connect(uri) as bad_client:
                await bad_client.send(json.dumps({"type": "hello", "token": "invalid"}))
                with self.assertRaises(ConnectionClosedError) as cm:
                    await bad_client.recv()
                self.assertEqual(cm.exception.rcvd.code, 4401)

            async with connect(uri) as client:
                await client.send(json.dumps({"type": "hello", "token": info["token"]}))
                ack = json.loads(await client.recv())
                self.assertEqual(ack, {"type": "hello_ok"})
                # Sincronización al conectar: modo actual de state.json
                sync_mode = json.loads(await asyncio.wait_for(client.recv(), timeout=2.0))
                self.assertEqual(sync_mode, {"type": "mode", "autopilot": False})

                ap_on = json.loads(tools.autopilot({"state": "on"}))
                self.assertTrue(ap_on["ok"])
                self.assertEqual(ap_on["delivered"], 1)
                mode_on = json.loads(await asyncio.wait_for(client.recv(), timeout=2.0))
                self.assertEqual(mode_on, {"type": "mode", "autopilot": True})

                out = json.loads(tools.render_surface({
                    "surface": "document",
                    "data": {"title": "Día 1", "body_markdown": "# Hola H.E.R.M.I.S"},
                }))
                self.assertTrue(out["ok"])
                self.assertEqual(out["id"], "document-1")
                self.assertEqual(out["delivered"], 1)
                self.assertTrue(out["overlay_connected"])

                msg = json.loads(await asyncio.wait_for(client.recv(), timeout=2.0))
                self.assertEqual(msg, {
                    "type": "render",
                    "id": "document-1",
                    "surface": "document",
                    "data": {"title": "Día 1", "body_markdown": "# Hola H.E.R.M.I.S"},
                })

                # Simula 2do proceso (gateway) publicando vía relay hacia overlay.json
                with ws_server._lock:
                    real_port = ws_server._STATE["port"]
                    ws_server._STATE["port"] = -1
                try:
                    relayed = ws_server._relay_to_overlay_server({
                        "type": "render",
                        "surface": "notification",
                        "data": {"text": "desde gateway", "level": "info"},
                    })
                finally:
                    with ws_server._lock:
                        ws_server._STATE["port"] = real_port
                self.assertEqual(relayed, 1)
                msg2 = json.loads(await asyncio.wait_for(client.recv(), timeout=2.0))
                self.assertEqual(msg2["data"]["text"], "desde gateway")

                # Simula hot-reload (_evict_modules) de Hermes: preserva _STATE, loop, port y clientes conectados
                spec_ws = importlib.util.spec_from_file_location("hermis.ws_server", ROOT / "ws_server.py")
                reloaded_ws = importlib.util.module_from_spec(spec_ws)  # type: ignore[arg-type]
                sys.modules["hermis.ws_server"] = reloaded_ws
                spec_ws.loader.exec_module(reloaded_ws)  # type: ignore[union-attr]
                reloaded_ws.start(data_dir=self.tmp)
                self.assertEqual(reloaded_ws._STATE["port"], info["port"])
                self.assertEqual(len(reloaded_ws._STATE["clients"]), 1)
                self.assertEqual(reloaded_ws.broadcast({"type": "render", "surface": "notification", "data": {"text": "post-reload"}}), 1)
                msg3 = json.loads(await asyncio.wait_for(client.recv(), timeout=2.0))
                self.assertEqual(msg3["data"]["text"], "post-reload")

                ap_off = json.loads(tools.autopilot({"state": "off"}))
                self.assertTrue(ap_off["ok"])
                self.assertEqual(ap_off["delivered"], 1)
                close_all = json.loads(await asyncio.wait_for(client.recv(), timeout=2.0))
                self.assertEqual(close_all, {"type": "close", "id": "all"})
                mode_off = json.loads(await asyncio.wait_for(client.recv(), timeout=2.0))
                self.assertEqual(mode_off, {"type": "mode", "autopilot": False})

        asyncio.run(scenario())


class AutostartTest(unittest.TestCase):
    """Autostart del overlay: mocks de Popen/which, nunca Electron real."""

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.fake_overlay = Path(self.tmp) / "overlay"
        (self.fake_overlay / "node_modules").mkdir(parents=True)
        with ws_server._lock:
            ws_server._STATE["data_dir_override"] = self.tmp
            ws_server._STATE["thread"] = None
            ws_server._STATE["loop"] = None
            ws_server._STATE["port"] = None
            ws_server._STATE["token"] = None
            ws_server._clients.clear()
        os.environ["HERMIS_OVERLAY_AUTOSTART"] = "1"
        overlay_launcher._last_launch = None
        overlay_launcher._pipeline_busy = False
        self.pipeline_calls: list[tuple] = []
        self.patches = [
            patch.object(overlay_launcher.shutil, "which", lambda cmd: f"C:\\fake\\{cmd}.exe"),
            patch.object(overlay_launcher, "_overlay_dir", self.fake_overlay),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self) -> None:
        for p in self.patches:
            p.stop()
        os.environ["HERMIS_OVERLAY_AUTOSTART"] = "0"
        overlay_launcher._last_launch = None
        overlay_launcher._pipeline_busy = False

    def _record_pipeline(self, npm: str, overlay_path: Path, data_dir: Path, installing: bool) -> None:
        self.pipeline_calls.append((npm, overlay_path, data_dir, installing))
        overlay_launcher._pipeline_busy = False

    def _wait_pipeline_calls(self, count: int) -> bool:
        for _ in range(250):
            if len(self.pipeline_calls) >= count:
                return True
            time.sleep(0.02)
        return len(self.pipeline_calls) >= count

    def test_disabled_by_env(self) -> None:
        os.environ["HERMIS_OVERLAY_AUTOSTART"] = "0"
        self.assertIsNone(overlay_launcher.ensure_overlay_running())
        self.assertFalse((Path(self.tmp) / "overlay.launch").exists())

    def test_missing_node_returns_clear_note(self) -> None:
        with patch.object(overlay_launcher.shutil, "which", lambda cmd: None):
            note = overlay_launcher.ensure_overlay_running()
        self.assertEqual(note, "instalá Node.js 20+ para ver el overlay")
        self.assertFalse((Path(self.tmp) / "overlay.launch").exists())

    def test_first_launch_installs_dependencies(self) -> None:
        (self.fake_overlay / "node_modules").rmdir()
        with patch.object(overlay_launcher, "_launch_pipeline", self._record_pipeline):
            note = overlay_launcher.ensure_overlay_running()
            self.assertEqual(note, "abriendo el overlay; la primera vez instala dependencias (~1 min)")
            self.assertTrue(self._wait_pipeline_calls(1))
        npm, overlay_path, data_dir, installing = self.pipeline_calls[0]
        self.assertEqual(npm, "C:\\fake\\npm.exe")
        self.assertEqual(overlay_path, self.fake_overlay)
        self.assertEqual(data_dir, Path(self.tmp))
        self.assertTrue(installing)
        marker = json.loads((Path(self.tmp) / "overlay.launch").read_text(encoding="utf-8"))
        self.assertAlmostEqual(marker["launched_at"], time.time(), delta=30)
        self.assertEqual(marker["pid"], os.getpid())

    def test_launch_with_modules_installed(self) -> None:
        with patch.object(overlay_launcher, "_launch_pipeline", self._record_pipeline):
            note = overlay_launcher.ensure_overlay_running()
            self.assertEqual(note, "abriendo el overlay…")
            self.assertTrue(self._wait_pipeline_calls(1))
        self.assertFalse(self.pipeline_calls[0][3])

    def test_relaunch_throttle(self) -> None:
        with patch.object(overlay_launcher, "_launch_pipeline", self._record_pipeline):
            self.assertEqual(overlay_launcher.ensure_overlay_running(), "abriendo el overlay…")
            self.assertTrue(self._wait_pipeline_calls(1))
            # dentro de la ventana de 90 s: por memoria y aunque se reinicie la memoria
            self.assertIsNone(overlay_launcher.ensure_overlay_running())
            overlay_launcher._last_launch = None
            self.assertIsNone(overlay_launcher.ensure_overlay_running())
            self.assertEqual(len(self.pipeline_calls), 1)
            # vencido el cooldown del archivo, vuelve a lanzar
            marker = json.loads((Path(self.tmp) / "overlay.launch").read_text(encoding="utf-8"))
            marker["launched_at"] -= overlay_launcher._RELAUNCH_COOLDOWN_S + 5
            (Path(self.tmp) / "overlay.launch").write_text(json.dumps(marker), encoding="utf-8")
            self.assertEqual(overlay_launcher.ensure_overlay_running(), "abriendo el overlay…")
            self.assertTrue(self._wait_pipeline_calls(2))

    def test_pipeline_installs_then_starts_detached(self) -> None:
        run_calls: list = []
        popen_calls: list = []
        with patch.object(overlay_launcher.subprocess, "run", lambda *a, **k: (
                 run_calls.append((a, k)) or subprocess.CompletedProcess(a[0], 0))), \
             patch.object(overlay_launcher.subprocess, "Popen", lambda *a, **k: popen_calls.append((a, k))):
            overlay_launcher._launch_pipeline("NPM.EXE", self.fake_overlay, Path(self.tmp), True)
            self.assertEqual(run_calls[0][0][0], ["NPM.EXE", "ci"])
            self.assertEqual(popen_calls[0][0][0],
                             ["NPM.EXE", "start", "--", "--data-dir", str(Path(self.tmp))])
            kwargs = popen_calls[0][1]
            self.assertEqual(kwargs["stdin"], subprocess.DEVNULL)
            self.assertEqual(kwargs["cwd"], str(self.fake_overlay))
            self.assertEqual(kwargs["stderr"], subprocess.STDOUT)
            self.assertIsNotNone(kwargs["stdout"])
            if sys.platform == "win32":
                self.assertEqual(kwargs["creationflags"], subprocess.DETACHED_PROCESS
                                 | subprocess.CREATE_NEW_PROCESS_GROUP
                                 | subprocess.CREATE_NO_WINDOW)
            else:
                self.assertTrue(kwargs["start_new_session"])
            self.assertTrue((Path(self.tmp) / "overlay.log").exists())
            # con node_modules presente no vuelve a instalar
            run_calls.clear()
            popen_calls.clear()
            overlay_launcher._launch_pipeline("NPM.EXE", self.fake_overlay, Path(self.tmp), False)
        self.assertEqual(run_calls, [])
        self.assertEqual(len(popen_calls), 1)

    def test_pipeline_stops_when_install_fails(self) -> None:
        popen_calls: list = []
        with patch.object(overlay_launcher.subprocess, "run",
                          lambda *a, **k: subprocess.CompletedProcess(a[0], 7)), \
             patch.object(overlay_launcher.subprocess, "Popen",
                          lambda *a, **k: popen_calls.append((a, k))):
            overlay_launcher._pipeline_busy = True
            overlay_launcher._launch_pipeline("NPM.EXE", self.fake_overlay, Path(self.tmp), True)

        self.assertEqual(popen_calls, [])
        self.assertIn(b"npm ci failed with exit code 7",
                      (Path(self.tmp) / "overlay.log").read_bytes())
        self.assertFalse(overlay_launcher._pipeline_busy)

    def test_tools_trigger_overlay_launch(self) -> None:
        # autopilot(on) lanza el overlay y lo avisa en la note
        with patch.object(overlay_launcher, "_launch_pipeline", self._record_pipeline):
            res = json.loads(tools.autopilot({"state": "on"}))
            self.assertEqual(res["note"], "abriendo el overlay…")
            self.assertTrue(self._wait_pipeline_calls(1))
            # encima del throttle, un render sin overlay mantiene la note genérica
            res = json.loads(tools.render_surface({"surface": "notification",
                                                   "data": {"text": "hola", "level": "info"}}))
            self.assertEqual(res["note"], "overlay no conectado: la superficie no se dibujó")
        # con node ausente, la note clara reemplaza a la genérica
        with patch.object(overlay_launcher.shutil, "which", lambda cmd: None):
            res = json.loads(tools.close_surface({"id": "x"}))
        self.assertEqual(res["note"], "instalá Node.js 20+ para ver el overlay")

    def test_register_never_launches_overlay(self) -> None:
        ctx = MagicMock(plugin_data_dir=self.tmp)
        hermis.register(ctx)
        self.assertEqual(ctx.register_tool.call_count, 6)
        self.assertTrue((Path(self.tmp) / "overlay.json").exists())
        self.assertFalse((Path(self.tmp) / "overlay.launch").exists())

    def test_day3_layout_windows_and_launch_app(self) -> None:
        os.environ["HERMIS_OVERLAY_AUTOSTART"] = "0"
        # Validaciones de entrada de layout_windows y launch_app
        self.assertFalse(json.loads(tools.layout_windows(None))["ok"])  # type: ignore[arg-type]
        self.assertFalse(json.loads(tools.layout_windows({"layout": "bad", "windows": ["A"]}))["ok"])
        self.assertFalse(json.loads(tools.layout_windows({"layout": "split", "windows": []}))["ok"])
        self.assertFalse(json.loads(tools.launch_app(None))["ok"])  # type: ignore[arg-type]
        self.assertFalse(json.loads(tools.launch_app({"app": "   "}))["ok"])
        self.assertFalse(json.loads(tools.launch_app({"app": "notepad; rm -rf /"}))["ok"])

        fake_wins = [
            {"hwnd": 101, "title": "Notas.xlsx - Excel", "x": 0, "y": 0, "width": 800, "height": 600},
            {"hwnd": 102, "title": "Trabajos - Google Chrome", "x": 100, "y": 100, "width": 800, "height": 600},
            {"hwnd": 103, "title": "Visual Studio Code", "x": 200, "y": 200, "width": 800, "height": 600},
        ]
        moved: list[tuple] = []
        with patch.object(win32_windows, "is_windows", lambda: True), \
             patch.object(win32_windows, "list_open_windows", lambda: fake_wins), \
             patch.object(win32_windows, "get_work_area", lambda: (0, 0, 1920, 1000)), \
             patch.object(win32_windows, "_move_window", lambda *a: moved.append(a) or True), \
             patch.object(win32_windows, "_maximize_window", lambda hwnd: True), \
             patch.object(win32_windows, "_focus_window", lambda hwnd: True), \
             patch.object(win32_windows, "_minimize_window", lambda hwnd: True):
            res_split = json.loads(tools.layout_windows({"layout": "split", "windows": ["Excel", "Chrome"]}))
            self.assertTrue(res_split["ok"])
            self.assertEqual(len(res_split["matched"]), 2)
            self.assertEqual(res_split["matched"][0]["x"], 0)
            self.assertEqual(res_split["matched"][0]["width"], 960)
            self.assertEqual(res_split["matched"][1]["x"], 960)
            self.assertEqual(res_split["matched"][1]["width"], 960)

            res_grid = json.loads(tools.layout_windows({"layout": "grid", "windows": ["Excel", "Chrome", "Code"]}))
            self.assertTrue(res_grid["ok"])
            self.assertEqual(len(res_grid["matched"]), 3)

            res_min = json.loads(tools.layout_windows({"layout": "minimize_others", "windows": ["Excel"]}))
            self.assertTrue(res_min["ok"])
            self.assertEqual(res_min["matched"][0]["minimized_others"], 2)

            # Verificar que las ventanas abiertas quedaron en caché para pre_llm_call
            tools.autopilot({"state": "on"})
            ctx = tools.pre_llm_call()
            self.assertIsNotNone(ctx)
            self.assertIn("Notas.xlsx - Excel", ctx["context"])  # type: ignore[index]

        # Verificar launch_app sin shell=True
        popen_calls: list = []
        fake_proc = MagicMock(pid=4242)
        with patch.object(win32_windows, "is_windows", lambda: True), \
             patch.object(win32_windows, "_window_snapshot", lambda: {}), \
             patch.object(win32_windows, "_bring_launched_window_to_front",
                          lambda before, app: {"focused": True, "window": "Sin título: Bloc de notas"}), \
             patch.object(win32_windows.shutil, "which", lambda exe: f"C:\\Windows\\System32\\{exe}"), \
             patch.object(win32_windows.subprocess, "Popen", lambda *a, **k: popen_calls.append((a, k)) or fake_proc):
            # Windows-only subprocess flags must also be mocked on Linux.
            with patch.object(subprocess, "DETACHED_PROCESS", 0x8, create=True), \
                 patch.object(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x200, create=True), \
                 patch.object(subprocess, "CREATE_NO_WINDOW", 0x08000000, create=True):
                launched = json.loads(tools.launch_app({"app": "bloc de notas", "args": ["notas.txt"]}))
            self.assertTrue(launched["ok"])
            self.assertEqual(launched["pid"], 4242)
            self.assertEqual(popen_calls[0][0][0], ["C:\\Windows\\System32\\notepad.exe", "notas.txt"])
            self.assertNotIn("shell", popen_calls[0][1])
            self.assertTrue(launched["focused"])
            self.assertEqual(launched["window"], "Sin título: Bloc de notas")

    def test_launched_app_window_is_brought_to_front(self) -> None:
        # El gateway corre en segundo plano: sin esto las apps abren detrás o minimizadas.
        before = {1: "Explorador", 2: "Nueva pestaña - Google Chrome"}
        cases = [
            # Ventana nueva (Calculadora vive en ApplicationFrameHost, no en el PID lanzado).
            ([{**before, 3: "Calculadora"}], "calculadora", {"focused": True, "window": "Calculadora"}, [3]),
            # Chrome reusa su proceso: no hay ventana nueva, cambia el título de la existente.
            ([{1: "Explorador", 2: "Google - Google Chrome"}] * 3, "chrome",
             {"focused": True, "window": "Google - Google Chrome"}, [2]),
            # No apareció nada reconocible.
            ([before] * 3, "spotify", {"focused": False}, []),
        ]
        for snapshots, app, expected, raised in cases:
            fronted: list[int] = []
            feed = iter(snapshots)
            last = {"value": before}

            def snapshot() -> dict[int, str]:
                last["value"] = next(feed, last["value"])
                return last["value"]

            with patch.object(win32_windows, "_window_snapshot", snapshot), \
                 patch.object(win32_windows, "_bring_to_front", lambda h: fronted.append(h) or True), \
                 patch.object(win32_windows, "_LAUNCH_WAIT_S", 0.03), \
                 patch.object(win32_windows, "_LAUNCH_POLL_S", 0.01):
                self.assertEqual(win32_windows._bring_launched_window_to_front(before, app), expected)
            self.assertEqual(fronted, raised)


async def _listen(demo: bool = False) -> None:
    if demo:
        ws_server.start()
    overlay_file = ws_server._data_dir() / "overlay.json"
    warned = False
    while True:
        try:
            info = json.loads(overlay_file.read_text(encoding="utf-8"))
            uri = f"ws://{info['host']}:{info['port']}"
            async with connect(uri) as conn:
                await conn.send(json.dumps({"type": "hello", "token": info["token"]}))
                print(f"[hermis] conectado a {uri} -> {await conn.recv()}", flush=True)
                warned = False
                if demo:
                    tools.autopilot({"state": "on"})
                    tools.render_surface({
                        "surface": "notification",
                        "data": {"text": "Modo Piloto Automático listo", "level": "success"},
                    })
                    tools.render_surface({
                        "surface": "document",
                        "data": {"title": "Demo Día 2", "body_markdown": "# H.E.R.M.I.S\n- Servidor WS activo\n- Superficies listas"},
                    })
                    for _ in range(3):
                        print(await conn.recv(), flush=True)
                    return
                while True:
                    try:
                        raw = await asyncio.wait_for(conn.recv(), timeout=2.0)
                        print(raw, flush=True)
                    except TimeoutError:
                        cur = json.loads(overlay_file.read_text(encoding="utf-8"))
                        if cur.get("port") != info.get("port") or cur.get("token") != info.get("token"):
                            print("[hermis] overlay.json cambió de puerto; reconectando…", flush=True)
                            break
                print("[hermis] servidor WS cerró la conexión; esperando reconexión…", flush=True)
        except (OSError, ConnectionClosedError, json.JSONDecodeError, KeyError):
            if not warned:
                print(
                    f"[hermis] esperando servidor WS activo en {overlay_file} "
                    "(abrí una sesión de 'hermes' en otra terminal, o probá con '--demo')…",
                    flush=True,
                )
                warned = True
            await asyncio.sleep(2.0)


if __name__ == "__main__":
    if "--listen" in sys.argv or "--demo" in sys.argv:
        try:
            asyncio.run(_listen(demo="--demo" in sys.argv))
        except KeyboardInterrupt:
            pass
    else:
        unittest.main()
