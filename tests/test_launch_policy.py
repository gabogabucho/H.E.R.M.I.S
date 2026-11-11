"""Política de aprobación de launch_app, el hook pre_tool_call y minimal_env."""
from __future__ import annotations

import json
import os
import unittest
from unittest.mock import patch

import test_commands

hermis = test_commands.hermis
launch_policy = hermis.launch_policy
IDENTITY = {"session_id": "session", "task_id": "task", "turn_id": "turn"}


class LaunchPolicyTest(unittest.TestCase):
    def decide(self, args):
        return launch_policy.launch_policy(args)

    def test_shells_interpreters_and_script_hosts_are_blocked(self):
        cases = [
            {"app": "cmd", "args": ["/c", "dir"]},
            {"app": "cmd.exe"},
            {"app": "powershell", "args": ["-Command", "Get-Process"]},
            {"app": "pwsh"},
            {"app": "wsl", "args": ["ls"]},
            {"app": "python", "args": ["-c", "print(1)"]},
            {"app": "node", "args": ["-e", "1"]},
        ]
        for args in cases:
            with self.subTest(app=args["app"]):
                res = self.decide(args)
                self.assertEqual(res["action"], "block")
                self.assertTrue(res["message"])

    def test_blocked_even_when_resolved_executable_is_a_shell(self):
        res = launch_policy.reject_reason(
            "otra-cosa", r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
        )
        self.assertIsNotNone(res)
        self.assertIn("shells", res)

    def test_paths_and_urls_as_app_are_blocked(self):
        for app in (
            r"C:\Windows\System32\notepad.exe",
            r"C:notepad.exe",
            "tools/evil.exe",
            "./evil.sh",
            "https://evil.example/x",
        ):
            with self.subTest(app=app):
                res = self.decide({"app": app})
                self.assertEqual(res["action"], "block")
                self.assertIn("nombre", res["message"])

    def test_allowlist_app_without_args_does_not_ask(self):
        self.assertIsNone(self.decide({"app": "calculadora"}))
        self.assertIsNone(self.decide({"app": "bloc de notas"}))
        self.assertIsNone(self.decide({"app": "spotify", "args": []}))
        self.assertIsNone(self.decide({"app": "notepad", "args": [""]}))

    def test_browser_with_one_http_url_does_not_ask(self):
        self.assertIsNone(self.decide({"app": "chrome", "args": ["https://example.com"]}))
        self.assertIsNone(self.decide({"app": "Microsoft Edge", "args": ["http://example.com"]}))

    def test_browser_with_javascript_url_asks_for_approval(self):
        res = self.decide({"app": "chrome", "args": ["javascript:alert(1)"]})
        self.assertEqual(res["action"], "approve")

    def test_browser_with_url_without_netloc_asks_for_approval(self):
        res = self.decide({"app": "firefox", "args": ["https://"]})
        self.assertEqual(res["action"], "approve")

    def test_browser_with_two_args_asks_for_approval(self):
        res = self.decide({"app": "edge", "args": ["--new-window", "https://example.com"]})
        self.assertEqual(res["action"], "approve")

    def test_any_args_ask_for_approval(self):
        for args in ({"app": "notepad", "args": [r"C:\notas\notitas.txt"]},
                     {"app": "excel", "args": ["libro.xlsx"]},
                     {"app": "explorer", "args": [r"C:\Windows"]}):
            with self.subTest(args=args):
                res = self.decide(args)
                self.assertEqual(res["action"], "approve")
                self.assertTrue(res["message"].startswith("H.E.R.M.I.S quiere abrir"))

    def test_unknown_app_asks_for_approval(self):
        res = self.decide({"app": "whatsapp"})
        self.assertEqual(res["action"], "approve")
        res = self.decide({"app": "juego-xyz", "args": ["--fullscreen"]})
        self.assertEqual(res["action"], "approve")

    def test_invalid_args_are_ignored_by_the_policy(self):
        self.assertIsNone(self.decide({"app": "  "}))
        self.assertIsNone(self.decide({}))
        self.assertIsNone(self.decide(None))
        self.assertIsNone(self.decide({"app": 42}))


