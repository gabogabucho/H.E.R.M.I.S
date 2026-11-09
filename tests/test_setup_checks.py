"""Onboarding: los chequeos son de solo lectura y dan el comando exacto para lo que falta."""
import importlib.util
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
PACKAGE = "hermis_setup_test"  # nombre propio: no pisa el paquete de los otros tests
if PACKAGE not in sys.modules:
    _spec = importlib.util.spec_from_file_location(PACKAGE, ROOT / "__init__.py", submodule_search_locations=[str(ROOT)])
    _mod = importlib.util.module_from_spec(_spec)
    sys.modules[PACKAGE] = _mod
    _spec.loader.exec_module(_mod)
hermis = sys.modules[PACKAGE]
checks = hermis.setup_checks


def by_id(items):
    return {it["id"]: it for it in items}


class SetupChecksTest(unittest.TestCase):
    def run_with(self, config, modules=(), env=None, node=True, node_modules=True):
        def has_module(name):
            return name in modules

        with patch.object(checks, "_read_config", return_value=config), \
             patch.object(checks, "_has_module", side_effect=has_module), \
             patch.object(checks.shutil, "which", lambda exe: f"C:\\bin\\{exe}" if node else None), \
             patch.object(Path, "is_dir", lambda self: node_modules), \
             patch.dict(os.environ, env or {}, clear=False):
            if env is not None and "ELEVENLABS_API_KEY" not in env:
                os.environ.pop("ELEVENLABS_API_KEY", None)
            return by_id(checks.run_checks())

    def test_fresh_install_lists_every_missing_step_with_its_command(self):
        items = self.run_with({"tts": {"provider": "elevenlabs"}}, env={}, node_modules=False)
        self.assertEqual(items["overlay"]["status"], "warn")
        self.assertIn("npm ci", items["overlay"]["fix"])
        self.assertIn("--extra stt-whisper", items["stt"]["fix"])
        self.assertIn("hermes gateway stop", items["stt"]["fix"])
        self.assertEqual(items["stt_language"]["fix"], "hermes config set stt.language es")
        self.assertIn("--extra tts-premium", items["tts"]["fix"])
        self.assertIn("--extra wake-openwakeword", items["wake"]["fix"])
        self.assertIn("cua:type:foreground", items["computer_use"]["fix"])

    def test_elevenlabs_key_is_checked_by_presence_only(self):
        config = {"tts": {"provider": "elevenlabs"}}
        missing = self.run_with(config, modules=("elevenlabs",), env={})
        self.assertEqual(missing["tts"]["status"], "warn")
        self.assertEqual(missing["tts"]["fix"], "ELEVENLABS_API_KEY=")
        ready = self.run_with(config, modules=("elevenlabs",), env={"ELEVENLABS_API_KEY": "secret-value"})
        self.assertEqual(ready["tts"]["status"], "ok")
        self.assertNotIn("secret-value", str(ready))

    def test_elevenlabs_transcription_needs_the_key_too(self):
        config = {"stt": {"provider": "elevenlabs", "language": "es"}}
        missing = self.run_with(config, env={})
        self.assertEqual(missing["stt"]["status"], "warn")
        self.assertEqual(missing["stt"]["fix"], "ELEVENLABS_API_KEY=")
        ready = self.run_with(config, env={"ELEVENLABS_API_KEY": "secret-value"})
        self.assertEqual(ready["stt"]["status"], "ok")

    def test_auto_tts_off_points_to_the_desktop_read_aloud_toggle(self):
        # El Desktop guarda "leer en voz alta" localmente; la config solo no alcanza.
        items = self.run_with({"voice": {"auto_tts": False}, "tts": {"provider": "edge"}})
        self.assertEqual(items["tts"]["status"], "info")
        self.assertIn("activá el parlante", items["tts"]["detail"])
        self.assertIn("hermes config set voice.auto_tts true", items["tts"]["fix"])
        # El paso fijo explica dónde están los toggles que el plugin no puede leer.
        desktop = items["desktop"]["detail"]
        for hint in ("This device", "la oreja", "el parlante", "botón negro"):
            self.assertIn(hint, desktop)
        self.assertNotIn("fix", items["desktop"])

    def test_configured_machine_is_all_ok(self):
        config = {
            "stt": {"language": "es"},
            "tts": {"provider": "edge"},
            "wake_word": {"enabled": True},
            "command_allowlist": ["cua:type:foreground"],
        }
        items = self.run_with(config, modules=("faster_whisper", "pyopen_wakeword"))
        self.assertEqual({k: v["status"] for k, v in items.items()},
                         {**{k: "ok" for k in ("overlay", "stt", "stt_language", "tts", "wake", "computer_use")}, "desktop": "info"})
        self.assertEqual(checks.surface_data()["items"][0]["id"], "overlay")

    def test_unreadable_config_degrades_to_info(self):
        items = self.run_with(None, modules=("faster_whisper", "pyopen_wakeword"))
        self.assertEqual(items["stt_language"]["status"], "info")

    def test_a_crashing_check_never_breaks_the_rest(self):
        with patch.object(checks, "_check_overlay", side_effect=RuntimeError("boom")), \
             patch.object(checks, "_read_config", return_value={}):
            items = checks.run_checks()
        self.assertEqual(len(items), 7)
        self.assertEqual(items[0]["status"], "info")

    def test_text_version_includes_commands(self):
        with patch.object(checks, "run_checks", return_value=[
            {"id": "wake", "label": "Wake word", "status": "warn", "detail": "Falta.", "fix": "hermes pm install --extra wake-openwakeword"},
        ]):
            text = checks.as_text()
        self.assertIn("[falta] Wake word: Falta.", text)
        self.assertIn("    hermes pm install --extra wake-openwakeword", text)


if __name__ == "__main__":
    unittest.main()
