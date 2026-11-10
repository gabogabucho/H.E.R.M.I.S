"""Public slash-command behavior and registration checks."""
from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = "hermis_commands_test"
if PACKAGE not in sys.modules:
    spec = importlib.util.spec_from_file_location(
        PACKAGE, ROOT / "__init__.py", submodule_search_locations=[str(ROOT)]
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[PACKAGE] = module
    spec.loader.exec_module(module)
hermis = sys.modules[PACKAGE]


class CommandTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.override = patch.dict(hermis.ws_server._STATE, data_dir_override=self.tmp.name)
        self.override.start()
        self.addCleanup(self.override.stop)
        hermis.ws_server.save_state({
            "autopilot": True, "seq": 1,
            "surfaces": {"doc": {"id": "doc", "surface": "document", "data": {"title": "Notes"}}},
            "onboarded": True,  # el onboarding tiene sus propios tests
        })
        self.path = Path(self.tmp.name) / "state.json"

    def dispatch(self, args):
        ctx = MagicMock(plugin_data_dir=self.tmp.name)
        with patch.object(hermis.ws_server, "start"):
            hermis.register(ctx)
        registration = ctx.register_command.call_args
        self.assertIsNotNone(registration, "register() must expose /hermis")
        self.assertEqual(registration.kwargs["name"], "hermis")
        self.assertEqual(registration.kwargs["args_hint"], "[status|on|off|check|setup|tour|gestures on|off]")
        return registration.kwargs["handler"](args)

    def test_command_status_is_read_only(self):
        before = self.path.read_bytes()
        with patch.object(hermis.ws_server, "broadcast") as broadcast, \
             patch.object(hermis.tools.overlay_launcher, "ensure_overlay_running") as launch:
            for args in ("", "status", "  STATUS  "):
                response = self.dispatch(args)
                self.assertIn("Autopilot: on", response)
                self.assertIn("Surfaces: 1", response)
                self.assertIn("not checked", response)
            broadcast.assert_not_called()
            launch.assert_not_called()
        self.assertEqual(self.path.read_bytes(), before)

    def test_command_on_off_reuses_autopilot(self):
        original = hermis.tools.autopilot
        with patch.object(hermis.tools, "autopilot", wraps=original) as handler, \
             patch.object(hermis.tools, "_safe_broadcast", return_value=(1, None)), \
             patch.object(hermis.tools, "_maybe_start_overlay", return_value=None), \
             patch.object(hermis.tools, "_refresh_windows_cache"):
            self.assertIn("Autopilot: off", self.dispatch("off"))
            self.assertFalse(hermis.ws_server.load_state()["autopilot"])
            self.assertEqual(hermis.ws_server.load_state()["surfaces"], {})
            self.assertIn("Autopilot: on", self.dispatch("on"))
            self.assertTrue(hermis.ws_server.load_state()["autopilot"])
            self.assertEqual([c.args[0] for c in handler.call_args_list], [{"state": "off"}, {"state": "on"}])

    def test_command_check_reports_limits_without_side_effects(self):
        before = self.path.read_bytes()
        with patch("shutil.which", return_value=None), \
             patch.object(hermis.ws_server, "broadcast") as broadcast, \
             patch.object(hermis.tools.overlay_launcher, "ensure_overlay_running") as launch:
            response = self.dispatch("check")
        self.assertIn("Node.js: missing", response)
        self.assertIn("npm: missing", response)
        self.assertIn("Voice: not verified", response)
        self.assertIn("Wake word: not verified", response)
        self.assertIn("Computer use: not verified", response)
        self.assertIn("not an end-to-end test", response)
        broadcast.assert_not_called()
        launch.assert_not_called()
        self.assertEqual(self.path.read_bytes(), before)

    def test_setup_preserves_welcome_until_first_activation(self):
        for completed in (False, True):
            with self.subTest(welcome_completed=completed):
                state = {"autopilot": False, "seq": 0, "surfaces": {},
                         "onboarded": completed, "gestures": False}
                hermis.ws_server.save_state(state)
                sent = []
                checklist = {"items": [], "title": "Setup", "subtitle": "Checked"}
                with patch.object(hermis.tools, "_safe_broadcast", side_effect=lambda m: (sent.append(m), (1, None))[1]), \
                     patch.object(hermis.tools, "_maybe_start_overlay", return_value=None), \
                     patch.object(hermis.tools, "_refresh_windows_cache"), \
                     patch.object(hermis.setup_checks, "surface_data", return_value=checklist), \
                     patch.object(hermis.setup_checks, "as_text", return_value="Setup checks"):
                    for _ in range(2):
                        self.assertIn("H.E.R.M.I.S setup", self.dispatch("setup"))
                        stored = hermis.ws_server.load_state()
                        self.assertEqual(stored.get("onboarded", False), completed)
                        self.assertFalse(stored["autopilot"])
                        self.assertFalse(stored.get("tour_pending", False))
                        self.assertEqual(stored["surfaces"]["hermis-setup"]["data"], checklist)
                        self.assertEqual(sent[-1]["surface"], "setup")
                    sent.clear()
                    self.assertIn("Autopilot: on", self.dispatch("on"))
                    stored = hermis.ws_server.load_state()
                    self.assertTrue(stored["onboarded"])
                    self.assertEqual(bool(stored.get("tour_pending")), not completed)
                    guides = [m for m in sent if m.get("id") == hermis.welcome.WELCOME_ID]
                    self.assertEqual(len(guides), 0 if completed else 1)
                    hermis.welcome.post_llm_call()
                    self.dispatch("off")
                    sent.clear()
                    self.dispatch("on")
                    self.assertFalse([m for m in sent if m.get("id") == hermis.welcome.WELCOME_ID])


    def test_command_rejects_unknown_or_extra_arguments(self):
        before = self.path.read_bytes()
        with patch.object(hermis.tools, "autopilot") as handler:
            for args in ("unknown", "on extra", "off --force", "status extra", "check extra"):
                self.assertIn("Usage: /hermis", self.dispatch(args))
            handler.assert_not_called()
        self.assertEqual(self.path.read_bytes(), before)

    def test_command_registration_preserves_tools_and_context_hook(self):
        ctx = MagicMock(plugin_data_dir=self.tmp.name)
        with patch.object(hermis.ws_server, "start"):
            hermis.register(ctx)
        self.assertEqual({c.kwargs["name"] for c in ctx.register_tool.call_args_list}, {
            "autopilot", "render_surface", "close_surface", "list_surfaces", "layout_windows", "launch_app",
        })
        ctx.register_hook.assert_any_call("pre_llm_call", hermis.tools.pre_llm_call)
        self.assertEqual({c.args[0] for c in ctx.register_hook.call_args_list}, {
            "pre_llm_call", "pre_tool_call", "post_tool_call", "post_llm_call",
        })
        self.assertIsNotNone(ctx.register_command.call_args)


if __name__ == "__main__":
    unittest.main()
