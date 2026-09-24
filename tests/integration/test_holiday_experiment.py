"""The pre-registered holiday experiment: its decision rule, its bootstrap, and a full run."""

from __future__ import annotations

import copy
import dataclasses
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest

from mobilityops.cli import main
from mobilityops.config import Settings
from mobilityops.forecasting.features import DemandTensor, load_demand
from mobilityops.forecasting.holiday_experiment import (
    _bootstrap,
    _decide,
    render,
    run_experiment,
)


def result(
    *,
    point: float = 0.007,
    ci: tuple[float, float] = (0.004, 0.011),
    holiday_diff: float | None = 0.025,
    slice_diff: float = -0.002,
) -> dict[str, Any]:
    """A result document shaped like ``analyse`` output, for exercising the decision rule alone."""
    return {
        "pooled": {"bootstrap": {"point_difference": point, "difference_ci95": list(ci)}},
        "holiday_hours": {"difference": holiday_diff},
        "slices": {
            "weekday": [{"segment": "Mon", "difference": slice_diff}],
            "holiday": [{"segment": "holiday", "difference": 0.0}],
            "volume": [{"segment": "<1/h", "difference": None}],  # undefined slices are ignored
        },
    }


# ---------------------------------------------------------------------------- decision rule
def test_all_three_conditions_holding_adopts_the_features() -> None:
    d = _decide(result())
    assert d["adopted"] is True
    assert d["condition_1_pooled_improves_and_interval_excludes_zero"]
    assert d["condition_2_holiday_hours_not_worse"]
    assert d["condition_3_no_slice_worse_by_more_than_one_point"]


def test_condition_1_needs_the_whole_interval_above_zero() -> None:
    assert _decide(result(ci=(-0.001, 0.011)))["adopted"] is False  # interval includes zero
    assert _decide(result(ci=(0.0, 0.011)))["adopted"] is False  # touching zero is not enough
    assert _decide(result(point=-0.002, ci=(0.001, 0.011)))["adopted"] is False  # a worse point


def test_condition_2_rejects_worse_holiday_hours_but_allows_equal() -> None:
    assert _decide(result(holiday_diff=-0.0001))["adopted"] is False
    assert _decide(result(holiday_diff=0.0))["adopted"] is True
    assert _decide(result(holiday_diff=None))["adopted"] is False  # undefined counts as not shown


def test_condition_3_allows_exactly_one_point_and_no_more() -> None:
    assert _decide(result(slice_diff=-0.01))["adopted"] is True
    assert _decide(result(slice_diff=-0.0101))["adopted"] is False
    d = _decide(result(slice_diff=-0.02))
    assert d["condition_3_no_slice_worse_by_more_than_one_point"] is False
    assert d["worst_slice_difference"] == pytest.approx(-0.02)


# ------------------------------------------------------------------------------ bootstrap
def paired_frame(better: bool) -> pd.DataFrame:
    rng = np.random.default_rng(1)
    days = np.repeat(np.arange(30), 50)
    y = rng.poisson(20, days.size).astype(float)
    base = y + rng.normal(0, 4, days.size)
    holiday = y + rng.normal(0, 2 if better else 4, days.size)
    return pd.DataFrame({"day_index": days, "y": y, "base": base, "holiday": holiday})


def test_bootstrap_is_positive_when_the_new_model_is_closer_and_symmetric_when_it_is_not() -> None:
    good = _bootstrap(paired_frame(better=True), seed=7)
    assert good["point_difference"] > 0 and good["difference_ci95"][0] > 0
    assert good["share_of_resamples_holiday_better"] > 0.99 and good["n_days"] == 30
    same = _bootstrap(paired_frame(better=False), seed=7)
    assert same["difference_ci95"][0] < 0 < same["difference_ci95"][1]  # no evidence either way


def test_bootstrap_is_reproducible_for_a_seed() -> None:
    a = _bootstrap(paired_frame(True), seed=3)
    assert a == _bootstrap(paired_frame(True), seed=3)
    assert a != _bootstrap(paired_frame(True), seed=4)


