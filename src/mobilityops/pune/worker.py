"""The ingestion worker: a separate process that keeps the operational store current.

It is the only writer to the store. Each source is a job with its own schedule; a failing source
is recorded (``ingestion_run``) and retried with backoff, and never stops the others. The worker
does not substitute values for a failed source: the store simply stops getting newer data, the
freshness module notices from the timestamps, and the interface says so.

Jobs (interval in seconds):

* open-meteo-forecast        900  current weather at a 3x3 grid over the study area
* open-meteo-air-quality    3600  modelled air quality at the same grid
* open-meteo-rain-hourly     900  hourly rain for the recent days (drives the simulated demand)
* simulated-demand            60  today's SIMULATED zone-hours up to now, then live events
* model-forecast           daily  today's forecast, made from data up to yesterday
"""

from __future__ import annotations

import os
import threading
import time
import traceback
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

import duckdb
import httpx
import pandas as pd

from mobilityops.config import Settings
from mobilityops.forecasting.features import load_demand
from mobilityops.forecasting.model import load_model
from mobilityops.log import get_logger
from mobilityops.pune import live, simulate
from mobilityops.pune.build import SEED, WEATHER_FILE, zone_frame
from mobilityops.pune.sources import openmeteo
from mobilityops.pune.sources.base import Observation, SourceError
from mobilityops.pune.store import StateStore

log = get_logger("pune.worker")

TICK_SECONDS = 15.0
BACKOFF_BASE_SECONDS = 30.0
GRID = 3  # weather is fetched on a GRID x GRID lattice over the study area
RAIN_PAST_DAYS = 9


def start_worker_thread(settings: Settings) -> tuple[threading.Thread, threading.Event]:
    """Run the worker inside this process, on a daemon thread; returns the thread and stop event.

    For hosts that offer no separate background process (Render's free web service). The worker is
    still the only writer to the store; the API opens it query-only. In a normal deployment run
    ``pune-worker`` as its own process instead (ADR-019).
    """
    stop = threading.Event()

    def run() -> None:
        with httpx.Client(follow_redirects=False) as client:
            Worker(settings, StateStore(settings.state_path), client).run_forever(stop)

    thread = threading.Thread(target=run, name="pune-worker", daemon=True)
    thread.start()
    return thread, stop


def weather_grid(
    bbox: tuple[float, float, float, float], n: int = GRID
) -> list[tuple[float, float]]:
    """Cell centres of an n x n lattice over the bounding box: (lat, lon) pairs."""
    lat0, lon0, lat1, lon1 = bbox
    return [
        (
            round(lat0 + (i + 0.5) * (lat1 - lat0) / n, 4),
            round(lon0 + (j + 0.5) * (lon1 - lon0) / n, 4),
        )
        for i in range(n)
        for j in range(n)
    ]


@dataclass
class Job:
    source: str
    interval_s: float
    fn: Callable[[datetime], tuple[int, int]]  # returns (records_in, records_ok)
    next_at: float = 0.0
    failures: int = 0


