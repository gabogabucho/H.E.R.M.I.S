"""Lifecycle observers must never modify agent results or persisted data."""
import asyncio
import json
import shutil
import subprocess
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

    def test_ws_server_voice_status_updates_orb_respecting_priority(self):
        class FakeConn:
            def __init__(self, incoming):
                self._incoming = list(incoming)
                self.sent = []
                self.closed = None

            async def recv(self):
                return self._incoming.pop(0)

            async def send(self, text):
                self.sent.append(json.loads(text))

            async def close(self, code=1000, reason=""):
                self.closed = (code, reason)

            def __aiter__(self):
                return self

            async def __anext__(self):
                if not self._incoming:
                    raise StopAsyncIteration
                return self._incoming.pop(0)

        conn = FakeConn([
            json.dumps({"type": "hello", "token": "secret-token"}),
            "not-json-ignored",
            json.dumps({"type": "voice.status", "state": "listening"}),
            json.dumps({"type": "voice.status", "state": "idle"}),
        ])
        with patch.dict(hermis.ws_server._STATE, token="secret-token"), \
             patch.object(hermis.ws_server, "broadcast", return_value=1) as send:
            asyncio.run(hermis.ws_server._handler(conn))
            self.assertEqual([c.args[0] for c in send.call_args_list], [
                {"type": "state", "orb": "listening"},
                {"type": "state", "orb": "idle"},
            ])
            send.reset_mock()
            self.call("pre_llm_call")
            self.assertEqual(send.call_args.args[0], {"type": "state", "orb": "thinking"})
            send.reset_mock()
            hermis.ws_server._handle_client_message(
                json.dumps({"type": "voice.status", "state": "listening"})
            )
            send.assert_not_called()

    def test_ws_server_wake_detected_broadcasts_intro_and_sets_listening(self):
        with patch.object(hermis.ws_server, "broadcast", return_value=1) as send:
            hermis.ws_server._handle_client_message(
                json.dumps({"type": "wake.detected", "phrase": "hey hermes"})
            )
            self.assertEqual([c.args[0] for c in send.call_args_list], [
                {"type": "state", "orb": "listening"},
                {"type": "intro", "phrase": "hey hermes"},
            ])

    @unittest.skipUnless(shutil.which("node"), "Node.js is required for gateway_client tests")
    def test_gateway_client_node_parsing_discovery_and_ws(self):
        gateway_client_path = (test_commands.ROOT / "overlay" / "gateway_client.js").as_posix()
        script = f"""
const assert = require('assert');
const net = require('net');
const os = require('os');
const path = require('path');
const {{ WebSocketServer }} = require('ws');
const gw = require({json.dumps(gateway_client_path)});

(async () => {{
  const raw = [
    JSON.stringify({{
      jsonrpc: '2.0',
      method: 'event',
      params: {{ type: 'voice.status', session_id: 's1', payload: {{ state: 'listening' }} }}
    }}),
    JSON.stringify({{
      jsonrpc: '2.0',
      method: 'event',
      params: {{ type: 'voice.status', session_id: 's1', payload: {{ state: 'transcribing' }} }}
    }}),
    JSON.stringify({{
      jsonrpc: '2.0',
      method: 'event',
      params: {{ type: 'wake.detected', session_id: 's1', payload: {{ phrase: 'hey hermes', start_new_session: true }} }}
    }}),
    JSON.stringify({{ event: 'voice.status', payload: {{ state: 'idle' }} }})
  ].join('\\n');

  const frames = gw.parseGatewayFrames(raw);
  assert.strictEqual(frames.length, 4);
  assert.deepStrictEqual(frames[0].pluginMessages, [{{ type: 'voice.status', state: 'listening', listening: true }}]);
  assert.deepStrictEqual(frames[0].rendererMessages, [{{ type: 'state', orb: 'listening' }}]);
  assert.deepStrictEqual(frames[1].pluginMessages, [{{ type: 'voice.status', state: 'transcribing', listening: false }}]);
  assert.deepStrictEqual(frames[1].rendererMessages, [{{ type: 'state', orb: 'idle' }}]);
  assert.deepStrictEqual(frames[2].pluginMessages, [
    {{ type: 'wake.detected', phrase: 'hey hermes', start_new_session: true }}
  ]);
  assert.deepStrictEqual(frames[2].rendererMessages, [
    {{ type: 'intro', phrase: 'hey hermes', start_new_session: true }},
    {{ type: 'state', orb: 'listening' }}
  ]);
  assert.deepStrictEqual(frames[3].pluginMessages, [{{ type: 'voice.status', state: 'idle', listening: false }}]);
  assert.deepStrictEqual(frames[3].rendererMessages, [{{ type: 'state', orb: 'idle' }}]);

  const wss = new WebSocketServer({{ host: '127.0.0.1', port: 0 }});
  await new Promise((r) => wss.once('listening', r));
  const wsPort = wss.address().port;

  const testHome = path.join(os.tmpdir(), 'hermis-gw-test-' + process.pid + '-' + Date.now());
  const pipePath = gw.controlSocketPathForHome(testHome);
  const controlServer = net.createServer((sock) => {{
    let buf = '';
    sock.on('error', () => {{}});
    sock.on('data', (chunk) => {{
      buf += chunk.toString('utf8');
      const idx = buf.indexOf('\\n');
      if (idx !== -1) {{
        const req = JSON.parse(buf.slice(0, idx));
        if (req.verb === 'identify') {{
          sock.end(JSON.stringify({{
            ok: true,
            result: {{
              api_origin: `http://127.0.0.1:${{wsPort}}`,
              instance_id: 'inst-1',
              served_profiles: [{{ profile_id: 'prof-1' }}]
            }}
          }}) + '\\n');
        }} else if (req.verb === 'session-ticket') {{
          sock.end(JSON.stringify({{
            ok: true,
            result: {{ ticket: 'tok-xyz' }}
          }}) + '\\n');
        }}
      }}
    }});
  }});
  await new Promise((r) => controlServer.listen(pipePath, r));

  const target = await gw.resolveGatewayTarget({{ hermesHome: testHome, env: {{}}, argv: [] }});
  assert.strictEqual(target.url, `ws://127.0.0.1:${{wsPort}}/api/ws`);
  assert.deepStrictEqual(target.protocols, ['hermes-gateway-v1', 'hermes-gateway-ticket.tok-xyz']);

  // Direct handleMessage check when sendToPlugin returns true (plugin WS connected)
  const connectedPlugin = [];
  const connectedRenderer = [];
  const connectedClient = gw.createGatewayClient({{
    sendToPlugin: (m) => {{ connectedPlugin.push(m); return true; }},
    forwardToRenderer: (m) => connectedRenderer.push(m)
  }});
  connectedClient.handleMessage(raw);
  assert.strictEqual(connectedPlugin.length, 4);
  assert.strictEqual(connectedRenderer.length, 0);

  // Fallback check when sendToPlugin returns false (plugin WS disconnected)
  const receivedPlugin = [];
  const receivedRenderer = [];
  let clientDone;
  const donePromise = new Promise((r) => {{ clientDone = r; }});

  wss.on('connection', (ws) => {{
    ws.send(
      JSON.stringify({{ jsonrpc: '2.0', method: 'event', params: {{ type: 'wake.detected', payload: {{ phrase: 'hey hermes' }} }} }}) +
      '\\n' +
      JSON.stringify({{ jsonrpc: '2.0', method: 'event', params: {{ type: 'voice.status', payload: {{ state: 'speaking' }} }} }})
    );
  }});

  const client = gw.createGatewayClient({{
    hermesHome: testHome,
    env: {{}},
    argv: [],
    sendToPlugin: (m) => {{ receivedPlugin.push(m); return false; }},
    forwardToRenderer: (m) => {{
      receivedRenderer.push(m);
      if (receivedRenderer.length >= 3) clientDone();
    }}
  }});
  client.start();
  await donePromise;
  client.stop();
  controlServer.close();
  wss.close();

  assert.strictEqual(receivedPlugin[0].type, 'wake.detected');
  assert.strictEqual(receivedRenderer[0].type, 'intro');
  assert.strictEqual(receivedRenderer[2].orb, 'speaking');
}})().catch((err) => {{
  console.error(err);
  process.exit(1);
}});
"""
        proc = subprocess.run(
            ["node", "-e", script],
            cwd=str(test_commands.ROOT / "overlay"),
            capture_output=True,
            text=True,
            timeout=15,
        )
        self.assertEqual(proc.returncode, 0, msg=proc.stderr or proc.stdout)

    def test_orb_listening_transitions_to_thinking_and_idle(self):
        with patch.object(hermis.ws_server, "broadcast", return_value=1) as send:
            hermis.orb_lifecycle.set_listening(True)
            self.call("pre_llm_call")
            self.call("post_llm_call")
            self.assertEqual([c.args[0] for c in send.call_args_list], [
                {"type": "state", "orb": state} for state in ("listening", "thinking", "idle")
            ])
