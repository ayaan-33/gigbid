"""Timeouts, bounded retries with backoff + jitter, and a circuit breaker (A6, C7)."""

from __future__ import annotations

import asyncio
import random
import time
from dataclasses import dataclass, field


@dataclass
class CircuitBreaker:
    """closed -> (N consecutive failures) -> open -> (cooldown) -> half_open -> success -> closed."""

    failure_threshold: int = 4
    cooldown_s: float = 20.0
    state: str = "closed"
    failures: int = 0
    opened_at: float = 0.0
    last_error: str | None = None
    history: list[tuple[float, str]] = field(default_factory=list)

    def allow(self) -> bool:
        if self.state == "open":
            if time.monotonic() - self.opened_at >= self.cooldown_s:
                self._set("half_open")
                return True
            return False
        return True

    def success(self) -> None:
        self.failures = 0
        if self.state != "closed":
            self._set("closed")

    def failure(self, err: str) -> None:
        self.failures += 1
        self.last_error = err
        if self.state == "half_open" or self.failures >= self.failure_threshold:
            self.opened_at = time.monotonic()
            self._set("open")

    def _set(self, s: str) -> None:
        self.state = s
        self.history.append((time.time(), s))
        self.history = self.history[-50:]

    def snapshot(self) -> dict:
        return {"state": self.state, "failures": self.failures, "last_error": self.last_error,
                "retry_in_s": max(0.0, self.cooldown_s - (time.monotonic() - self.opened_at)) if self.state == "open" else 0}


def backoff(attempt: int, base: float = 0.5, cap: float = 8.0) -> float:
    return min(cap, base * 2**attempt) * (0.5 + random.random() / 2)


async def sleep_backoff(attempt: int, retry_after: float | None = None) -> None:
    await asyncio.sleep(min(30.0, retry_after) if retry_after else backoff(attempt))
