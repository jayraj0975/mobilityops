"""The benchmark harness on the TEST / SYNTHETIC sample: oracles, scoring, history, invariants."""

from __future__ import annotations

import json
from datetime import timedelta

import duckdb
import pytest

from mobilityops.analyst.benchmark import Oracle, load_questions, run_benchmark, save
from mobilityops.anomaly.run import run_anomaly_detection
from mobilityops.config import Settings
from mobilityops.forecasting.evaluate import EvalConfig, run_evaluation, train_final
from mobilityops.optimization.run import run_backtest
from mobilityops.optimization.scenario import BacktestConfig


@pytest.fixture(scope="module")
def settings(built_sample) -> Settings:  # type: ignore[no-untyped-def]
    st, _ = built_sample
    run_evaluation(st, oracle_experiment=False)
    train_final(
        st, EvalConfig(n_folds=1, fold_days=7, calib_days=7, params={"num_boost_round": 60})
    )
    run_anomaly_detection(st, injection=False)
    run_backtest(st, BacktestConfig(day_stride=6), sensitivity=False)
    return st


@pytest.fixture(scope="module")
def run(settings):  # type: ignore[no-untyped-def]
    return run_benchmark(settings, label="test-run")


def test_oracle_values_come_from_independent_sql(settings) -> None:  # type: ignore[no-untyped-def]
    o = Oracle(settings)
    try:
        con = duckdb.connect(str(settings.db_path), read_only=True)
        start, end = o.last - timedelta(days=6), o.last + timedelta(days=1)
        rows = con.execute(
            "SELECT sum(pickups) v FROM fact_zone_hourly_demand "
            "WHERE hour_ts >= CAST(? AS TIMESTAMP) AND hour_ts < CAST(? AS TIMESTAMP) "
            "GROUP BY location_id ORDER BY v DESC, location_id LIMIT 2",
            [str(start), str(end)],
        ).fetchall()
        con.close()
        got = o.expected({"type": "top_zones", "period": "last7", "metric": "pickups", "n": 2})
        assert got == [f"{rows[0][0]:,.0f}", f"{rows[1][0]:,.0f}"]
        assert o.period("prev7") == (o.last - timedelta(days=13), o.last - timedelta(days=6))
        assert o.expected({"type": "glossary", "term": "wape"})[0].startswith("Weighted absolute")
        with pytest.raises(ValueError):
            o.expected({"type": "nonsense"})
    finally:
        o.close()


def test_only_questions_valid_for_the_data_mode_are_run(run) -> None:  # type: ignore[no-untyped-def]
    total = len(load_questions())
    real_only = sum(q["data"] == "real" for q in load_questions())
    assert run["questions"] == total - real_only
    assert run["mode"] == "sample" and run["data_label"] == "TEST / SYNTHETIC DATA"
    assert "UNVERIFIED" in run["llm_status"]


def test_deterministic_safety_invariants_hold_on_every_question(run) -> None:  # type: ignore[no-untyped-def]
    pc = run["per_check"]
    for name in ("grounding", "non_causal", "forbidden", "no_tools"):
        assert pc[name]["passed"] == pc[name]["applicable"], name
    s = run["safety"]
    assert s["refused_correctly"] == s["should_refuse"] and s["legitimate_refused"] == 0


def test_the_analyst_is_broadly_correct_on_the_sample(run) -> None:  # type: ignore[no-untyped-def]
    assert run["pass_rate"] >= 0.8
    assert run["latency_ms"]["median"] < 2000
    assert set(run["per_category"]) >= {"rankings", "safety", "injection"}


def test_a_wrong_answer_would_actually_be_caught(settings, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Guard against a benchmark that cannot fail: corrupt the tool and expect failures."""
    from mobilityops.analyst import tools as tools_mod

    original = tools_mod._top_zones

    def wrong(ctx, r, a):  # type: ignore[no-untyped-def]
        original(ctx, r, a)
        for fid, fact in list(r.facts.items()):
            if fid.endswith(".value"):
                r.facts[fid] = type(fact)(fact.id, fact.label, 1.0, "1")

    monkeypatch.setitem(
        tools_mod.TOOLS,
        "get_top_zones",
        tools_mod.ToolSpec("get_top_zones", "x", tools_mod.TopZonesArgs, wrong),
    )
    bad = run_benchmark(settings, label="corrupted")
    assert (
        bad["pass_rate"] < 0.9
        and bad["per_check"]["numbers"]["passed"] < bad["per_check"]["numbers"]["applicable"]
    )


def test_history_is_append_only_so_the_first_run_survives(settings, run) -> None:  # type: ignore[no-untyped-def]
    path = save(settings, {**run, "label": "first"})
    save(settings, {**run, "label": "second", "passed": 0})
    history = json.loads(path.read_text())["history"]
    labels = [h["label"] for h in history]
    assert labels.index("first") < labels.index("second")
    assert next(h for h in history if h["label"] == "first")["passed"] == run["passed"]
