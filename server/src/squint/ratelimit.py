"""Sliding-window counters keyed by client."""

from __future__ import annotations

import math
import threading
import time
from collections import deque


class SlidingWindowLimiter:
    def __init__(self, limit: int, window_s: float, clock=time.monotonic):
        self.limit = limit
        self.window = window_s
        self._clock = clock
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def _prune(self, key: str, now: float) -> deque[float]:
        q = self._hits.get(key)
        if q is None:
            return deque()
        while q and now - q[0] >= self.window:
            q.popleft()
        if not q:
            self._hits.pop(key, None)
        return q

    def retry_after(self, key: str) -> int:
        """0 when another hit is allowed now, else whole seconds until it will be."""
        with self._lock:
            now = self._clock()
            q = self._prune(key, now)
            if len(q) < self.limit:
                return 0
            return max(1, math.ceil(self.window - (now - q[0])))

    def hit(self, key: str) -> None:
        with self._lock:
            now = self._clock()
            self._prune(key, now)
            self._hits.setdefault(key, deque()).append(now)

    def reset(self, key: str) -> None:
        with self._lock:
            self._hits.pop(key, None)

    def sweep(self) -> None:
        with self._lock:
            now = self._clock()
            for key in list(self._hits):
                self._prune(key, now)
