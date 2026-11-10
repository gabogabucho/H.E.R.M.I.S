"""Observable local bootstrap and non-destructive recovery."""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = "hermis_bootstrap_test"
spec = importlib.util.spec_from_file_location(PACKAGE, ROOT / "__init__.py", submodule_search_locations=[str(ROOT)])
hermis = importlib.util.module_from_spec(spec)
sys.modules[PACKAGE] = hermis
spec.loader.exec_module(hermis)
launcher = hermis.overlay_launcher


class BootstrapTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name)
        self.overlay = self.directory / "overlay"
        self.overlay.mkdir()
        self.worker = None
        for mock in (
            patch.dict(os.environ, HERMIS_OVERLAY_AUTOSTART="1"),
            patch.dict(hermis.ws_server._STATE, data_dir_override=self.tmp.name),
            patch.object(launcher, "_overlay_dir", self.overlay),
            patch.object(launcher, "_last_launch", None),
            patch.object(launcher, "_pipeline_busy", False),
            patch.object(launcher, "_launch_process", None),
            patch.object(launcher, "_bootstrap", {"phase": "idle", "error": None, "started_at": 0}),
            patch.object(hermis.ws_server, "overlay_connected", return_value=False),
            patch.object(launcher, "runtime_status", return_value={"node": "node", "npm": "npm", "version": "v22.12.0", "error": None}),
        ):
            mock.start()
            self.addCleanup(mock.stop)
        hermis.ws_server.save_state({"autopilot": True, "onboarded": True, "seq": 1,
                                    "surfaces": {"doc": {"id": "doc", "surface": "document", "data": {"title": "Keep"}}}})
        self.before = (self.directory / "state.json").read_bytes()

    def launch(self, install_result=0, process=None, error=None):
        original = threading.Thread

        def worker(*args, **kwargs):
            self.worker = original(*args, **kwargs)
            return self.worker

        process = process or Mock(poll=Mock(return_value=0))
        with patch.object(launcher.threading, "Thread", side_effect=worker), \
             patch.object(launcher.subprocess, "run", side_effect=error,
                          return_value=subprocess.CompletedProcess([], install_result)), \
             patch.object(launcher.subprocess, "Popen", return_value=process) as start:
            note = launcher.ensure_overlay_running()
            self.worker.join(timeout=2)
            self.assertFalse(self.worker.is_alive())
        return note, start.call_count

    def test_install_failures_are_sanitized_and_retry_preserves_state(self):
        for error, code in ((None, "install_failed"),
                            (subprocess.TimeoutExpired("secret-token", 300), "install_timeout"),
                            (PermissionError("secret-token"), "install_denied")):
            with self.subTest(code=code):
                launcher.reset_cooldown()
                self.launch(install_result=7, error=error)
                status = launcher.bootstrap_status()
                self.assertEqual(status["phase"], "failed")
                self.assertEqual(status["error"], code)
                self.assertNotIn("secret-token", str(status))
                self.assertFalse((self.directory / "overlay.launch").exists())
                with patch.object(launcher.threading, "Thread") as worker:
                    response = hermis.commands.handle("retry")
                    self.assertNotIn("Usage:", response)
                    worker.return_value.start.assert_called_once()
                self.assertEqual((self.directory / "state.json").read_bytes(), self.before)
                launcher._pipeline_busy = False

    def test_active_install_retry_does_not_start_another_worker(self):
        started, release = threading.Event(), threading.Event()
        original = threading.Thread

        def install(*args, **kwargs):
            started.set()
            release.wait(timeout=2)
            return subprocess.CompletedProcess([], 7)

        workers = []
        def make_worker(*args, **kwargs):
            worker = original(*args, **kwargs)
            workers.append(worker)
            return worker

        with patch.object(launcher.threading, "Thread", side_effect=make_worker), \
             patch.object(launcher.subprocess, "run", side_effect=install):
            try:
                launcher.ensure_overlay_running()
                self.assertTrue(started.wait(timeout=1))
                self.assertEqual(launcher.bootstrap_status()["phase"], "installing")
                self.assertIn("installing", hermis.commands.handle("retry"))
                self.assertEqual(len(workers), 1)
            finally:
                release.set()
                for worker in workers:
                    worker.join(timeout=2)
        self.assertEqual((self.directory / "state.json").read_bytes(), self.before)

    def test_starting_is_not_connected_and_live_wrapper_blocks_retry(self):
        process = Mock(poll=Mock(return_value=None))
        self.launch(process=process)
        with patch.object(launcher, "_STARTUP_TIMEOUT_S", -1):
            status = launcher.bootstrap_status()
            self.assertEqual(status["phase"], "failed")
            self.assertEqual(status["error"], "startup_timeout")
            with patch.object(launcher.threading, "Thread") as worker:
                self.assertIn("startup_timeout", hermis.commands.handle("retry"))
                worker.assert_not_called()
        self.assertEqual((self.directory / "state.json").read_bytes(), self.before)

    def test_diagnostics_are_read_only_and_connection_needs_real_client_evidence(self):
        with patch.object(hermis.ws_server, "overlay_connected", return_value=False), \
             patch.object(launcher.threading, "Thread") as worker:
            response = hermis.commands.handle("status")
            self.assertIn("Overlay startup:", response)
            worker.assert_not_called()
        with patch.object(hermis.ws_server, "overlay_connected", return_value=True), \
             patch.object(launcher.threading, "Thread") as worker:
            self.assertEqual(launcher.bootstrap_status()["phase"], "connected")
            self.assertIn("connected", hermis.commands.handle("retry"))
            worker.assert_not_called()
        self.assertEqual((self.directory / "state.json").read_bytes(), self.before)

    def test_thread_and_process_start_failures_release_the_reservation(self):
        with patch.object(launcher.threading, "Thread", side_effect=PermissionError("secret-token")):
            self.assertNotIn("secret-token", launcher.ensure_overlay_running())
        self.assertFalse(launcher._pipeline_busy)
        self.assertEqual(launcher.bootstrap_status()["error"], "worker_failed")
        with patch.object(launcher.subprocess, "Popen", side_effect=PermissionError("secret-token")):
            launcher._launch_pipeline("npm", self.overlay, self.directory, False)
        self.assertEqual(launcher.bootstrap_status()["error"], "launch_failed")
        self.assertNotIn("secret-token", str(launcher.bootstrap_status()))

    def test_retry_after_early_exit_reinstalls_without_changing_user_state(self):
        with patch.object(launcher, "needs_install", return_value=False):
            self.launch(process=Mock(poll=Mock(return_value=7)))
            self.assertEqual(launcher.bootstrap_status()["error"], "launch_exited")
            with patch.object(launcher.threading, "Thread") as worker:
                hermis.commands.handle("retry")
                self.assertTrue(worker.call_args.kwargs["args"][3])
                worker.return_value.start.assert_called_once()
        self.assertEqual((self.directory / "state.json").read_bytes(), self.before)

    def test_failed_install_can_retry_to_a_successful_start(self):
        self.launch(install_result=7)
        original = threading.Thread
        workers = []
        def make_worker(*args, **kwargs):
            worker = original(*args, **kwargs)
            workers.append(worker)
            return worker
        with patch.object(launcher.threading, "Thread", side_effect=make_worker), \
             patch.object(launcher.subprocess, "run", return_value=subprocess.CompletedProcess([], 0)), \
             patch.object(launcher.subprocess, "Popen", return_value=Mock(poll=Mock(return_value=None))) as start:
            hermis.commands.handle("retry")
            for worker in workers:
                worker.join(timeout=2)
                self.assertFalse(worker.is_alive())
            start.assert_called_once()
        self.assertEqual(launcher.bootstrap_status()["phase"], "starting")
        self.assertEqual((self.directory / "state.json").read_bytes(), self.before)

    def test_disabled_retry_and_invalid_arguments_do_not_launch(self):
        with patch.object(launcher.threading, "Thread") as worker:
            with patch.dict(os.environ, HERMIS_OVERLAY_AUTOSTART="0"):
                self.assertIn("disabled", hermis.commands.handle("retry"))
            self.assertIn("Usage:", hermis.commands.handle("retry extra"))
            worker.assert_not_called()
        self.assertEqual((self.directory / "state.json").read_bytes(), self.before)
