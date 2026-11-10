"""Nonblocking native lock shared by hosts using one overlay installation."""
from __future__ import annotations

import errno
import sys
from pathlib import Path
from typing import BinaryIO

LOCK_NAME = ".hermis-bootstrap.lock"


def acquire(directory: Path) -> BinaryIO | None:
    """Keep the returned handle open for ownership; None means contention.

    Never unlink the identity file: replacing it would split the lock domain.
    Opening failure is an error, not evidence that another host owns the lock.
    """
    handle = (directory / LOCK_NAME).open("a+b")
    try:
        handle.seek(0)
        if sys.platform == "win32":
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        handle.close()
        if exc.errno in (errno.EACCES, errno.EAGAIN):
            return None
        raise
    except BaseException:
        handle.close()
        raise
    return handle


def release(handle: BinaryIO) -> None:
    try:
        handle.seek(0)
        if sys.platform == "win32":
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle, fcntl.LOCK_UN)
    finally:
        handle.close()
