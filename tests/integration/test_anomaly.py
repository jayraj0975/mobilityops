"""Anomaly detection end to end on the TEST / SYNTHETIC sample, scored against planted truth."""

from __future__ import annotations

import json

import pandas as pd
import pytest

from mobilityops.anomaly.run import load_predictions, run_anomaly_detection
from mobilityops.forecasting.evaluate import run_evaluation


@pytest.fixture(scope="module")
def sample_report(built_sample):  # type: ignore[no-untyped-def]
    """Forecast on the default 3x7-day walk-forward folds (covers all planted days), then detect."""
    settings, _ = built_sample
    run_evaluation(settings, oracle_experiment=False)
    return settings, run_anomaly_detection(settings)


def test_every_planted_anomaly_is_found_with_no_extra_events(sample_report) -> None:  # type: ignore[no-untyped-def]
    _, rep = sample_report
    truth = rep["planted_truth"]
    assert truth["planted"] == 3
    assert truth["found"] == 3 and truth["recall"] == 1.0
    assert truth["events_not_planted"] == 0
    kinds = {(d["zone"], d["kind"]) for d in truth["details"]}
    assert kinds == {(3, "surge"), (7, "drop"), (5, "surge")}


def test_report_is_labelled_and_artifacts_written(sample_report) -> None:  # type: ignore[no-untyped-def]
    settings, rep = sample_report
    assert rep["data_label"] == "TEST / SYNTHETIC DATA"
    assert "planted ground truth" in rep["accuracy_status"]
    assert "SEMI-SYNTHETIC" in rep["injection_experiment"]["label"]
    out = settings.artifacts_dir / "anomaly"
    events = pd.read_parquet(out / "events.parquet")
    assert len(events) == rep["events_total"] == 3
    saved = json.loads((out / "report.json").read_text())
    assert saved["scored_zone_hours"] == rep["scored_zone_hours"]
    assert {r["event_threshold"] for r in rep["threshold_sensitivity"]} == {4.0, 5.0, 6.0}


def test_events_carry_context_and_non_causal_explanations(sample_report) -> None:  # type: ignore[no-untyped-def]
    settings, _ = sample_report
    events = pd.read_parquet(settings.artifacts_dir / "anomaly" / "events.parquet")
    assert set(events["scope"]) <= {"localised", "partly shared", "city-wide"}
    # the planted drop and the zone-5 surge touch one zone only; the zone-3 surge falls on an
    # evening when forecast errors were also positive elsewhere, so it is honestly "partly shared"
    by_zone = events.set_index("location_id")["scope"]
    assert by_zone[7] == "localised" and by_zone[5] == "localised"
    for text in events["explanation"]:
        assert "not a cause" in text and "forecast" in text


def test_lower_thresholds_never_find_fewer_events(sample_report) -> None:  # type: ignore[no-untyped-def]
    _, rep = sample_report
    counts = [
        r["events"]
        for r in sorted(rep["threshold_sensitivity"], key=lambda r: r["event_threshold"])
    ]
    assert counts == sorted(counts, reverse=True)


def test_detection_is_deterministic(sample_report) -> None:  # type: ignore[no-untyped-def]
    settings, first = sample_report
    again = run_anomaly_detection(settings, injection=False)
    assert again["events_total"] == first["events_total"]
    assert again["planted_truth"]["found"] == first["planted_truth"]["found"]


def test_detection_without_forecasts_is_a_clear_error(sample_settings) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(FileNotFoundError, match="forecast-eval"):
        load_predictions(sample_settings)
