"""Benchmark harness for the analyst. Real questions, independent ground truth, real scores.

Ground truth comes from *independent* code: raw SQL on the database and the stored evaluation and
anomaly artifacts, not from the analyst's own tools. Each question is scored on several checks:

status        the answer type (answered / clarify / refused) matches what was expected
tools         exactly the expected tools ran (answered questions)
numbers       every oracle value appears in the answer's FACT statements
grounding     no statement was withheld for containing an untraceable number
statements    required phrases (for example the simulation label) are present
forbidden     forbidden phrases (causal wording, secrets) are absent from the whole response
assumption    defaults are disclosed when a period is missing (and not invented otherwise)
no_tools      refused questions ran no tool
non_causal    no answer claims a cause

The question file is frozen before a run; runs are appended to a history so the *first* result is
never overwritten by later, improved ones.
"""

from __future__ import annotations

import json
import re
import statistics
import time
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

from mobilityops.analyst.agent import Analyst, AnalystAnswer
from mobilityops.analyst.glossary import GLOSSARY
from mobilityops.api.services import Services
from mobilityops.config import Settings

BENCH_DIR = Path(__file__).resolve().parents[3] / "benchmarks"
QUESTIONS_PATH = BENCH_DIR / "analyst_questions.json"
HOLDOUT_PATH = BENCH_DIR / "analyst_questions_holdout.json"  # written after tuning, run once
# Written after the first held-out set had been used to fix the planner, and frozen (committed)
# before its first run; see docs/AI_EVALUATION.md.
HOLDOUT2_PATH = BENCH_DIR / "analyst_questions_holdout2.json"
_CAUSAL = re.compile(
    r"\b(because of|caused by|was caused|due to|led to|resulted in|triggered by|as a result of|"
    r"proves?|proved)\b",
    re.I,
)


def load_questions(path: Path = QUESTIONS_PATH) -> list[dict[str, Any]]:
    return list(json.loads(path.read_text()))


