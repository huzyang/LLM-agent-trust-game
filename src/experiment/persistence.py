"""Atomic checkpoints and exclusive session ownership, using only the stdlib."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import signal
import tempfile


@contextmanager
def defer_interrupt():
    """Finish an in-memory/disk commit before honoring Ctrl+C."""
    previous = signal.getsignal(signal.SIGINT)
    interrupted = []
    signal.signal(signal.SIGINT, lambda *args: interrupted.append(True))
    try:
        yield
    finally:
        signal.signal(signal.SIGINT, previous)
        if interrupted:
            raise KeyboardInterrupt


def atomic_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


@contextmanager
def session_lock(directory):
    """OS releases the lock after a crash; no stale PID lock or concurrent resume."""
    path = Path(directory) / ".session.lock"
    with path.open("a+b") as handle:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        if os.name == "nt":
            import msvcrt
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                raise ValueError("This experiment is already running in another process") from None
        else:
            import fcntl
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                raise ValueError("This experiment is already running in another process") from None
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle, fcntl.LOCK_UN)
