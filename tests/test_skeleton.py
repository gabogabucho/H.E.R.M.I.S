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
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

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


class SkeletonTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        with ws_server._lock:
            ws_server._STATE["data_dir_override"] = self.tmp
            ws_server._STATE["thread"] = None
            ws_server._STATE["loop"] = None
            ws_server._STATE["port"] = None
            ws_server._STATE["token"] = None
            ws_server._clients.clear()
        ws_server._ready.clear()

    def test_schema_and_validation(self) -> None:
        self.assertEqual(schemas.AUTOPILOT_SCHEMA["name"], "autopilot")
        self.assertEqual(schemas.RENDER_SURFACE_SCHEMA["name"], "render_surface")
        self.assertEqual(schemas.CLOSE_SURFACE_SCHEMA["name"], "close_surface")
        self.assertEqual(schemas.LIST_SURFACES_SCHEMA["name"], "list_surfaces")

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
            {"surface": "custom", "data": {"html": "   "}},
        ]
        for payload in bad_cases:
            res = json.loads(tools.render_surface(payload))  # type: ignore[arg-type]
            self.assertFalse(res["ok"], f"esperaba ok=False para {payload!r}")

        self.assertFalse(json.loads(tools.autopilot(None))["ok"])  # type: ignore[arg-type]
        self.assertFalse(json.loads(tools.autopilot({"state": "maybe"}))["ok"])
        self.assertFalse(json.loads(tools.close_surface(None))["ok"])  # type: ignore[arg-type]
        self.assertFalse(json.loads(tools.close_surface({"id": "  "}))["ok"])

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
            ("custom", {"title": "Widget", "html": "<div>Hola</div>"}),
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
        self.assertIn("Juan Pérez", ctx_text)
        self.assertIn("Hola, adjunto el TP final.", ctx_text)

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
        self.assertEqual(ctx.register_tool.call_count, 4)
        ctx.register_hook.assert_called_once_with("pre_llm_call", tools.pre_llm_call)

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
                mode_off = json.loads(await asyncio.wait_for(client.recv(), timeout=2.0))
                self.assertEqual(mode_off, {"type": "mode", "autopilot": False})

        asyncio.run(scenario())


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
