"""Cooperative bootstrap exclusion across hosts sharing one installation."""
from __future__ import annotations

import importlib.util
import errno
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
REAL_POPEN = subprocess.Popen
PACKAGE = "hermis_lock_test"
spec = importlib.util.spec_from_file_location(PACKAGE, ROOT / "__init__.py", submodule_search_locations=[str(ROOT)])
hermis = importlib.util.module_from_spec(spec)
sys.modules[PACKAGE] = hermis
spec.loader.exec_module(hermis)
launcher = hermis.overlay_launcher

# A separate interpreter simulates a second Hermes host, without npm/Electron.
HOST = r'''
import importlib.util, json, os, sys
from pathlib import Path
from unittest.mock import Mock, patch
root, overlay, data = map(Path, sys.argv[1:4])
spec = importlib.util.spec_from_file_location("hermis_host", root / "__init__.py", submodule_search_locations=[str(root)])
app = importlib.util.module_from_spec(spec); sys.modules[spec.name] = app; spec.loader.exec_module(app)
app.ws_server._STATE["data_dir_override"] = str(data)
os.environ["HERMIS_OVERLAY_AUTOSTART"] = "1"
with patch.object(app.overlay_launcher, "_overlay_dir", overlay), patch.object(app.overlay_launcher, "runtime_status", return_value={"npm":"npm", "error":None}), patch.object(app.overlay_launcher.threading, "Thread") as worker:
    note = app.overlay_launcher.ensure_overlay_running(retry=True)
    print(json.dumps({"launched":worker.return_value.start.called,"phase":app.overlay_launcher.bootstrap_status()["phase"],"note":note}), flush=True)
    if sys.argv[4] == "hold": sys.stdin.readline()
'''


class BootstrapLockTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name)
        self.overlay = self.directory / "overlay"
        self.overlay.mkdir()
        override = patch.dict(hermis.ws_server._STATE, data_dir_override=self.tmp.name)
        override.start()
        self.addCleanup(override.stop)
        hermis.ws_server.save_state({"autopilot": False, "seq": 0, "surfaces": {}})

    def host(self, name, hold=False):
        return REAL_POPEN([sys.executable, "-c", HOST, str(ROOT), str(self.overlay),
                                 str(self.directory / name), "hold" if hold else "once"],
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})

    def test_other_host_cannot_launch_until_holder_exits_without_deleting_lock_file(self):
        holder = self.host("one", hold=True)
        try:
            first = json.loads(holder.stdout.readline())
            self.assertTrue(first["launched"])
            contender = self.host("two")
            stdout, stderr = contender.communicate(timeout=5)
            self.assertEqual(contender.returncode, 0, stderr)
            self.assertEqual(json.loads(stdout)["phase"], "busy")
            self.assertFalse(json.loads(stdout)["launched"])
            self.assertFalse((self.directory / "two" / "overlay.launch").exists())
        finally:
            holder.communicate(input="release\n", timeout=5)
        lock_file = self.overlay / ".hermis-bootstrap.lock"
        self.assertTrue(lock_file.exists())
        inode = lock_file.stat().st_ino
        successor = self.host("three")
        stdout, stderr = successor.communicate(timeout=5)
        self.assertEqual(successor.returncode, 0, stderr)
        self.assertTrue(json.loads(stdout)["launched"])
        self.assertEqual(lock_file.stat().st_ino, inode)

    def test_diagnostics_and_opt_out_do_not_create_a_lock(self):
        with patch.object(launcher, "_overlay_dir", self.overlay), \
             patch.object(hermis.ws_server, "overlay_connected", return_value=False), \
             patch.dict(os.environ, HERMIS_OVERLAY_AUTOSTART="0"):
            self.assertIn("disabled", hermis.commands.handle("retry"))
            hermis.commands.handle("status")
        self.assertEqual(list(self.overlay.iterdir()), [])

    def test_lock_open_failure_is_sanitized_and_prevents_worker_start(self):
        with patch.object(launcher, "_overlay_dir", self.overlay), \
             patch.object(hermis.ws_server, "overlay_connected", return_value=False), \
             patch.dict(os.environ, HERMIS_OVERLAY_AUTOSTART="1"), \
             patch.object(launcher, "runtime_status", return_value={"npm": "npm", "error": None}), \
             patch.object(launcher.bootstrap_lock, "acquire", side_effect=PermissionError("secret-token")), \
             patch.object(launcher.threading, "Thread") as worker:
            response = hermis.commands.handle("retry")
            self.assertIn("lock_failed", response)
            self.assertNotIn("secret-token", response)
            worker.assert_not_called()

    def test_windows_lock_contract_uses_nonblocking_byte_zero_and_closes(self):
        backend = Mock(LK_NBLCK=2, LK_UNLCK=0)
        with patch.object(launcher.bootstrap_lock.sys, "platform", "win32"), \
             patch.dict(sys.modules, msvcrt=backend):
            handle = launcher.bootstrap_lock.acquire(self.overlay)
            self.assertIsNotNone(handle)
            backend.locking.assert_called_once_with(handle.fileno(), 2, 1)
            self.assertEqual(handle.tell(), 0)
            descriptor = handle.fileno()
            launcher.bootstrap_lock.release(handle)
            backend.locking.assert_called_with(descriptor, 0, 1)
            self.assertTrue(handle.closed)

    def test_windows_contention_and_unexpected_error_close_the_handle(self):
        backend = Mock(LK_NBLCK=2)
        for number in (errno.EACCES, errno.EIO):
            handle = Mock()
            backend.locking.side_effect = OSError(number, "secret-token")
            with self.subTest(errno=number), \
                 patch.object(launcher.bootstrap_lock.sys, "platform", "win32"), \
                 patch.dict(sys.modules, msvcrt=backend), \
                 patch.object(Path, "open", return_value=handle):
                if number == errno.EACCES:
                    self.assertIsNone(launcher.bootstrap_lock.acquire(self.overlay))
                else:
                    with self.assertRaises(OSError):
                        launcher.bootstrap_lock.acquire(self.overlay)
                handle.close.assert_called_once()

    def test_native_lock_is_held_during_install_and_until_wrapper_exits(self):
        installing, installed, launched, exited = (threading.Event() for _ in range(4))
        original_thread = threading.Thread
        workers = []

        def make_worker(*args, **kwargs):
            worker = original_thread(*args, **kwargs)
            if kwargs.get("name") == "hermis-overlay-launch":
                workers.append(worker)
            return worker

        def install(*args, **kwargs):
            installing.set()
            installed.wait(timeout=5)
            return subprocess.CompletedProcess([], 0)

        def wait():
            launched.set()
            exited.wait(timeout=5)
            return 0

        process = Mock(wait=Mock(side_effect=wait), poll=Mock(side_effect=lambda: 0 if exited.is_set() else None))
        with patch.object(launcher, "_overlay_dir", self.overlay), \
             patch.object(launcher, "_bootstrap_guard", None), \
             patch.object(launcher, "_launch_process", None), \
             patch.object(launcher, "_last_launch", None), \
             patch.object(launcher, "_pipeline_busy", False), \
             patch.object(launcher, "_bootstrap", {"phase": "idle", "error": None, "started_at": 0}), \
             patch.object(launcher, "runtime_status", return_value={"npm": "npm", "error": None}), \
             patch.object(hermis.ws_server, "data_dir", return_value=self.directory / "owner"), \
             patch.object(hermis.ws_server, "overlay_connected", return_value=False), \
             patch.dict(os.environ, HERMIS_OVERLAY_AUTOSTART="1"), \
             patch.object(launcher.threading, "Thread", side_effect=make_worker), \
             patch.object(launcher.subprocess, "run", side_effect=install), \
             patch.object(launcher.subprocess, "Popen", return_value=process):
            try:
                launcher.ensure_overlay_running()
                self.assertTrue(installing.wait(timeout=2))
                for phase in ("install", "wrapper"):
                    contender = self.host(phase)
                    stdout, stderr = contender.communicate(timeout=5)
                    self.assertEqual(contender.returncode, 0, stderr)
                    self.assertEqual(json.loads(stdout)["phase"], "busy")
                    installed.set()
                    self.assertTrue(launched.wait(timeout=2))
            finally:
                installed.set()
                exited.set()
                for worker in workers:
                    worker.join(timeout=3)
                    self.assertFalse(worker.is_alive())
                launcher._release_bootstrap_guard()
        successor = self.host("successor")
        stdout, stderr = successor.communicate(timeout=5)
        self.assertEqual(successor.returncode, 0, stderr)
        self.assertTrue(json.loads(stdout)["launched"])
