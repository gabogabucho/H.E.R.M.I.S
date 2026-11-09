"""Best-effort process-local orb observations, never agent directives."""
from __future__ import annotations

import functools
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


def patch_audio_recorder_class(cls: Any) -> Any:
    """Wrap an AudioRecorder class idempotently to report listening state."""
    if cls is None or getattr(cls, "_hermis_wrapped", False):
        return cls
    orig_start = getattr(cls, "start", None)
    orig_stop = getattr(cls, "stop", None)
    orig_cancel = getattr(cls, "cancel", None)

    if callable(orig_start):
        @functools.wraps(orig_start)
        def _start(self: Any, *args: Any, **kwargs: Any) -> Any:
            if "on_silence_stop" in kwargs and callable(kwargs["on_silence_stop"]):
                orig_cb = kwargs["on_silence_stop"]

                def _wrapped_cb(*cb_args: Any, **cb_kwargs: Any) -> Any:
                    set_listening(False)
                    return orig_cb(*cb_args, **cb_kwargs)

                kwargs = dict(kwargs, on_silence_stop=_wrapped_cb)
            elif args and callable(args[0]):
                orig_cb = args[0]

                def _wrapped_cb(*cb_args: Any, **cb_kwargs: Any) -> Any:
                    set_listening(False)
                    return orig_cb(*cb_args, **cb_kwargs)

                args = (_wrapped_cb, *args[1:])
            res = orig_start(self, *args, **kwargs)
            if res is not False and getattr(self, "is_recording", getattr(self, "_recording", True)):
                set_listening(True)
            return res

        setattr(cls, "start", _start)

    if callable(orig_stop):
        @functools.wraps(orig_stop)
        def _stop(self: Any, *args: Any, **kwargs: Any) -> Any:
            set_listening(False)
            return orig_stop(self, *args, **kwargs)

        setattr(cls, "stop", _stop)

    if callable(orig_cancel):
        @functools.wraps(orig_cancel)
        def _cancel(self: Any, *args: Any, **kwargs: Any) -> Any:
            set_listening(False)
            return orig_cancel(self, *args, **kwargs)

        setattr(cls, "cancel", _cancel)

    setattr(cls, "_hermis_wrapped", True)
    return cls


def patch_voice_module(mod: Any) -> Any:
    """Wrap ``start_continuous`` on a voice module idempotently to observe ``on_status``."""
    if mod is None:
        return mod
    orig_start_continuous = getattr(mod, "start_continuous", None)
    if not callable(orig_start_continuous) or getattr(orig_start_continuous, "_hermis_wrapped", False):
        return mod

    @functools.wraps(orig_start_continuous)
    def _start_continuous(*args: Any, **kwargs: Any) -> Any:
        orig_on_status = kwargs.get("on_status") if "on_status" in kwargs else (args[1] if len(args) > 1 else None)

        def _wrapped_on_status(status: str, *s_args: Any, **s_kwargs: Any) -> Any:
            if status == "listening":
                set_listening(True)
            elif status in ("transcribing", "idle"):
                set_listening(False)
            if callable(orig_on_status):
                return orig_on_status(status, *s_args, **s_kwargs)
            return None

        if len(args) > 1 and "on_status" not in kwargs:
            args = (args[0], _wrapped_on_status, *args[2:])
        else:
            kwargs = dict(kwargs, on_status=_wrapped_on_status)

        res = orig_start_continuous(*args, **kwargs)
        if res is False:
            set_listening(False)
        return res

    setattr(_start_continuous, "_hermis_wrapped", True)
    setattr(mod, "start_continuous", _start_continuous)
    return mod


def patch_wake_detector_class(cls: Any) -> Any:
    """Wrap ``WakeWordDetector._fire`` idempotently so wake detection sets listening."""
    if cls is None or getattr(cls, "_hermis_wrapped", False):
        return cls
    orig_fire = getattr(cls, "_fire", None)
    if callable(orig_fire):
        @functools.wraps(orig_fire)
        def _fire(self: Any, *args: Any, **kwargs: Any) -> Any:
            set_listening(True)
            return orig_fire(self, *args, **kwargs)

        setattr(cls, "_fire", _fire)
    setattr(cls, "_hermis_wrapped", True)
    return cls


def install_voice_hooks() -> None:
    """Install best-effort in-process voice and wake-word observers."""
    try:
        from tools import voice_mode  # type: ignore[import-not-found]
        patch_audio_recorder_class(getattr(voice_mode, "AudioRecorder", None))
    except Exception:
        pass
    try:
        from hermes_cli import voice  # type: ignore[import-not-found]
        patch_voice_module(voice)
    except Exception:
        pass
    try:
        from tools import wake_word  # type: ignore[import-not-found]
        patch_wake_detector_class(getattr(wake_word, "WakeWordDetector", None))
    except Exception:
        pass
