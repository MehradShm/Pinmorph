"""Bounded process-local request metrics; multi-process aggregation is a later upgrade."""

import math
from threading import Lock
from time import monotonic

BUCKETS_MS = (10, 25, 50, 100, 250, 500, 1000, 2500, 5000)
METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}


class RequestMetrics:
    def __init__(self):
        self._lock = Lock()
        self._started = monotonic()
        self._groups = {}

    def observe(self, method: str, route: str, status: int, latency_ms: float) -> None:
        if not math.isfinite(latency_ms) or latency_ms < 0:
            raise ValueError("Request latency must be finite and nonnegative")
        method = method if method in METHODS else "OTHER"
        status_class = f"{status // 100}xx"
        # Caller supplies a route template, never a user-controlled path/query/item ID.
        key = (method, route, status_class)
        with self._lock:
            group = self._groups.setdefault(
                key, {"count": 0, "latency_sum_ms": 0.0, "buckets": [0] * len(BUCKETS_MS)}
            )
            group["count"] += 1
            group["latency_sum_ms"] += latency_ms
            for index, boundary in enumerate(BUCKETS_MS):
                group["buckets"][index] += latency_ms <= boundary

    def snapshot(self) -> dict:
        with self._lock:
            records = [
                {
                    "method": method,
                    "route": route,
                    "status_class": status,
                    "count": group["count"],
                    "latency_sum_ms": group["latency_sum_ms"],
                    "latency_buckets_ms": {
                        str(bound): count
                        for bound, count in zip(BUCKETS_MS, group["buckets"], strict=True)
                    },
                    "latency_infinite_bucket": group["count"],
                }
                for (method, route, status), group in sorted(self._groups.items())
            ]
        return {
            "scope": "api_process_since_start",
            "uptime_seconds": monotonic() - self._started,
            "requests": records,
        }
