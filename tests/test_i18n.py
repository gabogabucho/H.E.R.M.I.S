"""Sistema de idiomas: catálogo único es/en, resolución de locale y /hermis lang."""
from __future__ import annotations

import importlib.util
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = "hermis_i18n_test"
if PACKAGE not in sys.modules:
    _spec = importlib.util.spec_from_file_location(
        PACKAGE, ROOT / "__init__.py", submodule_search_locations=[str(ROOT)]
    )
    _mod = importlib.util.module_from_spec(_spec)
    sys.modules[PACKAGE] = _mod
    _spec.loader.exec_module(_mod)
hermis = sys.modules[PACKAGE]
i18n = hermis.i18n

_PLACEHOLDER = re.compile(r"\{(\w+)\}")


def _raw(locale: str) -> dict:
    return json.loads((ROOT / "messages" / f"{locale}.json").read_text(encoding="utf-8"))


class CatalogTest(unittest.TestCase):
    """messages/es.json y messages/en.json tienen que ser el mismo catálogo."""

    def test_both_languages_have_exactly_the_same_keys(self):
        es = {k: v for k, v in _raw("es").items() if not k.startswith("_")}
        en = {k: v for k, v in _raw("en").items() if not k.startswith("_")}
        self.assertTrue(es, "el catálogo no puede estar vacío")
        self.assertEqual(sorted(set(es) - set(en)), [], "faltan claves en en.json")
        self.assertEqual(sorted(set(en) - set(es)), [], "faltan claves en es.json")

    def test_no_text_is_empty(self):
        for locale in ("es", "en"):
            for key, value in _raw(locale).items():
                if key.startswith("_"):
                    continue
                self.assertIsInstance(value, str)
                self.assertTrue(value.strip(), f"{locale}:{key} está vacío")

    def test_placeholders_are_the_same_in_both_languages(self):
        es = {k: v for k, v in _raw("es").items() if not k.startswith("_")}
        en = {k: v for k, v in _raw("en").items() if not k.startswith("_")}
        for key, value in es.items():
            self.assertEqual(set(_PLACEHOLDER.findall(value)), set(_PLACEHOLDER.findall(en[key])),
                             f"los placeholders de {key} no coinciden")

    def test_the_catalog_covers_every_area_of_the_plugin(self):
        keys = set(_raw("es"))
        for prefix in ("overlay.", "welcome.", "setup.", "launcher.", "commands."):
            self.assertTrue(any(k.startswith(prefix) for k in keys), f"falta la sección {prefix}")

    def test_the_overlay_only_gets_its_own_texts(self):
        strings = i18n.overlay_strings("es")
        self.assertTrue(strings)
        self.assertTrue(all(k.startswith("overlay.") for k in strings))
        self.assertIn("overlay.copy", strings)


class LocaleTest(unittest.TestCase):
    def test_normalize_accepts_regional_variants(self):
        for value, expected in (("es", "es"), ("es-AR", "es"), ("ES", "es"), ("en_US", "en"),
                                ("en-GB", "en"), ("fr", None), ("", None), (None, None)):
            self.assertEqual(i18n.normalize_locale(value), expected, value)

    def test_manual_override_wins_over_the_hermes_config(self):
        self.assertEqual(i18n.resolve_locale("es", {"stt": {"language": "en"}}), "es")
        self.assertEqual(i18n.resolve_locale("en", {"stt": {"language": "es"}}), "en")

    def test_without_override_it_follows_the_language_of_hermes(self):
        self.assertEqual(i18n.resolve_locale(None, {"stt": {"language": "es"}}), "es")
        self.assertEqual(i18n.resolve_locale(None, {"stt": {"language": "en-US"}}), "en")

    def test_without_config_it_falls_back_to_the_base_language(self):
        self.assertEqual(i18n.resolve_locale(None, {}), i18n.BASE_LOCALE)
        # Sin config explícita se lee la de Hermes (en esta máquina: es).
        self.assertIn(i18n.resolve_locale(None, None), i18n.SUPPORTED)

    def test_translation_uses_the_requested_language(self):
        self.assertEqual(i18n.t("overlay.copy", "es"), "Copiar")
        self.assertEqual(i18n.t("overlay.copy", "en"), "Copy")

    def test_unknown_key_returns_the_key_instead_of_breaking(self):
        self.assertEqual(i18n.t("no.existe.esta.clave", "es"), "no.existe.esta.clave")

    def test_placeholders_are_filled(self):
        self.assertEqual(i18n.t("setup.stt.cloud_provider", "en", provider="elevenlabs"),
                         "Cloud provider: elevenlabs.")

    def test_a_missing_translation_falls_back_to_the_base_language(self):
        # Se simula quitando la clave del catálogo español.
        original = i18n._catalog
        try:
            i18n._catalog = lambda locale: {} if locale == "es" else original(locale)
            self.assertEqual(i18n.t("overlay.copy", "es"), "Copy")
        finally:
            i18n._catalog = original


class LangCommandTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        override = patch.dict(hermis.ws_server._STATE, data_dir_override=self.tmp.name)
        override.start()
        self.addCleanup(override.stop)
        hermis.ws_server.save_state({"autopilot": False, "seq": 0, "surfaces": {}, "locale": "en"})

    def test_lang_switches_the_interface_and_says_it_in_the_new_language(self):
        with patch.object(hermis.ws_server, "broadcast", return_value=1):
            response = hermis.commands.handle("lang es")
        self.assertIn("es", response)
        self.assertEqual(hermis.ws_server.load_state()["locale"], "es")

    def test_lang_without_argument_reports_the_current_language(self):
        response = hermis.commands.handle("lang")
        self.assertIn("en", response)

    def test_lang_reset_goes_back_to_the_language_of_hermes(self):
        with patch.object(hermis.ws_server, "broadcast", return_value=1):
            hermis.commands.handle("lang es")
            hermis.commands.handle("lang reset")
        self.assertNotIn("locale", hermis.ws_server.load_state())

    def test_an_unknown_language_is_refused(self):
        response = hermis.commands.handle("lang fr")
        self.assertIn("fr", response)
        self.assertEqual(hermis.ws_server.load_state()["locale"], "en")

    def test_the_language_reaches_the_overlay(self):
        sent: list[dict] = []
        with patch.object(hermis.ws_server, "broadcast", side_effect=lambda m: (sent.append(m), 1)[1]):
            hermis.commands.handle("lang es")
        i18n_messages = [m for m in sent if m.get("type") == "i18n"]
        self.assertEqual(len(i18n_messages), 1)
        self.assertEqual(i18n_messages[0]["locale"], "es")
        self.assertEqual(i18n_messages[0]["strings"]["overlay.copy"], "Copiar")


class OverlayCatalogTest(unittest.TestCase):
    """El overlay recibe los textos por el WebSocket: no puede leerlos del disco."""

    def test_the_i18n_message_carries_the_language_and_the_texts(self):
        message = hermis.ws_server.i18n_message("en")
        self.assertEqual(message["type"], "i18n")
        self.assertEqual(message["locale"], "en")
        self.assertEqual(message["strings"]["overlay.copy"], "Copy")

    def test_the_overlay_javascript_uses_the_catalog_and_not_hardcoded_texts(self):
        shell = (ROOT / "overlay" / "renderer" / "shell.js").read_text(encoding="utf-8")
        self.assertIn("function t(key, fallback)", shell)
        self.assertIn("I18N.locale", shell)
        self.assertIn("'i18n'", shell)
        # La fecha ya no sale forzada en es-AR: usa el idioma de la interfaz.
        self.assertNotIn("toLocaleDateString('es-AR'", shell)
        self.assertNotIn("toLocaleTimeString('es-AR'", shell)


if __name__ == "__main__":
    unittest.main()
