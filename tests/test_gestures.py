"""Gestos v1: flag en state, comando /hermis gestures, sync y gesture.close."""
from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = "hermis_gestures_test"  # nombre propio: no pisa el paquete de los otros tests
if PACKAGE not in sys.modules:
    spec = importlib.util.spec_from_file_location(
        PACKAGE, ROOT / "__init__.py", submodule_search_locations=[str(ROOT)]
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[PACKAGE] = module
    spec.loader.exec_module(module)
hermis = sys.modules[PACKAGE]

STATE = hermis.ws_server
TOOLS = hermis.tools
COMMANDS = hermis.commands


class _FakeConn:
    """Conn mínima para _handler: recibe el hello, junta lo enviado, cierra el stream."""

    def __init__(self, incoming):
        self._incoming = list(incoming)
        self.sent = []

    async def recv(self):
        if self._incoming:
            return self._incoming.pop(0)
        raise asyncio.IncompleteReadError(b"", None)

    async def send(self, text):
        self.sent.append(text)

    async def close(self, code=None, reason=None):
        pass

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._incoming:
            return self._incoming.pop(0)
        raise StopAsyncIteration


class GesturesStateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.override = patch.dict(STATE._STATE, data_dir_override=self.tmp.name, token="tok-test")
        self.override.start()
        self.addCleanup(self.override.stop)

    def test_gestures_flag_defaults_to_off_and_survives_roundtrip(self):
        # Apagado por defecto, incluso sin archivo.
        self.assertFalse(STATE.load_state()["gestures"])
        STATE.save_state({"autopilot": True, "seq": 0, "surfaces": {}, "gestures": True})
        self.assertTrue(STATE.load_state()["gestures"])
        # Sin la clave (state.json viejo) vuelve a ser False.
        STATE.save_state({"autopilot": False, "seq": 0, "surfaces": {}})
        self.assertFalse(STATE.load_state()["gestures"])

    def test_set_gestures_persists_flag_and_warns_overlay(self):
        with patch.object(STATE, "broadcast", return_value=1) as broadcast:
            out = json.loads(TOOLS.set_gestures({"enabled": True}))
        self.assertTrue(out["ok"])
        self.assertTrue(out["overlay_connected"])
        self.assertTrue(STATE.load_state()["gestures"])
        broadcast.assert_called_once_with({"type": "gestures", "enabled": True})
        with patch.object(STATE, "broadcast", return_value=0) as broadcast:
            out = json.loads(TOOLS.set_gestures({"enabled": False}))
        self.assertFalse(STATE.load_state()["gestures"])
        self.assertFalse(out["overlay_connected"])
        broadcast.assert_called_once_with({"type": "gestures", "enabled": False})

    def test_set_gestures_requires_bool(self):
        for bad in ("yes", 1, None):
            with patch.object(STATE, "broadcast") as broadcast:
                out = json.loads(TOOLS.set_gestures({"enabled": bad}))
                self.assertFalse(out["ok"])
                self.assertEqual(out["error"], "invalid_enabled")
                broadcast.assert_not_called()
        self.assertFalse(STATE.load_state()["gestures"])

    def test_connect_sync_includes_gestures_message(self):
        STATE.save_state({"autopilot": True, "seq": 0, "surfaces": {}, "gestures": True})
        conn = _FakeConn([json.dumps({"type": "hello", "token": "tok-test"})])
        asyncio.run(STATE._handler(conn))
        msgs = [json.loads(t) for t in conn.sent]
        self.assertEqual(msgs[0], {"type": "hello_ok"})
        self.assertIn({"type": "gestures", "enabled": True}, msgs)
        self.assertIn({"type": "mode", "autopilot": True}, msgs)

    def test_connect_sync_sends_gestures_off_by_default(self):
        STATE.save_state({"autopilot": True, "seq": 0, "surfaces": {}})
        conn = _FakeConn([json.dumps({"type": "hello", "token": "tok-test"})])
        asyncio.run(STATE._handler(conn))
        msgs = [json.loads(t) for t in conn.sent]
        self.assertIn({"type": "gestures", "enabled": False}, msgs)


class GestureCloseTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.override = patch.dict(STATE._STATE, data_dir_override=self.tmp.name)
        self.override.start()
        self.addCleanup(self.override.stop)
        STATE.save_state({
            "autopilot": True, "seq": 1, "gestures": True,
            "surfaces": {"doc-1": {"id": "doc-1", "surface": "document", "data": {"title": "Notas"}}},
        })
        self.path = Path(self.tmp.name) / "state.json"

    def _wait_until(self, predicate, timeout=2.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if predicate():
                return True
            time.sleep(0.01)
        return False

    def test_gesture_close_message_closes_like_close_surface(self):
        # Debe correr fuera del loop del WS y comportarse como close_surface:
        # actualiza state.json y difunde close con el id.
        with patch.object(STATE, "broadcast", return_value=1) as broadcast:
            STATE._handle_client_message(json.dumps({"type": "gesture.close", "id": "doc-1"}))
            self.assertTrue(self._wait_until(lambda: not STATE.load_state()["surfaces"]))
        self.assertEqual(STATE.load_state()["surfaces"], {})
        broadcast.assert_any_call({"type": "close", "id": "doc-1"})

    def test_gesture_close_ignores_missing_or_invalid_ids(self):
        with patch.object(STATE, "broadcast", return_value=1) as broadcast:
            for payload in (
                {"type": "gesture.close"},
                {"type": "gesture.close", "id": "   "},
                {"type": "gesture.close", "id": 7},
            ):
                STATE._handle_client_message(json.dumps(payload))
            time.sleep(0.15)  # no debe haber hilo ni difusión
        self.assertIn("doc-1", STATE.load_state()["surfaces"])
        broadcast.assert_not_called()


class GesturesCommandTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.override = patch.dict(STATE._STATE, data_dir_override=self.tmp.name)
        self.override.start()
        self.addCleanup(self.override.stop)
        STATE.save_state({"autopilot": False, "seq": 0, "surfaces": {}, "onboarded": True})
        self.path = Path(self.tmp.name) / "state.json"

    def dispatch(self, args):
        return COMMANDS.handle(args)

    def test_command_gestures_on_persists_and_answers(self):
        with patch.object(STATE, "broadcast", return_value=1):
            self.assertIn("Gestures: on", self.dispatch("gestures on"))
        self.assertTrue(STATE.load_state()["gestures"])
        with patch.object(STATE, "broadcast", return_value=0):
            response = self.dispatch("gestures off")
        self.assertIn("Gestures: off", response)
        self.assertFalse(STATE.load_state()["gestures"])

    def test_command_status_shows_gestures_flag(self):
        self.assertIn("Gestures: off", self.dispatch("status"))
        with patch.object(STATE, "broadcast", return_value=1):
            self.dispatch("gestures on")
        self.assertIn("Gestures: on", self.dispatch("status"))
        self.assertIn("Gestures: on", self.dispatch(""))

    def test_command_gestures_needs_on_off_argument(self):
        before = self.path.read_bytes()
        with patch.object(STATE, "broadcast") as broadcast:
            for args in ("gestures", "gestures maybe", "gestures on extra"):
                self.assertIn("Usage: /hermis", self.dispatch(args))
            broadcast.assert_not_called()
        self.assertEqual(self.path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
