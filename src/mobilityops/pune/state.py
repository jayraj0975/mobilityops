"""The read model behind ``/api/v1/state/*``: turns the operational store into what the interface
shows. Pure reads; it never writes and never calls a data source.

Every value that appears carries its own honesty: demand is SIMULATED, weather and air quality are
model output, and each source's freshness is computed from its own timestamps (``freshness.py``).
"""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
from typing import Any

import duckdb
import pandas as pd

from mobilityops.config import Settings
from mobilityops.pune import live
from mobilityops.pune.build import zone_frame
from mobilityops.pune.freshness import Freshness, classify, worst
from mobilityops.pune.sources.registry import SOURCES, SourceSpec
from mobilityops.pune.store import StateStore, iso
from mobilityops.pune.worker import TICK_SECONDS
from mobilityops.pune.zones import load_zones

OFFSETS_MIN = {"now": 0, "-15m": 15, "-1h": 60, "-6h": 360}
MODEL_ERROR_SHARE = live.MODEL_ERROR_SHARE
ENV_METRICS = {
    "temperature_2m": "temperature",
    "relative_humidity_2m": "humidity",
    "precipitation": "precipitation",
    "wind_speed_10m": "wind",
    "pm2_5": "pm2_5",
    "pm10": "pm10",
    "us_aqi": "us_aqi",
}
MIN_MOVER_TRIPS = 15


def _dt(text: str | None) -> datetime | None:
    return datetime.fromisoformat(text) if text else None