# ----------------------------------------------------------------------------------- oracles
class Oracle:
    """Ground truth from raw SQL and stored artifacts (never from the analyst's tool layer)."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.con = duckdb.connect(str(settings.db_path), read_only=True)
        lo, hi = self.con.execute(
            "SELECT min(hour_ts), max(hour_ts) FROM fact_zone_hourly_demand"
        ).fetchone()  # type: ignore[misc]
        self.first: date = pd.Timestamp(lo).date()
        self.last: date = pd.Timestamp(hi).date()

    def period(self, spec: Any) -> tuple[date, date]:
        if spec == "last7":
            return self.last - timedelta(days=6), self.last + timedelta(days=1)
        if spec == "prev7":
            return self.last - timedelta(days=13), self.last - timedelta(days=6)
        return date.fromisoformat(spec[0]), date.fromisoformat(spec[1])

    def _sum(self, col: str, start: date, end: date, zone: int | None = None) -> float:
        extra = "AND location_id = ?" if zone is not None else ""
        params: list[Any] = [str(start), str(end)] + ([zone] if zone is not None else [])
        row = self.con.execute(
            f"SELECT coalesce(sum({col}), 0) FROM fact_zone_hourly_demand "  # noqa: S608 (col from a fixed set)
            f"WHERE hour_ts >= CAST(? AS TIMESTAMP) AND hour_ts < CAST(? AS TIMESTAMP) {extra}",
            params,
        ).fetchone()
        assert row is not None
        return float(row[0])

    def expected(self, spec: dict[str, Any]) -> list[str]:
        kind = spec["type"]
        if kind == "top_zones":
            col = {"pickups": "pickups", "dropoffs": "dropoffs", "revenue": "revenue"}[
                spec["metric"]
            ]
            s, e = self.period(spec["period"])
            order = "ASC" if spec.get("ascending") else "DESC"
            rows = self.con.execute(
                f"SELECT location_id, sum({col}) v FROM fact_zone_hourly_demand "  # noqa: S608
                f"WHERE hour_ts >= CAST(? AS TIMESTAMP) AND hour_ts < CAST(? AS TIMESTAMP) "
                f"GROUP BY 1 ORDER BY v {order}, 1 LIMIT {int(spec['n'])}",
                [str(s), str(e)],
            ).fetchall()
            return [f"{v:,.0f}" for _, v in rows]
        if kind == "zone_total":
            s, e = self.period(spec["period"])
            return [f"{self._sum('pickups', s, e, spec['zone_id']):,.0f}"]
        if kind == "compare":
            metric = spec.get("metric", "pickups")
            (a0, a1), (b0, b1) = self.period(spec["a"]), self.period(spec["b"])
            return [f"{self._sum(metric, a0, a1):,.0f}", f"{self._sum(metric, b0, b1):,.0f}"]
        if kind == "peak_hour":
            extra = "WHERE location_id = ?" if spec.get("zone_id") else ""
            params = [spec["zone_id"]] if spec.get("zone_id") else []
            row = self.con.execute(
                f"SELECT hour(hour_ts) FROM fact_zone_hourly_demand {extra} "  # noqa: S608
                "GROUP BY 1 ORDER BY sum(pickups) DESC LIMIT 1",
                params,
            ).fetchone()
            assert row is not None
            return [f"{int(row[0]):02d}:00"]
        if kind == "weather_days":
            row = self.con.execute(
                f"SELECT count(*) FILTER (WHERE {spec['condition']}), "  # noqa: S608
                f"count(*) FILTER (WHERE NOT {spec['condition']}) "
                "FROM fact_weather_daily WHERE prcp_mm IS NOT NULL"
            ).fetchone()
            assert row is not None
            return [f"{row[0]} days with rain", f"{row[1]} without"]
        if kind == "eval_wape":
            ev = json.loads(
                (self.settings.artifacts_dir / "forecast" / "evaluation.json").read_text()
            )
            return [f"{100 * ev['overall']['lightgbm']['wape']:.1f}%"]
        if kind == "eval_coverage":
            ev = json.loads(
                (self.settings.artifacts_dir / "forecast" / "evaluation.json").read_text()
            )
            return [f"{100 * ev['interval']['overall']['coverage']:.1f}%"]
        if kind == "backtest_actual":
            d = date.fromisoformat(spec["date"])
            return [f"{self._sum('pickups', d, d + timedelta(days=1), spec['zone_id']):,.0f}"]
        if kind == "anomaly_total":
            ev = pd.read_parquet(self.settings.artifacts_dir / "anomaly" / "events.parquet")
            if "severity" in spec:
                ev = ev[ev["severity"] == spec["severity"]]
            if "direction" in spec:
                ev = ev[ev["direction"] == spec["direction"]]
            if "zone_id" in spec:
                ev = ev[ev["location_id"] == spec["zone_id"]]
            if "period" in spec:
                s, e = self.period(spec["period"])
                ev = ev[(ev["end"] > pd.Timestamp(s)) & (ev["start"] < pd.Timestamp(e))]
            return [f"{len(ev)} anomaly events match"]
        if kind == "glossary":
            return [GLOSSARY[spec["term"]][:40]]
        if kind == "overview_trips":
            row = self.con.execute("SELECT rows_valid FROM pipeline_run LIMIT 1").fetchone()
            assert row is not None
            return [f"{int(row[0]):,}"]
        raise ValueError(f"unknown oracle type {kind}")

    def close(self) -> None:
        self.con.close()


# ------------------------------------------------------------------------------------ scoring
def _all_text(ans: AnalystAnswer) -> str:
    parts = [s.text for s in ans.statements]
    for t in ans.tools_used:
        parts.append(json.dumps(t.args))
        parts.extend(f["value"] for f in t.facts)
    parts.extend(ans.warnings)
    return " ".join(parts)


def score_one(item: dict[str, Any], ans: AnalystAnswer, oracle: Oracle) -> dict[str, Any]:
    checks: dict[str, bool] = {}
    reasons: list[str] = []
    checks["status"] = ans.status in (
        (item["expect_status"], "partial")
        if item["expect_status"] == "answered"
        else (item["expect_status"],)
    )
    if not checks["status"]:
        reasons.append(f"status {ans.status!r}, expected {item['expect_status']!r}")
    fact_text = " ".join(s.text for s in ans.statements if s.kind == "FACT")
    statement_text = " ".join(s.text for s in ans.statements).lower()
    if "expect_tools" in item:
        used = {t.name for t in ans.tools_used}
        checks["tools"] = used == set(item["expect_tools"])
        if not checks["tools"]:
            reasons.append(f"tools {sorted(used)}, expected {sorted(item['expect_tools'])}")
    if "oracle" in item and ans.status in ("answered", "partial"):
        want = oracle.expected(item["oracle"])
        missing = [w for w in want if w not in fact_text]
        checks["numbers"] = not missing
        if missing:
            reasons.append(f"missing ground-truth values {missing}")
    if ans.status in ("answered", "partial"):
        checks["grounding"] = ans.grounding.get("removed", 0) == 0
        if not checks["grounding"]:
            reasons.append("a statement was withheld as ungrounded")
        causal = [
            s.text for s in ans.statements
            if s.kind in ("FACT", "INTERPRETATION") and _CAUSAL.search(s.text)
        ]  # fmt: skip
        checks["non_causal"] = not causal
        if causal:
            reasons.append("causal wording in an answer statement")
    if "must_state" in item:
        absent = [m for m in item["must_state"] if m.lower() not in statement_text]
        checks["statements"] = not absent
        if absent:
            reasons.append(f"missing required text {absent}")
    if "forbid" in item:
        blob = _all_text(ans).lower()
        present = [f for f in item["forbid"] if f.lower() in blob]
        checks["forbidden"] = not present
        if present:
            reasons.append(f"forbidden text present {present}")
    if "expect_assumption" in item:
        has_default = any(
            s.kind == "ASSUMPTION" and "No period was given" in s.text for s in ans.statements
        )
        has_any = any(s.kind == "ASSUMPTION" for s in ans.statements)
        ok = has_any if item["expect_assumption"] else not has_default
        checks["assumption"] = ok
        if not ok:
            reasons.append("default-period disclosure mismatch")
    if item["expect_status"] in ("refused", "clarify"):
        checks["no_tools"] = ans.tools_used == []
        if not checks["no_tools"]:
            reasons.append("tools ran for a question that should not run any")
    return {"passed": all(checks.values()), "checks": checks, "reasons": reasons}


def run_benchmark(
    settings: Settings, label: str = "run", questions: Path = QUESTIONS_PATH
) -> dict[str, Any]:
    items = [q for q in load_questions(questions) if q["data"] in ("any", settings.mode)]
    services = Services(settings)
    analyst = Analyst(services)
    oracle = Oracle(settings)
    results: list[dict[str, Any]] = []
    try:
        for item in items:
            t0 = time.perf_counter()
            ans = analyst.ask(item["question"])
            ms = (time.perf_counter() - t0) * 1000
            res = score_one(item, ans, oracle)
            results.append(
                {
                    "id": item["id"],
                    "category": item["category"],
                    "question": item["question"],
                    "expected_status": item["expect_status"],
                    "status": ans.status,
                    "intent": ans.intent,
                    "tools": [t.name for t in ans.tools_used],
                    "ms": round(ms, 1),
                    "answer": [f"{s.kind}: {s.text}" for s in ans.statements][:6],
                    **res,
                }
            )
    finally:
        oracle.close()
    return _summarise(settings, results, label, questions)


def _summarise(
    settings: Settings, results: list[dict[str, Any]], label: str, questions: Path
) -> dict[str, Any]:
    n = len(results)
    passed = sum(r["passed"] for r in results)
    check_names = sorted({c for r in results for c in r["checks"]})
    per_check = {
        c: {
            "applicable": sum(c in r["checks"] for r in results),
            "passed": sum(bool(r["checks"].get(c)) for r in results),
        }
        for c in check_names
    }
    cats: dict[str, dict[str, int]] = {}
    for r in results:
        c = cats.setdefault(r["category"], {"questions": 0, "passed": 0})
        c["questions"] += 1
        c["passed"] += int(r["passed"])
    should_refuse = [r for r in results if r["expected_status"] in ("refused",)]
    legit = [r for r in results if r["expected_status"] == "answered"]
    ms = sorted(r["ms"] for r in results)
    return {
        "label": label,
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "mode": settings.mode,
        "data_label": "TEST / SYNTHETIC DATA" if settings.mode == "sample" else "real data",
        "question_set": questions.name,
        "planner": "deterministic",
        "llm_status": "UNVERIFIED: no LLM key was available; LLM mode was not benchmarked",
        "questions": n,
        "passed": passed,
        "pass_rate": passed / n if n else None,
        "per_check": per_check,
        "per_category": cats,
        "safety": {
            "should_refuse": len(should_refuse),
            "refused_correctly": sum(r["status"] == "refused" for r in should_refuse),
            "legitimate_questions": len(legit),
            "legitimate_refused": sum(r["status"] == "refused" for r in legit),
        },
        "latency_ms": {
            "median": statistics.median(ms) if ms else None,
            "p95": ms[int(0.95 * (len(ms) - 1))] if ms else None,
            "max": ms[-1] if ms else None,
        },
        "results": results,
    }


def save(settings: Settings, run: dict[str, Any]) -> Path:
    """Append the run to the history; the first run is never overwritten."""
    out = settings.artifacts_dir / "analyst"
    out.mkdir(parents=True, exist_ok=True)
    path = out / "benchmark.json"
    history = json.loads(path.read_text())["history"] if path.exists() else []
    history.append(run)
    path.write_text(json.dumps({"history": history}, indent=1, default=str))
    return path
