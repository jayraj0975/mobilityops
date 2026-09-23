"""Concurrency smoke test against a running API. A sanity check, not a benchmark.

    python scripts/load_smoke.py --base http://127.0.0.1:8000 --workers 16 --requests 400

It sends a realistic mix of read requests and analyst questions from several threads and reports
the error count and latency percentiles. Numbers depend entirely on the machine it runs on.
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
from concurrent.futures import ThreadPoolExecutor

import httpx

QUESTIONS = [
    "What were the busiest zones last week?",
    "How accurate is the forecast?",
    "Were there any high severity anomalies?",
    "What does WAPE mean?",
    "Compare last week with the week before",
]


def build_mix(meta: dict) -> list[tuple[str, str, dict | None]]:
    last = meta["data_end"][:10]
    first = meta["data_start"][:10]
    return [
        ("GET", "/api/v1/demand/top-zones", {"start": first, "end": last, "limit": 10}),
        ("GET", "/api/v1/demand/series", {"start": first, "end": last, "grain": "day"}),
        ("GET", "/api/v1/demand/profile/hourly", {"start": first, "end": last}),
        ("GET", "/api/v1/forecast/next-day", {}),
        ("GET", "/api/v1/anomalies", {"limit": 20}),
        ("GET", "/api/v1/zones", {}),
        ("POST", "/api/v1/analyst/ask", {"question": QUESTIONS[0]}),
    ]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--workers", type=int, default=16)
    ap.add_argument("--requests", type=int, default=400)
    a = ap.parse_args()
    with httpx.Client(base_url=a.base, timeout=60) as c:
        meta = c.get("/api/v1/meta").json()
    mix = build_mix(meta)

    def one(i: int) -> tuple[str, int, float]:
        method, path, payload = mix[i % len(mix)]
        if path.endswith("/ask"):
            payload = {"question": QUESTIONS[i % len(QUESTIONS)]}
        t0 = time.perf_counter()
        with httpx.Client(base_url=a.base, timeout=60) as c:
            r = c.post(path, json=payload) if method == "POST" else c.get(path, params=payload)
        return path, r.status_code, (time.perf_counter() - t0) * 1000

    t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=a.workers) as pool:
        results = list(pool.map(one, range(a.requests)))
    wall = time.perf_counter() - t0
    lat = sorted(r[2] for r in results)
    bad = [r for r in results if r[1] != 200]
    by: dict[str, list[float]] = {}
    for path, _, ms in results:
        by.setdefault(path, []).append(ms)
    report = {
        "mode": meta["mode"],
        "requests": a.requests,
        "workers": a.workers,
        "wall_seconds": round(wall, 2),
        "throughput_rps": round(a.requests / wall, 1),
        "non_200": len(bad),
        "latency_ms": {
            "p50": round(statistics.median(lat), 1),
            "p95": round(lat[int(0.95 * (len(lat) - 1))], 1),
            "max": round(lat[-1], 1),
        },
        "by_route_p95_ms": {
            p: round(sorted(v)[int(0.95 * (len(v) - 1))], 1) for p, v in sorted(by.items())
        },
    }
    print(json.dumps(report, indent=2))
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