class StateService:
    def __init__(self, settings: Settings, store: StateStore) -> None:
        self.settings = settings
        self.store = store
        self._zones = zone_frame().set_index("location_id")
        self._doc = load_zones()

    # ------------------------------------------------------------------------- geometry
    def geometry(self) -> dict[str, Any]:
        doc = self._doc
        return {
            "city": self.settings.city.name,
            "bbox": doc["bbox"],
            "attribution": doc["attribution"],
            "licence": doc["licence"],
            "method": doc["method"],
            "zones": [
                {
                    "id": z["id"],
                    "name": z["name"],
                    "sector": str(self._zones.loc[z["id"], "borough"]),
                    "lat": z["lat"],
                    "lon": z["lon"],
                    "area_km2": z["area_km2"],
                    "ring": z["ring"],
                }
                for z in doc["zones"]
            ],
        }

    # --------------------------------------------------------------------------- sources
    def worker(self, now: datetime) -> dict[str, Any]:
        info = self.store.get_kv("worker") or {}
        last = _dt(info.get("last_tick_at"))
        reading = classify(int(TICK_SECONDS), last, last, now)
        return {
            "freshness": reading.state.value,
            "last_tick_at": last,
            "age_s": reading.age_s,
            "pid": info.get("pid"),
        }

    def source_state(self, spec: SourceSpec, now: datetime) -> dict[str, Any]:
        enabled = spec.enabled()
        st = self.store.source_status(spec.key)
        reading = classify(
            spec.interval_s, st["last_observed_at"], st["last_success_at"], now, enabled=enabled
        )
        return {
            "key": spec.key,
            "label": spec.label,
            "provider": spec.provider,
            "data_class": spec.data_class,
            "modelled": spec.modelled,
            "licence": spec.licence,
            "note": spec.note,
            "enabled": enabled,
            "disabled_reason": None if enabled else spec.disabled_reason(),
            "freshness": reading.state.value,
            "interval_s": spec.interval_s,
            "age_s": reading.age_s,
            "since_poll_s": reading.since_poll_s,
            "last_observed_at": st["last_observed_at"],
            "last_success_at": st["last_success_at"],
            "last_error": st["last_error"],
            "consecutive_failures": st["consecutive_failures"],
            "runs": st["runs"],
            "successes": st["successes"],
            "records_total": st["records_total"],
        }

    def sources(self, now: datetime) -> list[dict[str, Any]]:
        return [self.source_state(s, now) for s in SOURCES]

    @staticmethod
    def overall(sources: list[dict[str, Any]]) -> str:
        applicable = [
            Freshness(s["freshness"]) for s in sources if s["data_class"] not in ("STATIC",)
        ]
        return worst(applicable).value

    # ---------------------------------------------------------------------- environment
    def environment(self, now: datetime, sources: list[dict[str, Any]]) -> dict[str, Any]:
        fresh = {s["key"]: s["freshness"] for s in sources}
        out: dict[str, Any] = {"attribution": "Weather data by Open-Meteo.com (CC BY 4.0)"}
        for key in ("open-meteo-forecast", "open-meteo-air-quality"):
            rows = self.store.latest_observations(key)
            by_metric: dict[str, list[dict[str, Any]]] = {}
            for r in rows:
                by_metric.setdefault(r["metric"], []).append(r)
            for metric, group in by_metric.items():
                name = ENV_METRICS.get(metric)
                if name is None:
                    continue
                out[name] = {
                    "value": round(sum(g["value"] for g in group) / len(group), 2),
                    "unit": group[0]["unit"],
                    "observed_at": max(g["observed_at"] for g in group),
                    "freshness": fresh[key],
                    "modelled": bool(group[0]["modelled"]),
                }
        return out

    # ----------------------------------------------------------------------- the snapshot
    def _window(self, selector: str, now: datetime) -> tuple[pd.Timestamp, pd.Timestamp, str]:
        local = pd.Timestamp(live.local_naive(now))
        if selector == "today":
            return local.normalize(), local, "Today so far, 00:00 to now"
        if selector == "forecast":
            nxt = local.floor("h") + pd.Timedelta(hours=1)
            return nxt, nxt + pd.Timedelta(hours=1), "Forecast for the next full hour"
        t = local - pd.Timedelta(minutes=OFFSETS_MIN[selector])
        start = t.floor("h")
        label = "Now" if selector == "now" else f"{OFFSETS_MIN[selector]} minutes ago"
        return start, t, f"{label}: pickups from {start:%H:%M} to {t:%H:%M} (hour so far)"

    def _values(
        self, selector: str, start: pd.Timestamp, end: pd.Timestamp
    ) -> tuple[pd.DataFrame, pd.DataFrame]:
        """Actual and forecast per zone for the window, hours pro-rated where partial."""
        lo_ts = start.floor("h")
        hi_ts = (end.ceil("h") if selector != "forecast" else end) + pd.Timedelta(seconds=0)
        act = self.store.zone_hours(lo_ts.isoformat(), hi_ts.isoformat())
        fc = self.store.forecast(lo_ts.isoformat(), hi_ts.isoformat())
        for df in (act, fc):
            if not df.empty:
                df["hour_ts"] = pd.to_datetime(df["hour_ts"])
                df["frac"] = [live.hour_fraction(h, end) for h in df["hour_ts"]]
                df.loc[df["hour_ts"] < start.floor("h"), "frac"] = 1.0
        return act, fc

    def snapshot(self, selector: str, now: datetime, seq: int | None = None) -> dict[str, Any]:
        start, end, note = self._window(selector, now)
        act, fc = self._values(selector, start, end)
        sources = self.sources(now)
        events = self.events(now, 20)
        active: dict[int, dict[str, Any]] = {}
        for e in events:  # an event applies to a zone while it overlaps the shown window
            if pd.Timestamp(e["start"]) < end and pd.Timestamp(e["end"]) > start:
                active.setdefault(e["zone_id"], e)
        zones = []
        tot_a = tot_f = tot_lo = tot_hi = 0.0
        have_actual = selector != "forecast" and not act.empty
        forecast_meta = self.store.get_kv("forecast_meta") or {}
        for zid in self._zones.index:
            fz = fc[fc["zone_id"] == zid] if not fc.empty else fc
            az = act[act["zone_id"] == zid] if not act.empty else act
            f = float((fz["pred"] * fz["frac"]).sum()) if not fz.empty else 0.0
            lo = float((fz["lo"] * fz["frac"]).sum()) if not fz.empty else 0.0
            hi = float((fz["hi"] * fz["frac"]).sum()) if not fz.empty else 0.0
            a = float((az["pickups"] * az["frac"]).sum()) if have_actual and not az.empty else None
            z = ratio = None
            if a is not None and f > 0:
                ratio = a / f
                z = (a - f) / math.sqrt(max(f + (MODEL_ERROR_SHARE * f) ** 2, 1.0))
            ev = active.get(int(zid))
            zones.append(
                {
                    "id": int(zid),
                    "actual": None if a is None else round(a, 1),
                    "forecast": round(f, 1),
                    "lo": round(lo, 1),
                    "hi": round(hi, 1),
                    "ratio": None if ratio is None else round(ratio, 3),
                    "z": None if z is None else round(z, 2),
                    "status": ev["kind"] if ev else "normal",
                    "event_id": ev["id"] if ev else None,
                }
            )
            tot_f += f
            tot_lo += lo
            tot_hi += hi
            tot_a += a or 0.0
        totals = {
            "actual": round(tot_a, 1) if have_actual else None,
            "forecast": round(tot_f, 1),
            "lo": round(tot_lo, 1),
            "hi": round(tot_hi, 1),
            "ratio": round(tot_a / tot_f, 3) if have_actual and tot_f > 0 else None,
        }
        return {
            "server_time": now,
            "selector": selector,
            "window_start": start.to_pydatetime(),
            "window_end": end.to_pydatetime(),
            "window_note": note,
            "data_label": self.settings.data_label,
            "city": self.settings.city.name,
            "timezone": self.settings.city.timezone,
            "seq": self.store.version() if seq is None else seq,
            "freshness": self.overall(sources),
            "worker": self.worker(now),
            "forecast_model": forecast_meta.get("model_id"),
            "forecast_made_at": _dt(forecast_meta.get("made_at")),
            "zones": zones,
            "totals": totals,
            "events": events,
            "environment": self.environment(now, sources),
            "sources": sources,
        }

    # ---------------------------------------------------------------------------- events
    def events(self, now: datetime, limit: int = 30) -> list[dict[str, Any]]:
        out = []
        for e in self.store.events(limit):
            zid = int(e["zone_id"])
            out.append(
                {
                    "id": e["id"],
                    "zone_id": zid,
                    "zone": str(self._zones.loc[zid, "zone"])
                    if zid in self._zones.index
                    else str(zid),
                    "kind": e["kind"],
                    "severity": e["severity"],
                    "start": datetime.fromisoformat(e["start_ts"]),
                    "end": datetime.fromisoformat(e["end_ts"]),
                    "actual": e["actual"],
                    "expected": e["expected"],
                    "score": e["score"],
                    "detected_at": _dt(e["detected_at"]) or now,
                    "explanation": e["explanation"],
                    "data_class": "SIMULATED",
                }
            )
        return out

    # -------------------------------------------------------------------------- zone detail
    def zone_detail(self, zone_id: int, now: datetime, hours: int = 30) -> dict[str, Any] | None:
        if zone_id not in self._zones.index:
            return None
        local = pd.Timestamp(live.local_naive(now))
        start = local.floor("h") - pd.Timedelta(hours=hours - 1)
        end = local.floor("h") + pd.Timedelta(hours=24)
        act = self.store.zone_hours(start.isoformat(), end.isoformat())
        fc = self.store.forecast(start.isoformat(), end.isoformat())
        act = act[act["zone_id"] == zone_id] if not act.empty else act
        fc = fc[fc["zone_id"] == zone_id] if not fc.empty else fc
        running = local.floor("h")
        a_by = {pd.Timestamp(r["hour_ts"]): r for r in act.to_dict("records")}
        f_by = {pd.Timestamp(r["hour_ts"]): r for r in fc.to_dict("records")}
        series: list[dict[str, Any]] = []
        today = local.normalize()
        t_act = t_fc = 0.0
        for h in sorted(set(a_by) | set(f_by)):
            a, f = a_by.get(h), f_by.get(h)
            is_running = h == running
            frac = live.hour_fraction(h, local) if is_running else 1.0
            actual = None if a is None or h > running else round(float(a["pickups"]) * frac, 1)
            series.append(
                {
                    "hour": h.to_pydatetime(),
                    "actual": actual,
                    "forecast": None if f is None else round(float(f["pred"]), 1),
                    "lo": None if f is None else round(float(f["lo"]), 1),
                    "hi": None if f is None else round(float(f["hi"]), 1),
                    "partial": is_running,
                }
            )
            if today <= h <= running:
                t_act += actual or 0.0
                t_fc += 0.0 if f is None else float(f["pred"]) * frac
        events = [e for e in self.events(now, 100) if e["zone_id"] == zone_id][:10]
        return {
            "id": zone_id,
            "name": str(self._zones.loc[zone_id, "zone"]),
            "sector": str(self._zones.loc[zone_id, "borough"]),
            "server_time": now,
            "data_label": self.settings.data_label,
            "series": series,
            "events": events,
            "today_actual": round(t_act, 1),
            "today_forecast": round(t_fc, 1),
        }

    # -------------------------------------------------------------------------- quality
    def database(self, now: datetime) -> dict[str, Any]:
        path = self.settings.db_path
        if not path.exists():
            return {"available": False, "checks": []}
        con = duckdb.connect(str(path), read_only=True)
        try:
            run = con.execute(
                "SELECT run_id, built_at_utc, window_start, window_end, rows_valid, synthetic "
                "FROM pipeline_run ORDER BY built_at_utc DESC LIMIT 1"
            ).fetchone()
            checks = con.execute(
                "SELECT \"check\", status, message FROM quality_result WHERE stage = 'gold'"
            ).fetchall()
        finally:
            con.close()
        if run is None:
            return {"available": False, "checks": []}
        end = datetime.fromisoformat(str(run[3])).date()
        behind = (live.local_naive(now).date() - end).days
        return {
            "available": True,
            "run_id": run[0],
            "built_at_utc": run[1],
            "window_start": run[2],
            "window_end": run[3],
            "days_behind": behind,
            "rows_valid": int(run[4]),
            "synthetic": bool(run[5]),
            "checks": [{"check": c, "status": s, "message": m} for c, s, m in checks],
        }

    def health(self, now: datetime, sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
        since = iso(now - timedelta(hours=24))
        out = []
        for s in sources:
            runs = [r for r in self.store.runs(2000, s["key"]) if r["finished_at"] >= since]
            n_ok = sum(1 for r in runs if r["ok"])
            out.append(
                {
                    "key": s["key"],
                    "label": s["label"],
                    "freshness": s["freshness"],
                    "runs_24h": len(runs),
                    "success_rate_24h": (n_ok / len(runs)) if runs else None,
                    "rejected_records_24h": sum(
                        max(0, r["records_in"] - r["records_ok"]) for r in runs if r["ok"]
                    ),
                    "mean_duration_ms": (sum(r["duration_ms"] for r in runs) / len(runs))
                    if runs
                    else None,
                    "last_error": s["last_error"],
                }
            )
        return out

    def quality(self, now: datetime) -> dict[str, Any]:
        sources = self.sources(now)
        runs = [
            {
                "id": r["id"],
                "source": r["source"],
                "started_at": datetime.fromisoformat(r["started_at"]),
                "finished_at": datetime.fromisoformat(r["finished_at"]),
                "ok": bool(r["ok"]),
                "records_in": r["records_in"],
                "records_ok": r["records_ok"],
                "duration_ms": r["duration_ms"],
                "error": r["error"],
            }
            for r in self.store.runs(40)
        ]
        notes = [
            "Demand is SIMULATED: there is no open source of Pune trip data. Rain and the holiday "
            "calendar are real inputs; the level and shape of demand are assumptions.",
            "Weather and air quality are model output on a coarse grid, not station readings.",
            "Freshness is computed from each source's own timestamps, never set by hand.",
        ]
        return {
            "server_time": now,
            "data_label": self.settings.data_label,
            "database": self.database(now),
            "sources": sources,
            "health": self.health(now, sources),
            "runs": runs,
            "notes": notes,
        }

    def ingestion_runs(self, limit: int, source: str | None) -> list[dict[str, Any]]:
        return [
            {
                "id": r["id"],
                "source": r["source"],
                "started_at": datetime.fromisoformat(r["started_at"]),
                "finished_at": datetime.fromisoformat(r["finished_at"]),
                "ok": bool(r["ok"]),
                "records_in": r["records_in"],
                "records_ok": r["records_ok"],
                "duration_ms": r["duration_ms"],
                "error": r["error"],
            }
            for r in self.store.runs(limit, source)
        ]


def utcnow() -> datetime:
    return datetime.now(UTC)
