"""In-process login-failure lockout.

5 consecutive failures within 15 minutes blocks further login attempts for
that username for the remainder of the window. Successful login clears the
counter.

Hub is assumed single-instance; if you horizontally scale we'd need to push
this into the DB.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass


_MAX_FAILS = 5
_WINDOW_SECS = 15 * 60


@dataclass
class _State:
    fails: int = 0
    locked_until: float = 0.0


class LoginLockout:
    def __init__(self) -> None:
        self._by_user: dict[str, _State] = {}
        self._lock = threading.Lock()

    def is_locked(self, username: str) -> bool:
        with self._lock:
            st = self._by_user.get(username.lower())
            return bool(st and st.locked_until > time.time())

    def record_failure(self, username: str) -> bool:
        """Tick the failure counter. Returns True if this attempt locked them out."""
        now = time.time()
        with self._lock:
            key = username.lower()
            st = self._by_user.get(key)
            if st is None or now > st.locked_until + _WINDOW_SECS:
                st = _State()
                self._by_user[key] = st
            st.fails += 1
            if st.fails >= _MAX_FAILS:
                st.locked_until = now + _WINDOW_SECS
                return True
            return False

    def clear(self, username: str) -> None:
        with self._lock:
            self._by_user.pop(username.lower(), None)