@dataclass
class Worker:
    settings: Settings
    store: StateStore
    client: httpx.Client
    clock: Callable[[], datetime] = lambda: datetime.now(UTC)
    seed: int = SEED
    jobs: list[Job] = field(default_factory=list)
    rain: pd.DataFrame = field(
        default_factory=lambda: pd.DataFrame(columns=["hour_ts", "precipitation"])
    )
    _sim_model: simulate.ZoneModel | None = None
    _zone_names: dict[int, str] = field(default_factory=dict)
    _forecast_day: date | None = None
    _forecast_frame: pd.DataFrame | None = None

    def __post_init__(self) -> None:
        zones = zone_frame()
        self._sim_model = simulate.build_model(zones)
        self._zone_names = dict(zip(zones["location_id"], zones["zone"], strict=True))
        self._grid = weather_grid(self.settings.city.bbox)
        self._centre = self.centre
        self.jobs = [
            Job("open-meteo-forecast", 900, self._weather),
            Job("open-meteo-air-quality", 3600, self._air),
            Job("open-meteo-rain-hourly", 900, self._rain_hourly),
            Job("simulated-demand", 60, self._demand),
        ]
        cached = self.settings.raw_dir / WEATHER_FILE
        if cached.exists():
            self.rain = pd.read_parquet(cached)[["hour_ts", "precipitation"]]

    @property
    def centre(self) -> tuple[float, float]:
        b = self.settings.city.bbox
        return ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2)

    # ---------------------------------------------------------------------------- jobs
    def _weather(self, now: datetime) -> tuple[int, int]:
        obs = openmeteo.fetch_current_weather(self.client, self._grid, now)
        return len(self._grid) * len(openmeteo.WEATHER_VARS), self.store.add_observations(obs)

    def _air(self, now: datetime) -> tuple[int, int]:
        obs = openmeteo.fetch_current_air(self.client, self._grid, now)
        return len(self._grid) * len(openmeteo.AIR_VARS), self.store.add_observations(obs)

    def _rain_hourly(self, now: datetime) -> tuple[int, int]:
        lat, lon = self._centre
        frame = openmeteo.fetch_recent_hourly(self.client, lat, lon, RAIN_PAST_DAYS, 2)
        recent = frame[["hour_ts", "precipitation"]].dropna()
        keep = self.rain[~self.rain["hour_ts"].isin(recent["hour_ts"])]
        self.rain = pd.concat([keep, recent], ignore_index=True).sort_values("hour_ts")
        running = pd.Timestamp(live.local_naive(now)).floor("h")
        obs = []
        for hour, mm in zip(recent["hour_ts"], recent["precipitation"], strict=True):
            local = pd.Timestamp(hour)
            if local > running:
                continue  # a forecast hour is not an observation
            obs.append(
                Observation(
                    source="open-meteo-rain-hourly",
                    metric="precipitation",
                    value=float(mm),
                    unit="mm",
                    observed_at=local.tz_localize(live.LOCAL).tz_convert(UTC).to_pydatetime(),
                    received_at=now,
                    lat=lat,
                    lon=lon,
                    data_class="RECENT",
                    modelled=True,
                )
            )
        return len(frame), self.store.add_observations(obs)

    def _demand(self, now: datetime) -> tuple[int, int]:
        assert self._sim_model is not None
        frame, partial = live.simulate_recent(self._sim_model, now, self.rain, self.seed)
        self.store.put_zone_hours(frame, partial, now)
        self.store.set_asof("simulated-demand", now)
        self._ensure_forecast(now)
        self._detect(now, frame[frame["hour_ts"] >= pd.Timestamp(live.local_naive(now).date())])
        return len(frame), len(frame)

    # -------------------------------------------------------------------- forecast, events
    def _ensure_forecast(self, now: datetime) -> None:
        today = live.local_naive(now).date()
        if self._forecast_day == today and self._forecast_frame is not None:
            return
        started = self.clock()
        try:
            assert self._sim_model is not None
            tensor = load_demand(self.settings.db_path, self.settings.city)
            model = load_model(self.settings)
            frame = live.forecast_today(tensor, model, self._sim_model, today, self.rain, self.seed)
            model_id = (
                str(model.meta.get("model_id", "latest")) if hasattr(model, "meta") else "latest"
            )
            self.store.put_forecast(frame, model_id, now)
            self.store.set_asof("model-forecast", now)
            self.store.set_kv("forecast_meta", {"model_id": model_id, "made_at": now.isoformat()})
            self._forecast_day, self._forecast_frame = today, frame
            self.store.record_run(
                "model-forecast",
                started,
                self.clock(),
                ok=True,
                records_in=len(frame),
                records_ok=len(frame),
            )
        except (FileNotFoundError, ValueError, duckdb.Error) as exc:
            self.store.record_run(
                "model-forecast", started, self.clock(), ok=False, error=str(exc)[:300]
            )
            log.warning("forecast unavailable", extra={"ctx": {"error": str(exc)[:200]}})

    def _detect(self, now: datetime, actual: pd.DataFrame) -> None:
        if self._forecast_frame is None:
            return
        events = live.detect_live_events(actual, self._forecast_frame, self._zone_names, now)
        self.store.replace_events(live.local_naive(now).date().isoformat(), events)

    # ---------------------------------------------------------------------------- loop
    def _run_job(self, job: Job, mono: float) -> None:
        started = self.clock()
        try:
            n_in, n_ok = job.fn(started)
            self.store.record_run(
                job.source, started, self.clock(), ok=True, records_in=n_in, records_ok=n_ok
            )
            job.failures = 0
            job.next_at = mono + job.interval_s
        except (SourceError, ValueError, OSError, duckdb.Error) as exc:
            job.failures += 1
            self.store.record_run(job.source, started, self.clock(), ok=False, error=str(exc)[:300])
            wait = min(job.interval_s, BACKOFF_BASE_SECONDS * 2 ** (job.failures - 1))
            job.next_at = mono + wait
            log.warning(
                "source failed",
                extra={"ctx": {"source": job.source, "error": str(exc)[:200], "retry_s": wait}},
            )
        except Exception as exc:  # a bug in one job must not stop the worker
            job.failures += 1
            self.store.record_run(
                job.source, started, self.clock(), ok=False, error=f"internal error: {exc!r}"[:300]
            )
            job.next_at = mono + BACKOFF_BASE_SECONDS * 4
            log.error(
                "job crashed",
                extra={"ctx": {"source": job.source, "trace": traceback.format_exc()[-800:]}},
            )

    def tick(self, mono: float | None = None) -> None:
        """Run every job that is due. The rain job runs before demand so demand sees new rain."""
        m = time.monotonic() if mono is None else mono
        for job in self.jobs:
            if m >= job.next_at:
                self._run_job(job, m)
        now = self.clock()
        self.store.set_kv(
            "worker",
            {
                "pid": os.getpid(),
                "last_tick_at": now.isoformat(timespec="seconds"),
                "tick_s": TICK_SECONDS,
            },
        )

    def run_forever(self, stop: threading.Event | None = None) -> None:
        """Tick until ``stop`` is set. Waiting on the event (not sleeping) stops it at once."""
        stop = stop or threading.Event()
        self.store.set_kv("worker_started_at", self.clock().isoformat(timespec="seconds"))
        last_prune = self.clock() - timedelta(days=1)
        while not stop.is_set():
            self.tick()
            if self.clock() - last_prune > timedelta(hours=6):
                self.store.prune(self.clock())
                last_prune = self.clock()
            stop.wait(TICK_SECONDS)
