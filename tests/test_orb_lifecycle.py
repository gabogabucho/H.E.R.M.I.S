"""Lifecycle observers must never modify agent results or persisted data."""
import json
import types
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock, patch

import test_commands

hermis = test_commands.hermis


class OrbLifecycleTest(unittest.TestCase):
    def setUp(self):
        test_commands.CommandTest.setUp(self)
        hermis.orb_lifecycle.reset()
        ctx = MagicMock(plugin_data_dir=self.tmp.name)
        with patch.object(hermis.ws_server, "start"):
            hermis.register(ctx)
        self.hooks = {c.args[0]: c.args[1] for c in ctx.register_hook.call_args_list}
        self.identity = {"session_id": "session", "task_id": "task", "turn_id": "turn"}

    def call(self, hook, **extra):
        return self.hooks[hook](**(self.identity | extra))

    def test_orb_sequence_preserves_context_and_storage(self):
        before = self.path.read_bytes()
        expected_context = hermis.tools.pre_llm_call()
        with patch.object(hermis.ws_server, "broadcast", return_value=1) as send:
            self.assertEqual(self.call("pre_llm_call"), expected_context)
            self.assertIsNone(self.call("pre_tool_call", tool_call_id="a"))
            self.assertIsNone(self.call("post_tool_call", tool_call_id="a", status="error"))
            self.assertIsNone(self.call("post_llm_call"))
        self.assertEqual([c.args[0] for c in send.call_args_list], [
            {"type": "state", "orb": state} for state in ("thinking", "acting", "thinking", "idle")
        ])
        self.assertEqual(self.path.read_bytes(), before)

    def test_orb_parallel_tools_do_not_finish_early(self):
        with patch.object(hermis.ws_server, "broadcast", return_value=1) as send:
            self.call("pre_llm_call")
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(self.call, "pre_tool_call", tool_call_id=call) for call in ("a", "b")]
                for future in futures:
                    self.assertIsNone(future.result(timeout=5))
            self.call("post_tool_call", tool_call_id="a")
            self.assertEqual(send.call_args.args[0]["orb"], "acting")
            self.call("post_tool_call", tool_call_id="b")
            self.assertEqual(send.call_args.args[0]["orb"], "thinking")
            self.call("post_llm_call")
            self.assertEqual(send.call_args.args[0]["orb"], "idle")
            count = send.call_count
            self.call("post_tool_call", tool_call_id="b")
            self.call("post_llm_call")
            self.assertEqual(send.call_count, count)

    def test_orb_independent_turns_and_late_events(self):
        with patch.object(hermis.ws_server, "broadcast", return_value=1) as send:
            self.call("pre_llm_call")
            self.call("pre_llm_call", turn_id="other")
            self.call("pre_tool_call", turn_id="other", tool_call_id="a")
            self.call("post_llm_call")
            self.assertEqual(send.call_args.args[0]["orb"], "acting")
            count = send.call_count
            self.call("post_tool_call", tool_call_id="late")
            self.assertEqual(send.call_count, count)
            self.call("post_tool_call", turn_id="other", tool_call_id="a")
            self.call("post_llm_call", turn_id="other")
            self.assertEqual(send.call_args.args[0]["orb"], "idle")

    def test_orb_disabled_or_unidentified_hooks_are_silent(self):
        with patch.object(hermis.ws_server, "broadcast") as send:
            self.hooks["pre_llm_call"]()
            self.hooks["pre_tool_call"](tool_call_id="a")
            hermis.ws_server.save_state({"autopilot": False, "surfaces": {}})
            for hook in self.hooks:
                self.assertIsNone(self.call(hook, tool_call_id="a"))
            send.assert_not_called()

    def test_orb_broadcast_failure_does_not_block_agent(self):
        with patch.object(hermis.ws_server, "broadcast", side_effect=RuntimeError("offline")):
            self.assertIn("context", self.call("pre_llm_call"))
            for hook in ("pre_tool_call", "post_tool_call", "post_llm_call"):
                self.assertIsNone(self.call(hook, tool_call_id="a"))

    def test_orb_mode_restart_forgets_old_activity(self):
        with patch.object(hermis.ws_server, "broadcast", return_value=1) as send, \
             patch.object(hermis.tools, "_refresh_windows_cache"):
            self.call("pre_llm_call")
            self.call("pre_tool_call", tool_call_id="stale")
            self.assertTrue(json.loads(hermis.tools.autopilot({"state": "off"}))["ok"])
            self.assertTrue(json.loads(hermis.tools.autopilot({"state": "on"}))["ok"])
            self.call("pre_llm_call", turn_id="new")
            self.assertEqual(send.call_args.args[0]["orb"], "thinking")
            self.call("post_llm_call", turn_id="new")
            self.assertEqual(send.call_args.args[0]["orb"], "idle")

    def test_orb_set_listening_respects_autopilot_and_deduplicates(self):
        with patch.object(hermis.ws_server, "broadcast", return_value=1) as send:
            hermis.orb_lifecycle.set_listening(True)
            hermis.orb_lifecycle.set_listening(True)
            hermis.orb_lifecycle.set_listening(False)
            hermis.orb_lifecycle.set_listening(False)
            self.assertEqual([c.args[0] for c in send.call_args_list], [
                {"type": "state", "orb": "listening"},
                {"type": "state", "orb": "idle"},
            ])
            send.reset_mock()
            hermis.ws_server.save_state({"autopilot": False, "surfaces": {}})
            hermis.orb_lifecycle.set_listening(True)
            send.assert_not_called()

    def test_orb_listening_transitions_to_thinking_and_idle(self):
        with patch.object(hermis.ws_server, "broadcast", return_value=1) as send:
            hermis.orb_lifecycle.set_listening(True)
            self.call("pre_llm_call")
            self.call("post_llm_call")
            self.assertEqual([c.args[0] for c in send.call_args_list], [
                {"type": "state", "orb": state} for state in ("listening", "thinking", "idle")
            ])

    def test_orb_voice_and_recorder_patches_drive_listening_state(self):
        class FakeRecorder:
            def __init__(self):
                self.is_recording = False
                self._cb = None

            def start(self, on_silence_stop=None):
                self.is_recording = True
                self._cb = on_silence_stop

            def stop(self):
                self.is_recording = False
                return "sample.wav"

            def cancel(self):
                self.is_recording = False

        class FakeWakeDetector:
            def _fire(self):
                return "fired"

        fake_voice = types.SimpleNamespace()
        captured = {}

        def fake_start_continuous(on_transcript, on_status=None, **kwargs):
            captured["on_status"] = on_status
            if on_status:
                on_status("listening")
            return True

        fake_voice.start_continuous = fake_start_continuous
        hermis.orb_lifecycle.patch_audio_recorder_class(FakeRecorder)
        hermis.orb_lifecycle.patch_audio_recorder_class(FakeRecorder)
        hermis.orb_lifecycle.patch_voice_module(fake_voice)
        hermis.orb_lifecycle.patch_voice_module(fake_voice)
        hermis.orb_lifecycle.patch_wake_detector_class(FakeWakeDetector)

        with patch.object(hermis.ws_server, "broadcast", return_value=1) as send:
            rec = FakeRecorder()
            rec.start()
            self.assertEqual(send.call_args.args[0], {"type": "state", "orb": "listening"})
            rec.stop()
            self.assertEqual(send.call_args.args[0], {"type": "state", "orb": "idle"})

            silence_called = []
            rec.start(on_silence_stop=lambda: silence_called.append(True))
            self.assertEqual(send.call_args.args[0], {"type": "state", "orb": "listening"})
            rec._cb()
            self.assertEqual(silence_called, [True])
            self.assertEqual(send.call_args.args[0], {"type": "state", "orb": "idle"})

            statuses = []
            fake_voice.start_continuous(lambda t: None, on_status=statuses.append)
            self.assertEqual(send.call_args.args[0], {"type": "state", "orb": "listening"})
            captured["on_status"]("transcribing")
            self.assertEqual(send.call_args.args[0], {"type": "state", "orb": "idle"})
            self.assertEqual(statuses, ["listening", "transcribing"])

            det = FakeWakeDetector()
            self.assertEqual(det._fire(), "fired")
            self.assertEqual(send.call_args.args[0], {"type": "state", "orb": "listening"})
            rec.cancel()
            self.assertEqual(send.call_args.args[0], {"type": "state", "orb": "idle"})
