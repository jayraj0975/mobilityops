"""Operational store for the live layer: SQLite in WAL mode.

Why SQLite and not Postgres or Redis: one writer (the worker), a few readers (the API), a few
thousand rows a day, one machine. WAL lets readers and the writer work at once; nothing here needs
a network database, a cache tier or a broker, and each of those is one more thing to operate and
secure (docs/DECISIONS.md, ADR-018). The analytical history stays in DuckDB/Parquet.

The worker is the only writer. The API opens the file with ``query_only`` so a bug there cannot
write. Timestamps: ``*_at`` columns are UTC ISO-8601 strings; ``hour_ts`` is naive local
(Asia/Kolkata), the same convention as the analytical database.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from mobilityops.pune.sources.base import Observation

SCHEMA = """
CREATE TABLE IF NOT EXISTS kv(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS ingestion_run(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT NOT NULL,
    ok INTEGER NOT NULL,
    records_in INTEGER NOT NULL DEFAULT 0,
    records_ok INTEGER NOT NULL DEFAULT 0,
    duration_ms INTEGER NOT NULL DEFAULT 0,
    error TEXT
);
CREATE INDEX IF NOT EXISTS ix_run_source ON ingestion_run(source, id DESC);
CREATE TABLE IF NOT EXISTS observation(
    source TEXT NOT NULL,
    metric TEXT NOT NULL,
    lat REAL NOT NULL,
    lon REAL NOT NULL,
    value REAL NOT NULL,
    unit TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    received_at TEXT NOT NULL,
    data_class TEXT NOT NULL,
    modelled INTEGER NOT NULL,
    PRIMARY KEY (source, metric, lat, lon, observed_at)
);
CREATE INDEX IF NOT EXISTS ix_obs_time ON observation(observed_at);
CREATE TABLE IF NOT EXISTS zone_hour(
    zone_id INTEGER NOT NULL,
    hour_ts TEXT NOT NULL,
    pickups INTEGER NOT NULL,
    dropoffs INTEGER NOT NULL,
    partial INTEGER NOT NULL,
    computed_at TEXT NOT NULL,
    PRIMARY KEY (zone_id, hour_ts)
);
CREATE TABLE IF NOT EXISTS zone_forecast(
    zone_id INTEGER NOT NULL,
    hour_ts TEXT NOT NULL,
    pred REAL NOT NULL,
    lo REAL NOT NULL,
    hi REAL NOT NULL,
    model_id TEXT NOT NULL,
    made_at TEXT NOT NULL,
    PRIMARY KEY (zone_id, hour_ts)
);
CREATE TABLE IF NOT EXISTS live_event(
    id TEXT PRIMARY KEY,
    zone_id INTEGER NOT NULL,
    kind TEXT NOT NULL,
    severity TEXT NOT NULL,
    start_ts TEXT NOT NULL,
    end_ts TEXT NOT NULL,
    actual REAL NOT NULL,
    expected REAL NOT NULL,
    score REAL NOT NULL,
    detected_at TEXT NOT NULL,
    explanation TEXT NOT NULL
);
"""

HISTORY_KEEP_DAYS = 14
RUNS_KEEP = 2000


def iso(ts: datetime) -> str:
    return (
        (ts if ts.tzinfo else ts.replace(tzinfo=UTC)).astimezone(UTC).isoformat(timespec="seconds")
    )


def parse(text: str | None) -> datetime | None:
    return datetime.fromisoformat(text) if text else None


WORKER_ALIVE_SECONDS = 90.0  # the worker ticks every 15 s; six missed ticks means it is not running


def worker_alive(path: Path, now: datetime | None = None) -> bool:
    """Has the ingestion worker ticked recently? False if the store or the heartbeat is missing."""
    if not path.exists():
        return False
    info = StateStore(path, read_only=True).get_kv("worker") or {}
    last = parse(info.get("last_tick_at"))
    if last is None:
        return False
    age = ((now or datetime.now(UTC)) - last).total_seconds()
    return 0 <= age <= WORKER_ALIVE_SECONDS


class StateStore:
    def __init__(self, path: Path, *, read_only: bool = False) -> None:
        self.path = path
        self.read_only = read_only
        if not read_only:
            path.parent.mkdir(parents=True, exist_ok=True)
            with self._conn() as con:
                con.execute("PRAGMA journal_mode=WAL")
                con.executescript(SCHEMA)
                con.execute("INSERT OR IGNORE INTO kv VALUES('version', '0')")

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        con = sqlite3.connect(self.path, timeout=10)
        con.row_factory = sqlite3.Row
        try:
            if self.read_only:
                con.execute("PRAGMA query_only=ON")
            yield con
            if not self.read_only:
                con.commit()
        finally:
            con.close()

    def exists(self) -> bool:
        return self.path.exists()

    # ---------------------------------------------------------------------- version and kv
    def version(self) -> int:
        with self._conn() as con:
            row = con.execute("SELECT value FROM kv WHERE key='version'").fetchone()
        return int(row["value"]) if row else 0

    def _bump(self, con: sqlite3.Connection) -> None:
        con.execute("UPDATE kv SET value = CAST(value AS INTEGER) + 1 WHERE key='version'")

    def set_kv(self, key: str, value: Any) -> None:
        with self._conn() as con:
            con.execute("INSERT OR REPLACE INTO kv VALUES(?, ?)", (key, json.dumps(value)))
            self._bump(con)

    def get_kv(self, key: str, default: Any = None) -> Any:
        with self._conn() as con:
            row = con.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
        return json.loads(row["value"]) if row else default

    def set_asof(self, source: str, ts: datetime) -> None:
        """Record when a computed (non-observation) source's data applies, e.g. simulated demand."""
        self.set_kv(f"asof:{source}", iso(ts))

    # -------------------------------------------------------------------------- ingestion
    def record_run(
        self,
        source: str,
        started_at: datetime,
        finished_at: datetime,
        *,
        ok: bool,
        records_in: int = 0,
        records_ok: int = 0,
        error: str | None = None,
    ) -> None:
        ms = int((finished_at - started_at).total_seconds() * 1000)
        with self._conn() as con:
            con.execute(
                "INSERT INTO ingestion_run(source, started_at, finished_at, ok, records_in, "
                "records_ok, duration_ms, error) VALUES (?,?,?,?,?,?,?,?)",
                (
                    source,
                    iso(started_at),
                    iso(finished_at),
                    int(ok),
                    records_in,
                    records_ok,
                    ms,
                    error,
                ),
            )
            self._bump(con)

    def runs(self, limit: int = 50, source: str | None = None) -> list[dict[str, Any]]:
        q = "SELECT * FROM ingestion_run"
        args: list[Any] = []
        if source:
            q += " WHERE source=?"
            args.append(source)
        q += " ORDER BY id DESC LIMIT ?"
        args.append(limit)
        with self._conn() as con:
            return [dict(r) for r in con.execute(q, args).fetchall()]

    def source_status(self, source: str) -> dict[str, Any]:
        """Last success, last error and the run of consecutive failures for one source."""
        with self._conn() as con:
            ok = con.execute(
                "SELECT finished_at, records_ok FROM ingestion_run WHERE source=? AND ok=1 "
                "ORDER BY id DESC LIMIT 1",
                (source,),
            ).fetchone()
            last = con.execute(
                "SELECT finished_at, ok, error FROM ingestion_run WHERE source=? "
                "ORDER BY id DESC LIMIT 1",
                (source,),
            ).fetchone()
            fails = con.execute(
                "SELECT count(*) AS n FROM ingestion_run WHERE source=? AND ok=0 AND id > "
                "coalesce((SELECT max(id) FROM ingestion_run WHERE source=? AND ok=1), 0)",
                (source, source),
            ).fetchone()
            totals = con.execute(
                "SELECT count(*) AS runs, sum(ok) AS ok, coalesce(sum(records_ok),0) AS recs "
                "FROM ingestion_run WHERE source=?",
                (source,),
            ).fetchone()
            obs = con.execute(
                "SELECT max(observed_at) AS observed, max(received_at) AS received "
                "FROM observation WHERE source=?",
                (source,),
            ).fetchone()
        return {
            "last_success_at": parse(ok["finished_at"]) if ok else None,
            "last_run_at": parse(last["finished_at"]) if last else None,
            "last_error": last["error"] if last and not last["ok"] else None,
            "consecutive_failures": int(fails["n"]),
            "runs": int(totals["runs"]),
            "successes": int(totals["ok"] or 0),
            "records_total": int(totals["recs"]),
            "last_observed_at": (
                parse(obs["observed"])
                if obs and obs["observed"]
                else parse(self.get_kv(f"asof:{source}"))
            ),
            "last_received_at": parse(obs["received"]) if obs and obs["received"] else None,
        }

    # ------------------------------------------------------------------------ observations
    def add_observations(self, obs: list[Observation]) -> int:
        rows = [
            (
                o.source, o.metric, round(o.lat, 4), round(o.lon, 4), o.value, o.unit,
                iso(o.observed_at), iso(o.received_at), o.data_class, int(o.modelled),
            )
            for o in obs
        ]  # fmt: skip
        with self._conn() as con:
            con.executemany("INSERT OR REPLACE INTO observation VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
            self._bump(con)
        return len(rows)

    def latest_observations(self, source: str | None = None) -> list[dict[str, Any]]:
        """The newest observation for each source, metric and place."""
        q = (
            "SELECT o.* FROM observation o JOIN (SELECT source, metric, lat, lon, "
            "max(observed_at) AS m FROM observation {w} GROUP BY 1,2,3,4) l "
            "ON o.source=l.source AND o.metric=l.metric AND o.lat=l.lat AND o.lon=l.lon "
            "AND o.observed_at=l.m ORDER BY o.source, o.metric, o.lat, o.lon"
        )
        args: list[Any] = []
        where = ""
        if source:
            where = "WHERE source=?"
            args.append(source)
        with self._conn() as con:
            return [dict(r) for r in con.execute(q.format(w=where), args).fetchall()]

    def observation_series(
        self, source: str, metric: str, hours: int, now: datetime
    ) -> list[dict[str, Any]]:
        """Mean over places per observation time, for the last ``hours``."""
        since = iso(now - timedelta(hours=hours))
        with self._conn() as con:
            rows = con.execute(
                "SELECT observed_at, avg(value) AS value FROM observation WHERE source=? AND "
                "metric=? AND observed_at>=? GROUP BY observed_at ORDER BY observed_at",
                (source, metric, since),
            ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------------ demand, forecast
    def put_zone_hours(self, frame: pd.DataFrame, partial_hour: str | None, now: datetime) -> None:
        """Insert or replace simulated zone-hours. ``partial_hour``: the (still running) hour."""
        stamp = iso(now)
        rows = [
            (
                int(z), pd.Timestamp(h).isoformat(), int(p), int(d),
                int(partial_hour is not None and pd.Timestamp(h).isoformat() == partial_hour),
                stamp,
            )
            for z, h, p, d in zip(
                frame["location_id"], frame["hour_ts"], frame["pickups"], frame["dropoffs"],
                strict=True,
            )
        ]  # fmt: skip
        with self._conn() as con:
            con.executemany("INSERT OR REPLACE INTO zone_hour VALUES (?,?,?,?,?,?)", rows)
            self._bump(con)

    def zone_hours(self, start: str, end: str) -> pd.DataFrame:
        with self._conn() as con:
            rows = con.execute(
                "SELECT * FROM zone_hour WHERE hour_ts>=? AND hour_ts<? ORDER BY hour_ts, zone_id",
                (start, end),
            ).fetchall()
        return pd.DataFrame([dict(r) for r in rows])

    def put_forecast(self, frame: pd.DataFrame, model_id: str, made_at: datetime) -> None:
        stamp = iso(made_at)
        rows = [
            (int(z), pd.Timestamp(h).isoformat(), float(p), float(lo), float(hi), model_id, stamp)
            for z, h, p, lo, hi in zip(
                frame["location_id"], frame["hour_ts"], frame["pred"], frame["lo"], frame["hi"],
                strict=True,
            )
        ]  # fmt: skip
        with self._conn() as con:
            con.executemany("INSERT OR REPLACE INTO zone_forecast VALUES (?,?,?,?,?,?,?)", rows)
            self._bump(con)

    def forecast(self, start: str, end: str) -> pd.DataFrame:
        with self._conn() as con:
            rows = con.execute(
                "SELECT * FROM zone_forecast WHERE hour_ts>=? AND hour_ts<? "
                "ORDER BY hour_ts, zone_id",
                (start, end),
            ).fetchall()
        return pd.DataFrame([dict(r) for r in rows])

    # ------------------------------------------------------------------------------ events
    def replace_events(self, day_prefix: str, events: list[dict[str, Any]]) -> None:
        """Replace the detected events whose start is on ``day_prefix`` (``YYYY-MM-DD``)."""
        with self._conn() as con:
            con.execute("DELETE FROM live_event WHERE start_ts LIKE ?", (f"{day_prefix}%",))
            con.executemany(
                "INSERT OR REPLACE INTO live_event VALUES (:id,:zone_id,:kind,:severity,:start_ts,"
                ":end_ts,:actual,:expected,:score,:detected_at,:explanation)",
                events,
            )
            self._bump(con)

    def events(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._conn() as con:
            rows = con.execute(
                "SELECT * FROM live_event ORDER BY end_ts DESC, ABS(score) DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]

    # ----------------------------------------------------------------------------- upkeep
    def prune(self, now: datetime) -> None:
        cutoff = iso(now - timedelta(days=HISTORY_KEEP_DAYS))
        local_cut = (now - timedelta(days=HISTORY_KEEP_DAYS)).replace(tzinfo=None).isoformat()
        with self._conn() as con:
            con.execute("DELETE FROM observation WHERE observed_at < ?", (cutoff,))
            con.execute("DELETE FROM zone_hour WHERE hour_ts < ?", (local_cut,))
            con.execute("DELETE FROM zone_forecast WHERE hour_ts < ?", (local_cut,))
            con.execute(
                "DELETE FROM ingestion_run WHERE id <= (SELECT max(id) FROM ingestion_run) - ?",
                (RUNS_KEEP,),
            )
