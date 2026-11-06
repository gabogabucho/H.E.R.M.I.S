"""Tests del esqueleto Día 1 + cliente WS en vivo (`--listen`).

- Tests:  python -m unittest discover -s tests -v
- Listen: python tests/test_skeleton.py --listen
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
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
    def test_schema_and_validation(self) -> None:
        self.assertEqual(schemas.RENDER_SURFACE_SCHEMA["name"], "render_surface")
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
        ]
        for payload in bad_cases:
            res = json.loads(tools.render_surface(payload))  # type: ignore[arg-type]
            self.assertFalse(res["ok"], f"esperaba ok=False para {payload!r}")

    def test_ws_handshake_and_broadcast(self) -> None:
        tmp = tempfile.mkdtemp()
        ctx = MagicMock(plugin_data_dir=tmp)
        hermis.register(ctx)
        ctx.register_tool.assert_called_once()

        info = json.loads((Path(tmp) / "overlay.json").read_text(encoding="utf-8"))
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

                out = json.loads(tools.render_surface({
                    "surface": "document",
                    "data": {"title": "Día 1", "body_markdown": "# Hola H.E.R.M.I.S"},
                }))
                self.assertTrue(out["ok"])
                self.assertEqual(out["delivered"], 1)
                self.assertTrue(out["overlay_connected"])

                msg = json.loads(await asyncio.wait_for(client.recv(), timeout=2.0))
                self.assertEqual(msg, {
                    "type": "render",
                    "surface": "document",
                    "data": {"title": "Día 1", "body_markdown": "# Hola H.E.R.M.I.S"},
                })

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
                    tools.render_surface({
                        "surface": "notification",
                        "data": {"text": "Modo Piloto Automático listo", "level": "success"},
                    })
                    tools.render_surface({
                        "surface": "document",
                        "data": {"title": "Demo Día 1", "body_markdown": "# H.E.R.M.I.S\n- Servidor WS activo\n- Superficies listas"},
                    })
                    print(await conn.recv(), flush=True)
                    print(await conn.recv(), flush=True)
                    return
                async for raw in conn:
                    print(raw, flush=True)
        except (OSError, json.JSONDecodeError, KeyError):
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
