"""Small in-memory metrics: enough to see how the service is behaving, nothing more.

Only route *templates* are recorded (``/api/v1/zones/{zone_id}``), never raw paths, query strings,
questions or headers, so the numbers cannot leak what people asked. Counters reset on restart.
"""

from __future__ import annotations

import threading
import time
from collections import Counter, deque
from typing import Any

MAX_SAMPLES = 1000  # latency samples kept per route


class Metrics:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.started = time.time()
        self.requests: Counter[tuple[str, str, int]] = Counter()
        self.latency: dict[str, deque[float]] = {}
        self.analyst: Counter[str] = Counter()
        self.events: Counter[str] = Counter()

    def request(self, method: str, route: str, status: int, ms: float) -> None:
        with self._lock:
            self.requests[(method, route, status)] += 1
            self.latency.setdefault(route, deque(maxlen=MAX_SAMPLES)).append(ms)

    def analyst_outcome(self, status: str, removed: int, injection: bool) -> None:
        with self._lock:
            self.analyst[f"status.{status}"] += 1
            if removed:
                self.analyst["statements_withheld_ungrounded"] += removed
            if injection:
                self.analyst["instruction_override_flagged"] += 1

    def event(self, name: str) -> None:
        with self._lock:
            self.events[name] += 1

    @staticmethod
    def _pct(values: list[float], q: float) -> float:
        s = sorted(values)
        return round(s[min(len(s) - 1, int(q * (len(s) - 1) + 0.5))], 2)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            by_route: dict[str, dict[str, Any]] = {}
            for (method, route, status), n in self.requests.items():
                r = by_route.setdefault(route, {"requests": 0, "by_status": {}})
                r["requests"] += n
                key = f"{method} {status}"
                r["by_status"][key] = r["by_status"].get(key, 0) + n
            for route, samples in self.latency.items():
                vals = list(samples)
                by_route[route]["latency_ms"] = {
                    "p50": self._pct(vals, 0.5),
                    "p95": self._pct(vals, 0.95),
                    "max": round(max(vals), 2),
                    "samples": len(vals),
                }
            total = sum(self.requests.values())
            errors = sum(n for (_, _, s), n in self.requests.items() if s >= 500)
            return {
                "uptime_seconds": round(time.time() - self.started, 1),
                "requests_total": total,
                "server_errors_total": errors,
                "routes": by_route,
                "analyst": dict(self.analyst),
                "events": dict(self.events),
                "note": "In-memory, per process; resets on restart. Route templates only.",
            }
