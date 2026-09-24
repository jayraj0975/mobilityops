"""Abuse limits for a publicly reachable API: per-client rate limits and a hard body cap.

Both are in-memory and per process, which is right for one small service (and stated as a limit in
docs/SECURITY.md). They are off by default for local use and switched on by configuration
(``MOBILITYOPS_RATE_LIMIT`` etc.), as a public deployment must.

Client identity is the socket peer. Behind a reverse proxy the peer is the proxy, so the first hop
of ``X-Forwarded-For`` is used *only* when ``MOBILITYOPS_TRUST_PROXY`` says the proxy is ours;
otherwise a client could dodge the limiter by sending that header itself.
"""

from __future__ import annotations

import json
import threading
import time
from collections import OrderedDict, deque
from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any

MAX_TRACKED_CLIENTS = 10_000
WINDOW_SECONDS = 60.0

Scope = MutableMapping[str, Any]
Message = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]


class RateLimiter:
    """Sliding-window counter per (client, bucket). ``limit <= 0`` disables the bucket."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._hits: OrderedDict[tuple[str, str], deque[float]] = OrderedDict()

    def check(self, client: str, bucket: str, limit: int) -> tuple[bool, float]:
        """Record a request. Returns ``(allowed, seconds_until_a_slot_frees)``."""
        if limit <= 0:
            return True, 0.0
        now = self._clock()
        key = (client, bucket)
        with self._lock:
            q = self._hits.get(key)
            if q is None:
                q = self._hits[key] = deque()
                while len(self._hits) > MAX_TRACKED_CLIENTS:
                    self._hits.popitem(last=False)  # forget the least recently seen client
            else:
                self._hits.move_to_end(key)
            while q and now - q[0] >= WINDOW_SECONDS:
                q.popleft()
            if len(q) >= limit:
                return False, max(0.0, WINDOW_SECONDS - (now - q[0]))
            q.append(now)
            return True, 0.0


def client_ip(peer: str | None, forwarded_for: str | None, trust_proxy: bool) -> str:
    if trust_proxy and forwarded_for:
        first = forwarded_for.split(",")[0].strip()
        if first and len(first) <= 64:
            return first
    return peer or "unknown"


class BodyLimitMiddleware:
    """Refuse request bodies over ``max_bytes`` even when sent chunked without Content-Length.

    The body is buffered before the application sees it (it is capped at a few KiB by design), so
    an oversized upload is answered 413 immediately and never reaches a parser that might turn the
    failure into something vaguer. Accepted bodies are replayed unchanged.
    """

    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        buffered: list[Message] = []
        total = 0
        while True:
            message = await receive()
            buffered.append(message)
            if message["type"] != "http.request":
                break  # a disconnect: nothing more to read
            total += len(message.get("body", b""))
            if total > self.max_bytes:
                await self._refuse(send)
                return
            if not message.get("more_body", False):
                break
        replay = iter(buffered)

        async def replaying_receive() -> Message:
            try:
                return next(replay)
            except StopIteration:
                return await receive()  # after the body: wait for a disconnect, as normal

        await self.app(scope, replaying_receive, send)

    async def _refuse(self, send: Send) -> None:
        body = json.dumps(
            {
                "error": {
                    "code": "payload_too_large",
                    "message": f"request body exceeds {self.max_bytes} bytes",
                    "request_id": "n/a",
                }
            }
        ).encode()
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})
