"""``/api/v1/state/*``: the live operational picture of Pune (see ``pune/state.py``)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse

from mobilityops.analytics.queries import NoData
from mobilityops.api import state_schemas as st
from mobilityops.api.services import NotReady
from mobilityops.config import Settings
from mobilityops.live.hub import LiveBusy
from mobilityops.pune.hub import StateHub
from mobilityops.pune.state import StateService
from mobilityops.pune.store import StateStore


class StateProvider:
    """Builds the read model on first use; only meaningful in ``pune`` mode."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._service: StateService | None = None
        self.clock: Callable[[], datetime] = lambda: datetime.now(UTC)

    def maybe(self) -> StateService | None:
        if self.settings.mode != "pune":
            return None
        if self._service is None:
            if not self.settings.state_path.exists():
                return None
            self._service = StateService(
                self.settings, StateStore(self.settings.state_path, read_only=True)
            )
        return self._service

    def require(self) -> StateService:
        if self.settings.mode != "pune":
            raise NoData("the live state is only available in pune mode (MOBILITYOPS_MODE=pune)")
        svc = self.maybe()
        if svc is None:
            raise NotReady("the ingestion worker has not started; run `pune-worker`")
        return svc


def register(api: APIRouter, settings: Settings) -> tuple[StateProvider, StateHub]:
    provider = StateProvider(settings)
    hub = StateHub(
        provider.maybe, max_streams=settings.live_max_streams, clock=lambda: provider.clock()
    )

    def now() -> datetime:
        return provider.clock()

    @api.get("/state/snapshot", response_model=st.StateSnapshot, tags=["state"])
    def state_snapshot(selector: Annotated[st.TimeSelector, Query(alias="at")] = "now") -> Any:
        """Every zone's simulated demand against its forecast at ``at`` (NOW, -15m, -1h, -6h,
        today, or forecast), plus events, weather, and the freshness of every source."""
        return provider.require().snapshot(selector, now())

    @api.get("/state/geometry", response_model=st.Geometry, tags=["state"])
    def state_geometry() -> Any:
        """Zone polygons and attribution (OpenStreetMap, ODbL). Static: cache freely."""
        return provider.require().geometry()

    @api.get("/state/zones/{zone_id}", response_model=st.ZoneDetail, tags=["state"])
    def state_zone(zone_id: int) -> Any:
        detail = provider.require().zone_detail(zone_id, now())
        if detail is None:
            raise NoData(f"unknown zone id {zone_id}")
        return detail

    @api.get("/state/events", response_model=list[st.EventItem], tags=["state"])
    def state_events(limit: Annotated[int, Query(ge=1, le=200)] = 30) -> Any:
        """Events the live rule found among today's completed hours (SIMULATED demand)."""
        return provider.require().events(now(), limit)

    @api.get("/state/sources", response_model=list[st.SourceState], tags=["state"])
    def state_sources() -> Any:
        """Every data source: what it is, its licence, and its freshness right now."""
        return provider.require().sources(now())

    @api.get("/state/quality", response_model=st.DataQuality, tags=["state"])
    def state_quality() -> Any:
        """The data-quality centre: database checks, source health and recent ingestion runs."""
        return provider.require().quality(now())

    @api.get("/state/runs", response_model=list[st.IngestionRun], tags=["state"])
    def state_runs(
        limit: Annotated[int, Query(ge=1, le=500)] = 50, source: str | None = None
    ) -> Any:
        return provider.require().ingestion_runs(limit, source)

    @api.get(
        "/state/stream",
        tags=["state"],
        responses={
            200: {"content": {"text/event-stream": {}}, "description": "Server-sent events"}
        },
    )
    async def state_stream(
        request: Request, limit: Annotated[int | None, Query(ge=1, le=10_000)] = None
    ) -> StreamingResponse:
        """Server-sent events: ``hello`` (a full snapshot), ``snapshot`` when the store changes
        (and at least every 30 s), and ``heartbeat`` every 10 s. ``limit`` ends the stream after
        that many events (for tests and ``curl``)."""
        if hub.streams >= settings.live_max_streams:
            raise LiveBusy(f"{settings.live_max_streams} live streams are already open")
        return StreamingResponse(
            hub.stream(request, limit),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @api.get("/state/stream/status", response_model=st.StreamStatus, tags=["state"])
    def state_stream_status() -> Any:
        return hub.status()

    return provider, hub
