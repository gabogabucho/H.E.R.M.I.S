"""Best-effort process-local orb observations, never agent directives."""
from __future__ import annotations

import threading

from . import ws_server

_lock = threading.Lock()
_turns: dict[tuple[str, str, str], set[str]] = {}


def reset() -> None:
    """Forget activity when the user explicitly changes autopilot mode."""
    with _lock:
        _turns.clear()


def _observe(event: str, **kwargs) -> None:
    # Serialize both reduction and delivery so parallel workers cannot reorder states.
    with _lock:
        try:
            if not ws_server.load_state().get("autopilot"):
                _turns.clear()
                return
            session, task, turn = (kwargs.get(name) or "" for name in ("session_id", "task_id", "turn_id"))
            if not session or not turn:
                return
            key = (session, task, turn)
            call = kwargs.get("tool_call_id")
            if event == "turn_start":
                _turns.setdefault(key, set())
            elif event == "tool_start" and call:
                _turns.setdefault(key, set()).add(call)
            elif event == "tool_end" and key in _turns and call in _turns[key]:
                _turns[key].remove(call)
            elif event == "turn_end" and key in _turns:
                del _turns[key]
            else:
                return  # Ignore incomplete, duplicate, or late terminal events.
            state = "acting" if any(_turns.values()) else "thinking" if _turns else "idle"
            ws_server.broadcast({"type": "state", "orb": state})
        except Exception:
            # A missing overlay must never block or transform the agent's work.
            return


def pre_llm_call(**kwargs) -> None:
    _observe("turn_start", **kwargs)


def pre_tool_call(**kwargs) -> None:
    _observe("tool_start", **kwargs)


def post_tool_call(**kwargs) -> None:
    _observe("tool_end", **kwargs)


def post_llm_call(**kwargs) -> None:
    _observe("turn_end", **kwargs)
