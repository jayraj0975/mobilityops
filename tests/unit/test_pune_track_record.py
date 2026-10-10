"""The forecast track record: only forecasts made before their hour are scored, against a
same-hour-last-week baseline on the same zone-hours."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import pytest

from mobilityops.config import Settings
from mobilityops.pune.state import StateService
from mobilityops.pune.store import StateStore

NOW = datetime(2026, 9, 24, 12, 0, tzinfo=UTC)  # 17:30 in Pune


@pytest.fixture()
def service(tmp_path: Path) -> StateService:
    s = Settings.from_env(
        {"MOBILITYOPS_DATA_DIR": str(tmp_path / "data"), "MOBILITYOPS_MODE": "pune"}
    )
    return StateService(s, StateStore(tmp_path / "state.sqlite"))


def _actuals(store: StateStore, rows: list[tuple[int, str, int]]) -> None:
    frame = pd.DataFrame(
        {
            "location_id": [r[0] for r in rows],
            "hour_ts": pd.to_datetime([r[1] for r in rows]),
            "pickups": [r[2] for r in rows],
            "dropoffs": [0] * len(rows),
        }
    )
    store.put_zone_hours(frame, partial_hour=None, now=NOW)


def _forecast(
    store: StateStore, rows: list[tuple[int, str, float, float, float]], made_utc: datetime
) -> None:
    frame = pd.DataFrame(
        {
            "location_id": [r[0] for r in rows],
            "hour_ts": pd.to_datetime([r[1] for r in rows]),
            "pred": [r[2] for r in rows],
            "lo": [r[3] for r in rows],
            "hi": [r[4] for r in rows],
        }
    )
    store.put_forecast(frame, "m1", made_utc)


def test_scores_only_forecasts_made_before_their_hour(service: StateService) -> None:
    st = service.store
    _actuals(
        st,
        [
            (1, "2026-09-23 10:00", 10),
            (1, "2026-09-23 11:00", 20),  # the day being scored
            (1, "2026-09-16 10:00", 6),
            (1, "2026-09-16 11:00", 26),  # same hours a week earlier
            (2, "2026-09-24 09:00", 30),
        ],
    )  # today, forecast too late
    # Made at local midnight on the 23rd (18:30 UTC the day before): 10 and 11 hours ahead.
    _forecast(
        st,
        [(1, "2026-09-23 10:00", 12, 8, 14), (1, "2026-09-23 11:00", 18, 15, 19)],
        datetime(2026, 9, 22, 18, 30, tzinfo=UTC),
    )
    # Rebuilt after a restart at 17:30 local: it already "knew" 09:00, so it must not be graded.
    _forecast(st, [(2, "2026-09-24 09:00", 30, 29, 31)], NOW)

    tr = service.track_record(NOW, days=14)
    assert tr["excluded_late"] == 1 and "SIMULATED" in tr["data_label"]
    [day] = tr["days"]
    assert str(day["day"]) == "2026-09-23"
    assert day == day | {
        "zone_hours": 2,
        "mae": 2.0,
        "baseline_mae": 5.0,
        "mae_on_baseline_hours": 2.0,
        "baseline_zone_hours": 2,
        "coverage": 0.5,
        "bias": 0.0,
        "lead_hours_median": 10.5,
    }
    assert tr["total"]["zone_hours"] == 2


def test_baseline_is_compared_on_the_same_zone_hours_only(service: StateService) -> None:
    st = service.store
    _actuals(
        st, [(1, "2026-09-23 10:00", 10), (1, "2026-09-23 11:00", 20), (1, "2026-09-16 10:00", 6)]
    )
    _forecast(
        st,
        [(1, "2026-09-23 10:00", 12, 8, 14), (1, "2026-09-23 11:00", 30, 15, 19)],
        datetime(2026, 9, 22, 18, 30, tzinfo=UTC),
    )
    t = service.track_record(NOW)["total"]
    assert t["mae"] == 6.0  # (2 + 10) / 2 over all scored hours
    assert (
        t["baseline_zone_hours"] == 1
        and t["baseline_mae"] == 4.0
        and t["mae_on_baseline_hours"] == 2.0
    )


def test_nothing_to_score_is_an_empty_record_not_an_error(service: StateService) -> None:
    tr = service.track_record(NOW)
    assert tr["days"] == [] and tr["total"] is None and tr["excluded_late"] == 0
