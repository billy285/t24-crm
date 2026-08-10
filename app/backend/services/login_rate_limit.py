"""Small in-process login rate limiter for the internal employee portal.

The CRM is deployed as a small internal service today.  This deliberately has
no external dependency, while still protecting both an account and a source IP
from repeated password guessing.  Multi-instance deployments should replace
this with a shared Redis-backed limiter.
"""

from __future__ import annotations

import hashlib
import os
import threading
import time
from collections import defaultdict, deque
from typing import Deque, Dict, Iterable


def _positive_int_env(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


class LoginRateLimiter:
    def __init__(self) -> None:
        self.max_failures = _positive_int_env("LOGIN_MAX_FAILURES", 5)
        self.window_seconds = _positive_int_env("LOGIN_FAILURE_WINDOW_SECONDS", 900)
        self.lock_seconds = _positive_int_env("LOGIN_LOCK_SECONDS", 900)
        self._failures: Dict[str, Deque[float]] = defaultdict(deque)
        self._blocked_until: Dict[str, float] = {}
        self._lock = threading.Lock()

    @staticmethod
    def account_key(email: str) -> str:
        normalized = (email or "").strip().lower()
        digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:24]
        return f"account:{digest}"

    @staticmethod
    def ip_key(client_ip: str) -> str:
        return f"ip:{(client_ip or 'unknown').strip()}"

    def keys(self, client_ip: str, email: str) -> tuple[str, str]:
        return self.ip_key(client_ip), self.account_key(email)

    def _prune(self, key: str, now: float) -> None:
        cutoff = now - self.window_seconds
        failures = self._failures[key]
        while failures and failures[0] < cutoff:
            failures.popleft()
        if not failures:
            self._failures.pop(key, None)

    def retry_after(self, keys: Iterable[str]) -> int:
        now = time.monotonic()
        with self._lock:
            retry = 0.0
            for key in keys:
                blocked_until = self._blocked_until.get(key, 0.0)
                if blocked_until <= now:
                    self._blocked_until.pop(key, None)
                    self._prune(key, now)
                    continue
                retry = max(retry, blocked_until - now)
            return max(0, int(retry + 0.999))

    def record_failure(self, keys: Iterable[str]) -> int:
        now = time.monotonic()
        with self._lock:
            retry = 0.0
            for key in keys:
                self._prune(key, now)
                failures = self._failures[key]
                failures.append(now)
                if len(failures) >= self.max_failures:
                    blocked_until = now + self.lock_seconds
                    self._blocked_until[key] = blocked_until
                    failures.clear()
                    retry = max(retry, blocked_until - now)
            return max(0, int(retry + 0.999))

    def clear(self, keys: Iterable[str]) -> None:
        with self._lock:
            for key in keys:
                self._failures.pop(key, None)
                self._blocked_until.pop(key, None)


login_rate_limiter = LoginRateLimiter()
