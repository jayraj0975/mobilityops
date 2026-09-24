"""Building the Pune database end to end (weather is injected; nothing touches the network)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import pytest

from mobilityops.config import Settings
from mobilityops.forecasting.features import load_demand
from mobilityops.pune import build as pb
from mobilityops.pune import simulate as sim
from mobilityops.quality.checks import QualityGateError

WINDOW = (date(2026, 8, 24), date(2026, 10, 5))  # 42 days, includes Ganesh Chaturthi (14 Sep)


def _weather(window: tuple[date, date] = WINDOW) -> pd.DataFrame:
    hours = pd.date_range(
        pd.Timestamp(window[0]), pd.Timestamp(window[1]), freq="h", inclusive="left"
    )
    rng = np.random.default_rng(0)
    rain = np.where(rng.random(len(hours)) < 0.05, rng.uniform(0.2, 4.0, len(hours)), 0.0)
    return pd.DataFrame(
        {
            "hour_ts": hours,
            "temperature_2m": 26.0 + 4 * np.sin(np.arange(len(hours)) / 24 * 2 * np.pi),
            "precipitation": rain,
            "relative_humidity_2m": 80.0,
        }
    )


@pytest.fixture()
def settings(tmp_path: Path) -> Settings:
    return Settings.from_env(
        {"MOBILITYOPS_DATA_DIR": str(tmp_path / "data"), "MOBILITYOPS_MODE": "pune"}
    )


def test_build_produces_a_labelled_gated_database(settings: Settings) -> None:
    res = pb.build_pune(settings, WINDOW, weather=_weather())
    assert res.report.overall.value == "PASS" and res.zones == 91
    con = duckdb.connect(str(settings.db_path), read_only=True)
    try:
        run = con.execute("SELECT mode, synthetic, rows_valid FROM pipeline_run").fetchone()
        assert run == ("pune", True, res.trips)
        rows = con.execute("SELECT count(*) FROM fact_zone_hourly_demand").fetchone()
        assert rows == (91 * 42 * 24,)
        holidays = con.execute("SELECT date FROM dim_date WHERE is_holiday").fetchall()
        assert holidays
        assert con.execute("SELECT count(*) FROM sim_events").fetchone() == (8,)
        checks = {
            r[0]: r[1] for r in con.execute('SELECT "check", status FROM quality_result').fetchall()
        }
    finally:
        con.close()
    assert checks["demand_is_simulated"] == "PASS" and set(checks.values()) == {"PASS"}


def test_rebuild_is_deterministic(settings: Settings) -> None:
    a = pb.build_pune(settings, WINDOW, weather=_weather())
    con = duckdb.connect(str(settings.db_path), read_only=True)
    first = con.execute(
        "SELECT sum(pickups), sum(pickups * hour(hour_ts)) FROM fact_zone_hourly_demand"
    ).fetchone()
    con.close()
    b = pb.build_pune(settings, WINDOW, weather=_weather())
    con = duckdb.connect(str(settings.db_path), read_only=True)
    second = con.execute(
        "SELECT sum(pickups), sum(pickups * hour(hour_ts)) FROM fact_zone_hourly_demand"
    ).fetchone()
    con.close()
    assert a.trips == b.trips and first == second


def test_the_forecasting_tensor_uses_pune_holidays_and_no_dst(settings: Settings) -> None:
    pb.build_pune(settings, WINDOW, weather=_weather())
    t = load_demand(settings.db_path, settings.city)
    assert t.n_zones == 91 and t.n_days == 42 and not np.isnan(t.y).any()
    ganesh = list(t.days).index(pd.Timestamp("2026-09-14"))
    assert bool(t.calendar["is_holiday"].iloc[ganesh])
    assert t.city.key == "pune"
    assert t.extended(1).calendar.shape[0] == 43


def test_a_failed_gate_keeps_the_previous_database(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    pb.build_pune(settings, WINDOW, weather=_weather())
    before = settings.db_path.read_bytes()
    real = sim.simulate_range

    def broken(*args, **kwargs):  # type: ignore[no-untyped-def]
        df = real(*args, **kwargs)
        df.loc[df.index[0], "dropoffs"] += 5  # dropoffs no longer reconcile with pickups
        return df

    monkeypatch.setattr(pb.simulate, "simulate_range", broken)
    with pytest.raises(QualityGateError, match="dropoffs_reconcile"):
        pb.build_pune(settings, WINDOW, weather=_weather())
    assert settings.db_path.read_bytes() == before
    assert not pb.building_path(settings).exists()


def test_missing_rain_days_warn_but_do_not_block(settings: Settings) -> None:
    w = _weather()
    w.loc[w["hour_ts"].dt.date.isin([date(2026, 9, 1), date(2026, 9, 2)]), "precipitation"] = np.nan
    res = pb.build_pune(settings, WINDOW, weather=w)
    cov = next(r for r in res.report.results if r.name == "weather_coverage")
    assert cov.status.value == "PASS" and cov.metrics["coverage"] == pytest.approx(40 / 42)


def test_pune_build_refuses_other_modes_and_short_windows(tmp_path: Path) -> None:
    real = Settings.from_env({"MOBILITYOPS_DATA_DIR": str(tmp_path), "MOBILITYOPS_MODE": "real"})
    with pytest.raises(ValueError, match="MOBILITYOPS_MODE=pune"):
        pb.build_pune(real, WINDOW, weather=_weather())
    pune = Settings.from_env({"MOBILITYOPS_DATA_DIR": str(tmp_path), "MOBILITYOPS_MODE": "pune"})
    with pytest.raises(ValueError, match="28 days"):
        pb.build_pune(pune, (date(2026, 9, 1), date(2026, 9, 10)), weather=_weather())


def test_daily_weather_needs_a_complete_day() -> None:
    w = _weather()
    w.loc[w["hour_ts"] == pd.Timestamp("2026-09-01 05:00"), "precipitation"] = np.nan
    d = pb.daily_weather(w).set_index("date")
    assert np.isnan(d.loc["2026-09-01", "prcp_mm"]) and not np.isnan(d.loc["2026-09-02", "prcp_mm"])
    assert d["snow_mm"].eq(0.0).all()


def test_default_window_leaves_the_incomplete_archive_tail() -> None:
    start, end = pb.default_window(date(2026, 9, 24))
    assert end == date(2026, 9, 17) and (end - start).days == 365


def test_cached_weather_is_reused_and_records_provenance(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[int] = []

    def fake_fetch(client, lat, lon, start, end):  # type: ignore[no-untyped-def]
        calls.append(1)
        return _weather((start, end + pd.Timedelta(days=1).to_pytimedelta()))

    monkeypatch.setattr(pb.openmeteo, "fetch_archive", fake_fetch)
    first = pb.load_or_fetch_weather(settings, WINDOW)
    again = pb.load_or_fetch_weather(settings, WINDOW)
    assert calls == [1] and len(first) == len(again)
    prov = (settings.raw_dir / pb.PROVENANCE_FILE).read_text()
    assert "ERA5" in prov and "HISTORICAL" in prov
    pb.load_or_fetch_weather(settings, WINDOW, refresh=True)
    assert len(calls) == 2
