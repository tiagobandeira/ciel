"""Locks de caminho para escritas concorrentes entre subagentes."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from threading import Lock, RLock

_LOCKS: dict[str, RLock] = {}
_GUARD = Lock()


def _key(path: str) -> str:
    try:
        return str(Path(path).expanduser().resolve())
    except Exception:
        return str(path)


def _lock(path: str) -> RLock:
    key = _key(path)
    with _GUARD:
        return _LOCKS.setdefault(key, RLock())


@contextmanager
def lock_path(path: str):
    lock = _lock(path)
    lock.acquire()
    try:
        yield
    finally:
        lock.release()


@contextmanager
def lock_paths(paths):
    """Adquire vários locks em ordem determinística para evitar deadlock."""
    chaves = sorted({_key(str(p)) for p in paths if p})
    locks = [_lock(k) for k in chaves]
    for lock in locks:
        lock.acquire()
    try:
        yield
    finally:
        for lock in reversed(locks):
            lock.release()
