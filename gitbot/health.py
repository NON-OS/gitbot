"""A small liveness registry the long-running tasks report into.

Each background task (the pollers, the command loop) marks a successful cycle
or a failure here. The health endpoint reads it so an operator, or a monitor,
can tell a wedged poller from a quiet one: a task that has not completed a cycle
in several of its own intervals is stale, and stale is what /healthz fails on.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

# A task is stale once it has missed this many of its own intervals.
STALE_INTERVALS = 3
# Alert the admin chat once a task has failed this many cycles in a row.
ALERT_AFTER = 3


@dataclass
class Component:
    name: str
    interval: float
    last_ok: float = 0.0
    fails: int = 0
    last_error: str = ""
    started: float = field(default_factory=time.time)


class Health:
    def __init__(self, started_at: float | None = None):
        self.started_at = started_at or time.time()
        self._components: dict[str, Component] = {}

    def register(self, name: str, interval: float) -> None:
        self._components.setdefault(name, Component(name, interval))

    def ok(self, name: str) -> None:
        c = self._components.get(name)
        if c is None:
            return
        c.last_ok = time.time()
        c.fails = 0
        c.last_error = ""

    def fail(self, name: str, error: str) -> int:
        """Record a failed cycle and return the consecutive failure count."""
        c = self._components.get(name)
        if c is None:
            return 0
        c.fails += 1
        c.last_error = error
        return c.fails

    def _stale(self, c: Component, now: float) -> bool:
        # Give a task a grace period of one interval after start before its
        # missing first cycle counts as stale.
        deadline = c.interval * STALE_INTERVALS
        if c.last_ok:
            return now - c.last_ok > deadline
        return now - c.started > deadline

    def healthy(self, now: float | None = None) -> bool:
        now = now or time.time()
        return all(not self._stale(c, now) for c in self._components.values())

    def snapshot(self, now: float | None = None) -> dict:
        now = now or time.time()
        return {
            "ok": self.healthy(now),
            "uptime_seconds": int(now - self.started_at),
            "components": {
                c.name: {
                    "ok": not self._stale(c, now),
                    "last_ok_age_seconds": int(now - c.last_ok) if c.last_ok else None,
                    "fails": c.fails,
                    "last_error": c.last_error,
                }
                for c in self._components.values()
            },
        }
