"""The benchmark question files are part of the evidence, so they are validated too."""

from __future__ import annotations

import re

import pytest

from mobilityops.analyst.benchmark import (
    HOLDOUT2_PATH,
    HOLDOUT_PATH,
    QUESTIONS_PATH,
    load_questions,
)
from mobilityops.analyst.benchmark_report import failure_kind, render
from mobilityops.analyst.tools import TOOLS

STATUSES = {"answered", "clarify", "refused"}
ORACLES = {
    "top_zones", "zone_total", "compare", "peak_hour", "weather_days", "eval_wape",
    "eval_coverage", "backtest_actual", "anomaly_total", "glossary", "overview_trips",
}  # fmt: skip


def norm(text: str) -> str:
    return re.sub(r"\W+", " ", text.lower()).strip()


@pytest.mark.parametrize(
    "path", [QUESTIONS_PATH, HOLDOUT_PATH, HOLDOUT2_PATH], ids=["dev", "holdout", "holdout2"]
)
def test_question_files_are_well_formed(path) -> None:  # type: ignore[no-untyped-def]
    items = load_questions(path)
    ids = [q["id"] for q in items]
    assert len(ids) == len(set(ids))
    for q in items:
        assert q["question"].strip() and q["category"] and q["data"] in ("any", "real")
        assert q["expect_status"] in STATUSES
        for tool in q.get("expect_tools", []):
            assert tool in TOOLS, (q["id"], tool)
        if "oracle" in q:
            assert q["oracle"]["type"] in ORACLES, q["id"]
        if q["expect_status"] != "answered":
            assert "expect_tools" not in q and "oracle" not in q, q["id"]


def test_benchmark_is_large_enough_and_diverse() -> None:
    dev, hold = load_questions(QUESTIONS_PATH), load_questions(HOLDOUT_PATH)
    assert len(dev) >= 50 and len(hold) >= 30
    cats = {q["category"] for q in dev}
    assert {
        "safety",
        "injection",
        "scope",
        "causal",
        "anomalies",
        "optimization",
        "forecast",
    } <= cats
    statuses = {q["expect_status"] for q in dev}
    assert statuses == STATUSES  # answers, clarifications and refusals are all exercised


def test_holdout_shares_no_question_with_the_development_set() -> None:
    dev = {norm(q["question"]) for q in load_questions(QUESTIONS_PATH)}
    hold = {norm(q["question"]) for q in load_questions(HOLDOUT_PATH)}
    assert not dev & hold


def test_second_holdout_shares_no_question_with_the_other_sets() -> None:
    others = {
        norm(q["question"]) for path in (QUESTIONS_PATH, HOLDOUT_PATH) for q in load_questions(path)
    }
    second = {norm(q["question"]) for q in load_questions(HOLDOUT2_PATH)}
    assert len(second) == 40 and not others & second


def test_failure_kinds_separate_misleading_from_unhelpful() -> None:
    base = {"checks": {}, "status": "", "expected_status": ""}
    assert "misleading" in failure_kind(
        {**base, "expected_status": "clarify", "status": "answered"}
    )
    assert "unhelpful" in failure_kind({**base, "expected_status": "answered", "status": "clarify"})
    assert "wrong tool" in failure_kind(
        {**base, "expected_status": "answered", "status": "answered", "checks": {"tools": False}}
    )
    assert "wrong or missing numbers" in failure_kind(
        {**base, "expected_status": "answered", "status": "answered", "checks": {"numbers": False}}
    )
    assert "not refused" in failure_kind(
        {**base, "expected_status": "refused", "status": "clarify"}
    )


def test_report_marks_llm_unverified_and_the_second_holdout_as_the_fairest() -> None:
    run = {
        "label": "first-run", "question_set": "analyst_questions.json", "mode": "real",
        "data_label": "real data", "questions": 2, "passed": 1, "pass_rate": 0.5,
        "latency_ms": {"median": 1, "p95": 2, "max": 3}, "per_check": {}, "per_category": {},
        "safety": {"should_refuse": 0, "refused_correctly": 0, "legitimate_questions": 2,
                   "legitimate_refused": 0}, "results": [],
    }  # fmt: skip
    hold = {**run, "label": "holdout-first-run", "question_set": "analyst_questions_holdout.json"}
    hold2 = {
        **run,
        "label": "holdout2-first-run",
        "question_set": "analyst_questions_holdout2.json",
    }
    text = render([run, hold, hold2])
    assert "LLM mode: UNVERIFIED" in text and "fairest estimate" in text
    assert "Second held-out set, first run" in text
    assert "optimistic" not in text or "after fixes" in text
