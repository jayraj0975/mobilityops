"""Broadcast hub: one shared replay clock and one poller for every connected viewer.

Work happens only while at least one viewer is subscribed: the first subscriber starts the tasks
and the last one stops them, so an unwatched server neither burns CPU nor calls the public feeds.
The replay clock is a fixed origin on the monotonic clock, so it keeps its place across those stops
and every viewer sees the same hour at the same moment (like a broadcast, not a per-viewer video).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import threading
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import httpx

from mobilityops.api.services import NotReady, Services
from mobilityops.config import Settings
from mobilityops.live.feeds import LiveFeeds
from mobilityops.live.replay import HISTORY_TICKS, Replay, ReplayUnavailable, build_replay
from mobilityops.log import get_logger

log = get_logger("live.hub")

FEED_POLL_SECONDS = 60.0
HEARTBEAT_SECONDS = 15.0
RETRY_REPLAY_SECONDS = 30.0
QUEUE_SIZE = 100


class LiveBusy(RuntimeError):
    """Too many concurrent streams."""


def encode(event: str, payload: dict[str, Any]) -> str:
    """One server-sent event."""
    return f"event: {event}\ndata: {json.dumps(payload, separators=(',', ':'))}\n\n"


@dataclass(eq=False)
class Subscription:
    queue: asyncio.Queue[tuple[str, dict[str, Any]]] = field(
        default_factory=lambda: asyncio.Queue(QUEUE_SIZE)
    )


class LiveHub:
    def __init__(
        self,
        settings: Settings,
        services: Services,
        *,
        client_factory: Callable[[], httpx.AsyncClient] | None = None,
        feed_poll_seconds: float = FEED_POLL_SECONDS,
    ) -> None:
        self.settings = settings
        self.services = services
        self._client_factory = client_factory or (lambda: httpx.AsyncClient(follow_redirects=True))
        self._feed_poll_seconds = feed_poll_seconds
        self._subs: set[Subscription] = set()
        self._tasks: list[asyncio.Task[None]] = []
        self._replay: Replay | None = None
        self._replay_error: str | None = None
        self._replay_tried = -1e9
        self._origin = time.monotonic()
        self._feeds: LiveFeeds | None = None
        self._client: httpx.AsyncClient | None = None
        self._replay_lock = threading.Lock()

    # ------------------------------------------------------------------ replay
    def replay(self) -> Replay | None:
        """The replay, built on first use; retried at most every 30 s while unavailable."""
        with self._replay_lock:  # the start-up warm-up and a first request must not both build it
            now = time.monotonic()
            if self._replay is None and now - self._replay_tried >= RETRY_REPLAY_SECONDS:
                self._replay_tried = now
                art = self.services.artifacts
                try:
                    self._replay = build_replay(
                        art / "forecast" / "predictions.parquet",
                        self.services.analytics().zones(),
                        art / "anomaly" / "events.parquet",
                        seconds_per_hour=self.settings.live_seconds_per_hour,
                        data_label=self.services.data_label,
                    )
                    self._replay.t0 = self._origin
                    self._replay_error = None
                except (ReplayUnavailable, NotReady) as exc:  # no forecasts, or no database yet
                    self._replay_error = str(exc)
            return self._replay

    # -------------------------------------------------------------- subscriptions
    @property
    def streams(self) -> int:
        return len(self._subs)

    def subscribe(self) -> Subscription:
        if len(self._subs) >= self.settings.live_max_streams:
            raise LiveBusy(
                f"{self.settings.live_max_streams} live streams are already open; try again shortly"
            )
        sub = Subscription()
        self._subs.add(sub)
        if not self._tasks:
            self._start()
        return sub

    def unsubscribe(self, sub: Subscription) -> None:
        self._subs.discard(sub)
        if not self._subs:
            self._stop()

    def publish(self, kind: str, payload: dict[str, Any]) -> None:
        for sub in list(self._subs):
            if sub.queue.full():  # a slow viewer loses its oldest event, never blocks the others
                with contextlib.suppress(asyncio.QueueEmpty):
                    sub.queue.get_nowait()
            sub.queue.put_nowait((kind, payload))

    def _start(self) -> None:
        loop = asyncio.get_running_loop()
        self._tasks = [loop.create_task(self._replay_loop())]
        if self.settings.live_feeds:
            self._client = self._client_factory()
            self._feeds = LiveFeeds(self._client) if self._feeds is None else self._feeds
            self._feeds.client = self._client
            self._tasks.append(loop.create_task(self._feeds_loop(self._feeds)))

    def _stop(self) -> None:
        for t in self._tasks:
            t.cancel()
        self._tasks = []
        client, self._client = self._client, None
        if client is not None:
            asyncio.get_running_loop().create_task(client.aclose())

    async def _replay_loop(self) -> None:
        last = -1
        while True:
            r = self.replay()
            if r is None:
                await asyncio.sleep(1.0)
                continue
            now = time.monotonic()
            elapsed = max(0.0, now - r.t0)
            i = r.index_at(now)
            if i != last:
                last = i
                self.publish("replay", r.tick(i, loop=int(elapsed / (r.seconds_per_hour * r.n))))
            boundary = (int(elapsed / r.seconds_per_hour) + 1) * r.seconds_per_hour
            await asyncio.sleep(max(0.01, boundary - elapsed))

    async def _feeds_loop(self, feeds: LiveFeeds) -> None:
        while True:
            now = time.time()
            results = await asyncio.gather(
                feeds.poll_citibike(now), feeds.poll_weather(now), return_exceptions=True
            )
            for state in results:
                if not isinstance(state, BaseException):
                    self.publish("feed", state.to_dict())
            if feeds.history:
                self.publish("history", {"kind": "history", "citibike": list(feeds.history)})
            await asyncio.sleep(self._feed_poll_seconds)

    # -------------------------------------------------------------------- output
    def hello(self) -> dict[str, Any]:
        r = self.replay()
        replay: dict[str, Any]
        if r is None:
            replay = {"available": False, "reason": self._replay_error or "not ready"}
        else:
            i = r.index_at(time.monotonic())
            replay = {"available": True, **r.meta(), "history": r.history(i, HISTORY_TICKS)}
        feeds: dict[str, Any]
        if not self.settings.live_feeds:
            feeds = {"enabled": False}
        else:
            feeds = {"enabled": True, **(self._feeds.snapshot() if self._feeds else {})}
        return {
            "kind": "hello",
            "server_time": datetime.now(UTC).isoformat(),
            "data_label": self.services.data_label,
            "replay": replay,
            "feeds": feeds,
        }

    def status(self) -> dict[str, Any]:
        r = self.replay()
        return {
            "streams": self.streams,
            "max_streams": self.settings.live_max_streams,
            "replay_available": r is not None,
            "replay_reason": None if r is not None else self._replay_error,
            "replay": None if r is None else r.meta(),
            "feeds_enabled": self.settings.live_feeds,
            "feed_poll_seconds": self._feed_poll_seconds,
        }

    async def stream(self, request: Any = None, limit: int | None = None) -> AsyncIterator[str]:
        """The event stream for one viewer: ``hello``, then replay ticks and feed updates."""
        sub = self.subscribe()
        try:
            yield encode("hello", self.hello())
            sent = 1
            while limit is None or sent < limit:
                try:
                    kind, payload = await asyncio.wait_for(sub.queue.get(), HEARTBEAT_SECONDS)
                except TimeoutError:
                    yield ": keep-alive\n\n"
                    if request is not None and await request.is_disconnected():
                        break
                    continue
                yield encode(kind, payload)
                sent += 1
        finally:
            self.unsubscribe(sub)