class PreToolCallHookTest(unittest.TestCase):
    def setUp(self):
        test_commands.CommandTest.setUp(self)

    def test_hook_blocks_launch_app_shells(self):
        with patch.object(hermis.ws_server, "broadcast", return_value=1):
            res = hermis.orb_lifecycle.pre_tool_call(
                tool_name="launch_app", args={"app": "powershell", "args": ["-Command", "whoami"]},
                **IDENTITY, tool_call_id="a",
            )
        self.assertEqual(res["action"], "block")

    def test_hook_asks_approval_for_unknown_apps_and_ignores_other_tools(self):
        with patch.object(hermis.ws_server, "broadcast", return_value=1) as send:
            res = hermis.orb_lifecycle.pre_tool_call(
                tool_name="launch_app", args={"app": "whatsapp"},
                **IDENTITY, tool_call_id="a",
            )
            self.assertEqual(res["action"], "approve")
            other = hermis.orb_lifecycle.pre_tool_call(
                tool_name="render_surface", args={"surface": "notification"},
                **IDENTITY, tool_call_id="b",
            )
            self.assertIsNone(other)
            self.assertEqual(send.call_args.args[0], {"type": "state", "orb": "acting"})

    def test_tool_itself_rejects_shells_and_paths_without_the_hook(self):
        # Defensa en profundidad: la tool rechaza por su cuenta, sin hook de por medio.
        with patch.object(hermis.tools.win32_windows, "is_windows", lambda: True), \
             patch.object(hermis.tools.win32_windows.shutil, "which",
                          lambda exe: f"C:\\Windows\\System32\\{exe}"):
            out = json.loads(hermis.tools.launch_app({"app": "cmd", "args": ["/c", "dir"]}))
            self.assertFalse(out["ok"])
            self.assertEqual(out["error"], "blocked_app")
            out = json.loads(hermis.tools.launch_app({"app": r"C:\Windows\notepad.exe"}))
            self.assertFalse(out["ok"])
            self.assertEqual(out["error"], "blocked_app")


class MinimalEnvTest(unittest.TestCase):
    def test_keeps_path_and_drops_provider_keys(self):
        fake = {
            "PATH": r"C:\Windows\System32",
            "LOCALAPPDATA": r"C:\Users\g\AppData\Local",
            "OPENAI_API_KEY": "sk-openai",
            "ANTHROPIC_API_KEY": "sk-anthropic",
            "ELEVENLABS_API_KEY": "sk-eleven",
        }
        with patch.dict(os.environ, fake, clear=True):
            env = hermis.child_env.minimal_env()
        self.assertEqual(env.get("PATH"), fake["PATH"])
        self.assertEqual(env.get("LOCALAPPDATA"), fake["LOCALAPPDATA"])
        for key in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "ELEVENLABS_API_KEY"):
            self.assertNotIn(key, env)

    def test_matching_is_case_insensitive_and_extra_extends(self):
        fake = {"path": r"C:\Windows", "Http_Proxy": "http://proxy:8080", "SECRET": "x"}
        with patch.dict(os.environ, fake, clear=True):
            env = hermis.child_env.minimal_env()
            # En Windows os.environ normaliza las claves a mayúsculas: se compara igual.
            self.assertEqual({k.upper(): v for k, v in env.items()},
                             {"PATH": fake["path"], "HTTP_PROXY": fake["Http_Proxy"]})
            env_extra = hermis.child_env.minimal_env(extra=["secret"])
            self.assertEqual(env_extra.get("SECRET"), "x")

    def test_gateway_tokens_only_reach_the_overlay(self):
        fake = {"PATH": r"C:\Windows", "HERMES_GATEWAY_TOKEN": "tok", "HERMES_API_TOKEN": "tok2"}
        with patch.dict(os.environ, fake, clear=True):
            base = {k.upper() for k in hermis.child_env.minimal_env()}
            overlay = {k.upper() for k in hermis.child_env.minimal_env(hermis.child_env.OVERLAY_GATEWAY_VARS)}
        self.assertNotIn("HERMES_GATEWAY_TOKEN", base)
        self.assertNotIn("HERMES_API_TOKEN", base)
        self.assertIn("HERMES_GATEWAY_TOKEN", overlay)


class StartAppRejectTest(unittest.TestCase):
    def test_console_start_apps_are_rejected(self):
        cases = [
            ("Windows PowerShell", r"{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell1.0\powershell.exe"),
            ("Terminal", "Microsoft.WindowsTerminal_8wekyb3d8bbwe!App"),
            ("Símbolo del sistema", r"{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\cmd.exe"),
            ("Ubuntu", "CanonicalGroupLimited.Ubuntu_79rhkp1fndgsc!ubuntu"),
            ("Python 3.12", r"{6D809377-6AF0-444B-8957-A3773F02200E}\Python312\python.exe"),
        ]
        for name, aumid in cases:
            with self.subTest(name=name):
                self.assertIsNotNone(launch_policy.reject_start_app(name, aumid))

    def test_regular_store_apps_are_allowed(self):
        for name, aumid in (("Spotify", "SpotifyAB.SpotifyMusic_zpdnekdrzrea0!Spotify"),
                            ("WhatsApp", "5319275A.WhatsAppDesktop_cv1g1gvanyjgm!App"),
                            ("Calculadora", "Microsoft.WindowsCalculator_8wekyb3d8bbwe!App")):
            with self.subTest(name=name):
                self.assertIsNone(launch_policy.reject_start_app(name, aumid))


if __name__ == "__main__":
    unittest.main()
