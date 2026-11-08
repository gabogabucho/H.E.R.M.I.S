"""Tests del puente automático de artefactos (artifact_bridge.post_llm_call)."""
from __future__ import annotations

import json
import os
import unittest
from unittest.mock import MagicMock, patch

import test_commands

hermis = test_commands.hermis
tools = hermis.tools
ws_server = hermis.ws_server
bridge = hermis.artifact_bridge

_HTML_BLOCK = """```html
<!doctype html>
<html>
<head><title>Ventas 2026</title></head>
<body>
  <h1>Ventas por trimestre</h1>
  <p>Gráfico de barras del año en curso con datos consolidados.</p>
</body>
</html>
```"""

# ≥ 2000 caracteres, como exige el criterio de artifact-detect.ts para svg.
_SVG_BODY = ('<svg xmlns="http://www.w3.org/2000/svg" width="400" height="300">'
             '<title>Diagrama de red</title>'
             '<!-- ' + 'x' * 2000 + ' -->'
             '</svg>')


class ArtifactBridgeTest(unittest.TestCase):
    def setUp(self):
        test_commands.CommandTest.setUp(self)
        os.environ["HERMIS_OVERLAY_AUTOSTART"] = "0"
        self.addCleanup(os.environ.pop, "HERMIS_OVERLAY_AUTOSTART", None)
        hermis.orb_lifecycle.reset()
        ctx = MagicMock(plugin_data_dir=self.tmp.name)
        with patch.object(hermis.ws_server, "start"):
            hermis.register(ctx)
        self.assertTrue(json.loads(tools.autopilot({"state": "on"}))["ok"])

    def renders(self, response: str) -> list[dict]:
        with patch.object(ws_server, "broadcast", return_value=1) as send:
            bridge.post_llm_call(session_id="s", task_id="t", turn_id="u",
                                 assistant_response=response)
            return [c.args[0] for c in send.call_args_list
                    if c.args[0].get("type") == "render" and c.args[0].get("surface") == "artifact"]

    def test_html_block_renders_artifact_with_title_and_stable_id(self):
        renders = self.renders(f"Antes del bloque.\n\n{_HTML_BLOCK}\n\nDespués.")
        self.assertEqual(len(renders), 1)
        msg = renders[0]
        self.assertEqual(msg["id"], bridge.artifact_id("html", "Ventas 2026"))
        self.assertEqual(msg["data"]["kind"], "html")
        self.assertEqual(msg["data"]["title"], "Ventas 2026")
        self.assertIn("<!doctype html>", msg["data"]["content"])

        # Una versión nueva del mismo gráfico (mismo kind + título) reutiliza el id
        updated = _HTML_BLOCK.replace("del año en curso", "del año en curso (v2)")
        again = self.renders(updated)
        self.assertEqual(again[0]["id"], msg["id"])
        persisted = ws_server.load_state()["surfaces"][msg["id"]]
        self.assertIn("(v2)", persisted["data"]["content"])

    def test_svg_block_renders_artifact(self):
        renders = self.renders(f"Acá va el diagrama:\n\n```svg\n{_SVG_BODY}\n```\n")
        self.assertEqual(len(renders), 1)
        msg = renders[0]
        self.assertEqual(msg["data"]["kind"], "svg")
        self.assertEqual(msg["data"]["title"], "Diagrama de red")
        self.assertEqual(msg["id"], bridge.artifact_id("svg", "Diagrama de red"))

    def test_small_block_does_not_qualify(self):
        renders = self.renders("Mirá:\n\n```html\n<p>hola</p>\n```\n")
        self.assertEqual(renders, [])

    def test_response_without_blocks_does_nothing(self):
        self.assertEqual(self.renders("Solo texto, sin bloques de código."), [])

    def test_mode_off_does_nothing(self):
        self.assertTrue(json.loads(tools.autopilot({"state": "off"}))["ok"])
        renders = self.renders(_HTML_BLOCK)
        self.assertEqual(renders, [])

    def test_oversized_content_is_rejected_without_broadcast(self):
        huge = "```html\n" + "<!doctype html><html><body>" + "y" * (256 * 1024) + "</body></html>\n```"
        with patch.object(ws_server, "broadcast", return_value=1) as send:
            res = json.loads(tools.render_surface({
                "surface": "artifact", "id": "artifact-x",
                "data": {"kind": "html", "title": "Enorme", "content": "y" * (256 * 1024 + 10)},
            }))
            self.assertFalse(res["ok"])
            self.assertIn("256 KB", res["message"])
            bridge.post_llm_call(session_id="s", task_id="t", turn_id="u", assistant_response=huge)
            self.assertEqual(send.call_count, 0)

    def test_bridge_never_raises(self):
        for kwargs in ({}, {"assistant_response": None}, {"assistant_response": 42},
                       {"assistant_response": "```html\nroto"}):
            self.assertIsNone(bridge.post_llm_call(**kwargs))


if __name__ == "__main__":
    unittest.main()