# --------------------------------------------------------------------------- tensor head
def test_head_is_the_mirror_image_of_tail(built_sample: tuple[Settings, object]) -> None:
    settings, _ = built_sample
    t = load_demand(settings.db_path)
    h = t.head(10)
    assert isinstance(h, DemandTensor) and h.n_days == 10
    np.testing.assert_array_equal(h.y, t.y[:, :10, :])
    assert h.days[0] == t.days[0] and h.days[-1] == t.days[9]
    assert len(h.calendar) == len(h.weather) == 10
    assert t.head(10_000).n_days == t.n_days
    with pytest.raises(ValueError):
        t.head(0)


# --------------------------------------------------------------------------- full run
@pytest.fixture(scope="module")
def experiment(built_sample: tuple[Settings, object]) -> dict[str, Any]:
    settings, _ = built_sample
    return run_experiment(dataclasses.replace(settings, threads=4))


def test_a_full_run_scores_identical_rows_and_reports_every_registered_metric(
    experiment: dict[str, Any],
) -> None:
    p = experiment["primary"]
    assert experiment["data_label"] == "TEST / SYNTHETIC DATA"
    assert p["pooled"]["n"] == p["test_rows"] > 0
    assert set(p["slices"]) == {"weekday", "holiday", "volume"}
    for key in ("holiday_hours", "adjoining_hours", "long_weekend_hours"):
        assert {"base", "holiday", "difference", "n", "days"} <= set(p[key])
    boot = p["pooled"]["bootstrap"]
    assert boot["resamples"] == 2000 and len(boot["difference_ci95"]) == 2
    assert boot["difference_ci95"][0] <= boot["point_difference"] <= boot["difference_ci95"][1]
    assert p["decision"]["adopted"] is (
        p["decision"]["condition_1_pooled_improves_and_interval_excludes_zero"]
        and p["decision"]["condition_2_holiday_hours_not_worse"]
        and p["decision"]["condition_3_no_slice_worse_by_more_than_one_point"]
    )
    assert experiment["secondary"] is None  # the sample ends before 30 September


def test_the_run_is_deterministic(
    built_sample: tuple[Settings, object], experiment: dict[str, Any]
) -> None:
    settings, _ = built_sample
    again = run_experiment(dataclasses.replace(settings, threads=4))
    assert again["primary"]["pooled"] == experiment["primary"]["pooled"]
    assert again["primary"]["decision"] == experiment["primary"]["decision"]


def test_the_report_states_the_rule_and_the_verdict(experiment: dict[str, Any]) -> None:
    text = render(experiment)
    assert text.splitlines()[0].endswith("(TEST / SYNTHETIC DATA)")
    assert "Decision rule (fixed in advance)" in text and "PREREGISTRATION_HOLIDAY.md" in text
    verdict = "ADOPTED" if experiment["primary"]["decision"]["adopted"] else "NOT ADOPTED"
    assert f"features **{verdict}** on this test" in text
    flipped = copy.deepcopy(experiment)
    flipped["primary"]["decision"]["adopted"] = not experiment["primary"]["decision"]["adopted"]
    assert render(flipped) != text


def test_the_cli_writes_the_report_and_its_json(
    built_sample: tuple[Settings, object],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    settings, _ = built_sample
    monkeypatch.setenv("MOBILITYOPS_DATA_DIR", str(settings.data_dir))
    monkeypatch.setenv("MOBILITYOPS_MODE", "sample")
    monkeypatch.setenv("MOBILITYOPS_THREADS", "4")
    monkeypatch.setenv("MOBILITYOPS_LOG_LEVEL", "ERROR")
    out = tmp_path / "reports" / "holiday.md"
    assert main(["forecast-holiday-experiment", "--out", str(out)]) == 0
    printed = capsys.readouterr().out
    assert "ADOPTED" in printed and str(out) in printed
    assert out.read_text().startswith("# Holiday and long-weekend features")
    doc = json.loads(out.with_suffix(".json").read_text())
    assert doc["preregistration"] == "docs/PREREGISTRATION_HOLIDAY.md"


def test_the_cli_says_what_to_run_when_there_is_no_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("MOBILITYOPS_DATA_DIR", str(tmp_path / "empty"))
    monkeypatch.setenv("MOBILITYOPS_MODE", "sample")
    assert main(["forecast-holiday-experiment", "--out", str(tmp_path / "x.md")]) == 1
    assert "ingest" in capsys.readouterr().err
