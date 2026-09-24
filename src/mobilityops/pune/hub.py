"""Server-sent events for the Pune state: one poller shared by every viewer.

The hub watches the operational store's version counter and pushes a fresh snapshot when it
changes (and at least every ``SNAPSHOT_EVERY`` seconds, because pro-rated values and freshness
ages move with the clock even when nothing is written). Viewers also get a small ``heartbeat``
every few seconds so a client can tell "the server is fine, nothing changed" from "the
connection died".

The poller runs only while someone is watching. Each viewer has a bounded queue: a slow client loses
its oldest event and never blocks the others.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from mobilityops.live.hub import LiveBusy
from mobilityops.pune.state import StateService

POLL_SECONDS = 1.0
HEARTBEAT_SECONDS = 10.0
SNAPSHOT_EVERY = 30.0
QUEUE_SIZE = 20


def encode(event: str, payload: dict[str, Any], event_id: int) -> str:
    body = json.dumps(payload, separators=(",", ":"), default=_json_default)
    return f"id: {event_id}\nevent: {event}\ndata: {body}\n\n"


def _json_default(o: object) -> str:
    if isinstance(o, datetime):
        return (o if o.tzinfo else o.replace(tzinfo=UTC)).isoformat()
    raise TypeError(f"not JSON serialisable: {type(o).__name__}")


@dataclass(eq=False)
class Viewer:
    queue: asyncio.Queue[tuple[str, dict[str, Any]]] = field(
        default_factory=lambda: asyncio.Queue(QUEUE_SIZE)
    )


class StateHub:
    def __init__(
        self,
        service: Callable[[], StateService | None],
        *,
        max_streams: int = 32,
        poll_seconds: float = POLL_SECONDS,
        heartbeat_seconds: float = HEARTBEAT_SECONDS,
        snapshot_every: float = SNAPSHOT_EVERY,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.clock = clock
        self._service = service
        self.max_streams = max_streams
        self._poll = poll_seconds
        self._heartbeat = heartbeat_seconds
        self._snapshot_every = snapshot_every
        self._viewers: set[Viewer] = set()
        self._task: asyncio.Task[None] | None = None
        self._seq = 0
        self.published = 0
        self.dropped = 0

    @property
    def streams(self) -> int:
        return len(self._viewers)

    def subscribe(self) -> Viewer:
        if len(self._viewers) >= self.max_streams:
            raise LiveBusy(f"{self.max_streams} live streams are already open; try again shortly")
        viewer = Viewer()
        self._viewers.add(viewer)
        if self._task is None or self._task.done():
            self._task = asyncio.get_running_loop().create_task(self._run())
        return viewer

    def unsubscribe(self, viewer: Viewer) -> None:
        self._viewers.discard(viewer)
        if not self._viewers and self._task is not None:
            self._task.cancel()
            self._task = None

    def publish(self, kind: str, payload: dict[str, Any]) -> None:
        self.published += 1
        for v in list(self._viewers):
            if v.queue.full():
                self.dropped += 1
                with contextlib.suppress(asyncio.QueueEmpty):
                    v.queue.get_nowait()
            v.queue.put_nowait((kind, payload))

    def status(self) -> dict[str, Any]:
        return {
            "streams": self.streams,
            "max_streams": self.max_streams,
            "published": self.published,
            "dropped_events": self.dropped,
        }

    async def _run(self) -> None:
        last_version = -1
        last_snapshot = 0.0
        last_beat = 0.0
        while True:
            svc = self._service()
            now_m = time.monotonic()
            if svc is not None:
                version = svc.store.version()
                if version != last_version or now_m - last_snapshot >= self._snapshot_every:
                    last_version, last_snapshot = version, now_m
                    self.publish("snapshot", svc.snapshot("now", self.clock(), version))
                if now_m - last_beat >= self._heartbeat:
                    last_beat = now_m
                    self.publish(
                        "heartbeat",
                        {
                            "server_time": self.clock(),
                            "seq": version,
                            "worker": svc.worker(self.clock()),
                        },
                    )
            await asyncio.sleep(self._poll)

    async def stream(self, request: Any = None, limit: int | None = None) -> AsyncIterator[str]:
        """``hello`` (a full snapshot), then ``snapshot`` and ``heartbeat`` events."""
        viewer = self.subscribe()
        try:
            svc = self._service()
            now = self.clock()
            hello: dict[str, Any] = {
                "server_time": now,
                "available": svc is not None,
                "snapshot": svc.snapshot("now", now) if svc is not None else None,
                "heartbeat_seconds": self._heartbeat,
            }
            self._seq += 1
            yield encode("hello", hello, self._seq)
            sent = 1
            while limit is None or sent < limit:
                try:
                    kind, payload = await asyncio.wait_for(
                        viewer.queue.get(), self._heartbeat + 5.0
                    )
                except TimeoutError:
                    if request is not None and await request.is_disconnected():
                        break
                    yield ": keep-alive\n\n"
                    continue
                self._seq += 1
                yield encode(kind, payload, self._seq)
                sent += 1
                if request is not None and await request.is_disconnected():
                    break
        finally:
            self.unsubscribe(viewer)
