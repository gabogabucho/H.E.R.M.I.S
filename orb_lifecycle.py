"""Best-effort process-local orb observations, never agent directives."""
from __future__ import annotations

import threading
from typing import Any

from . import ws_server

_lock = threading.Lock()
_turns: dict[tuple[str, str, str], set[str]] = {}
_listening: bool = False


def _current_state() -> str:
    """Resolve the highest-priority active orb state (caller holds ``_lock``)."""
    if any(_turns.values()):
        return "acting"
    if _turns:
        return "thinking"
    if _listening:
        return "listening"
    return "idle"


def reset() -> None:
    """Forget activity when the user explicitly changes autopilot mode."""
    global _listening
    with _lock:
        _turns.clear()
        _listening = False


def set_listening(active: bool) -> None:
    """Update microphone listening state and broadcast when autopilot is active."""
    global _listening
    with _lock:
        try:
            if not ws_server.load_state().get("autopilot"):
                _turns.clear()
                _listening = False
                return
            prev = _current_state()
            _listening = bool(active)
            state = _current_state()
            if state != prev:
                ws_server.broadcast({"type": "state", "orb": state})
        except Exception:
            return


def _observe(event: str, **kwargs: Any) -> None:
    # Serialize both reduction and delivery so parallel workers cannot reorder states.
    global _listening
    with _lock:
        try:
            if not ws_server.load_state().get("autopilot"):
                _turns.clear()
                _listening = False
                return
            session, task, turn = (kwargs.get(name) or "" for name in ("session_id", "task_id", "turn_id"))
            if not session or not turn:
                return
            key = (session, task, turn)
            call = kwargs.get("tool_call_id")
            if event == "turn_start":
                _listening = False
                _turns.setdefault(key, set())
            elif event == "tool_start" and call:
                _turns.setdefault(key, set()).add(call)
            elif event == "tool_end" and key in _turns and call in _turns[key]:
                _turns[key].remove(call)
            elif event == "turn_end" and key in _turns:
                del _turns[key]
            else:
                return  # Ignore incomplete, duplicate, or late terminal events.
            ws_server.broadcast({"type": "state", "orb": _current_state()})
        except Exception:
            # A missing overlay must never block or transform the agent's work.
            return


def pre_llm_call(**kwargs: Any) -> None:
    _observe("turn_start", **kwargs)


def pre_tool_call(**kwargs: Any) -> None:
    _observe("tool_start", **kwargs)


def post_tool_call(**kwargs: Any) -> None:
    _observe("tool_end", **kwargs)


def post_llm_call(**kwargs: Any) -> None:
    _observe("turn_end", **kwargs)
