"""Runtime compatibility through the launcher and user-facing diagnostics."""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = "hermis_runtime_test"
spec = importlib.util.spec_from_file_location(PACKAGE, ROOT / "__init__.py", submodule_search_locations=[str(ROOT)])
hermis = importlib.util.module_from_spec(spec)
sys.modules[PACKAGE] = hermis
spec.loader.exec_module(hermis)
launcher = hermis.overlay_launcher


class OverlayRuntimeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        for mock in (
            patch.dict(os.environ, HERMIS_OVERLAY_AUTOSTART="1"),
            patch.dict(hermis.ws_server._STATE, data_dir_override=self.tmp.name),
            patch.object(launcher, "_last_launch", None),
            patch.object(launcher, "_pipeline_busy", False),
            patch.object(launcher, "_bootstrap_guard", None),
            patch.object(launcher, "_overlay_dir", Path(self.tmp.name)),
        ):
            mock.start()
            self.addCleanup(mock.stop)
        self.addCleanup(launcher._release_bootstrap_guard)

    def test_incompatible_or_unverified_node_blocks_launch_without_state_changes(self):
        cases = (
            subprocess.CompletedProcess([], 0, "v20.19.0\n"),
            subprocess.CompletedProcess([], 0, "v22.11.9\n"),
            subprocess.CompletedProcess([], 0, "v22.12.0-rc.1\n"),
            subprocess.CompletedProcess([], 0, "not a version\n"),
            subprocess.CompletedProcess([], 1, "v22.12.0\n"),
            OSError("probe unavailable"),
            subprocess.TimeoutExpired("node", 5),
        )
        for result in cases:
            with self.subTest(result=result), \
                 patch.object(launcher.shutil, "which", side_effect=lambda name: f"/bin/{name}"), \
                 patch.object(launcher.subprocess, "run", side_effect=result if isinstance(result, Exception) else None,
                              return_value=result) as probe, \
                 patch.object(launcher.threading, "Thread") as thread:
                note = launcher.ensure_overlay_running()
                self.assertIn("22.12.0", note)
                thread.assert_not_called()
                self.assertIsNone(launcher._last_launch)
                self.assertFalse(launcher._pipeline_busy)
                self.assertEqual(list(Path(self.tmp.name).iterdir()), [])
                self.assertEqual(probe.call_args.args[0], ["/bin/node", "--version"])
                self.assertLessEqual(probe.call_args.kwargs["timeout"], 5)
                self.assertFalse(probe.call_args.kwargs.get("shell", False))

    def test_supported_versions_start_existing_pipeline(self):
        for version in ("v22.12.0", "v22.23.3", "v24.0.0"):
            with self.subTest(version=version), \
                 patch.object(launcher.shutil, "which", side_effect=lambda name: f"/bin/{name}"), \
                 patch.object(launcher.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, version)), \
                 patch.object(launcher.threading, "Thread") as thread, \
                 patch.object(launcher, "_recent_launch", return_value=False):
                launcher._last_launch = None
                launcher._pipeline_busy = False
                self.assertIn("overlay", launcher.ensure_overlay_running())
                self.assertEqual(thread.call_args.kwargs["target"], launcher._launch_pipeline)
                self.assertEqual(thread.call_args.kwargs["args"][0], "/bin/npm")
                thread.return_value.start.assert_called_once()

    def test_missing_executables_and_opt_out_do_not_probe_or_launch(self):
        for missing in ("node", "npm"):
            with self.subTest(missing=missing), \
                 patch.object(launcher.shutil, "which", side_effect=lambda name: None if name == missing else f"/bin/{name}"), \
                 patch.object(launcher.subprocess, "run") as probe, \
                 patch.object(launcher.threading, "Thread") as thread:
                self.assertIn("22.12.0", launcher.ensure_overlay_running())
                probe.assert_not_called()
                thread.assert_not_called()
        with patch.dict(os.environ, HERMIS_OVERLAY_AUTOSTART="0"), \
             patch.object(launcher.subprocess, "run") as probe:
            self.assertIsNone(launcher.ensure_overlay_running())
            probe.assert_not_called()

    def test_check_and_setup_share_the_runtime_requirement_and_remain_read_only(self):
        hermis.ws_server.save_state({"autopilot": False, "seq": 0, "surfaces": {}})
        state_path = Path(self.tmp.name) / "state.json"
        before = state_path.read_bytes()
        for version, status in (("v20.19.0", "warn"), ("v22.12.0", "ok")):
            with self.subTest(version=version), \
                 patch.object(launcher.shutil, "which", side_effect=lambda name: f"/bin/{name}"), \
                 patch.object(launcher.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, version)), \
                 patch.object(hermis.setup_checks, "_read_config", return_value={}), \
                 patch.object(Path, "is_dir", return_value=True), \
                 patch.object(launcher.threading, "Thread") as thread:
                response = hermis.commands.handle("check")
                self.assertIn("22.12.0", response)
                self.assertIn(version, response)
                overlay = next(item for item in hermis.setup_checks.run_checks() if item["id"] == "overlay")
                self.assertEqual(overlay["status"], status)
                thread.assert_not_called()
                self.assertEqual(state_path.read_bytes(), before)

    def test_package_manifests_declare_the_same_minimum(self):
        package = json.loads((ROOT / "overlay/package.json").read_text())
        lock = json.loads((ROOT / "overlay/package-lock.json").read_text())
        self.assertEqual(package.get("engines", {}).get("node"), ">=22.12.0")
        self.assertEqual(lock["packages"][""].get("engines"), package["engines"])
