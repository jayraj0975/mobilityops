"""The documents quote numbers from the generated reports; they must not drift apart.

These read only committed files, so they run in CI. If a report is regenerated with new results,
update the prose in README.md and docs/EVALUATION.md (this test tells you which number moved).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
README = (REPO / "README.md").read_text()
EVAL = (REPO / "docs" / "EVALUATION.md").read_text()
AI = (REPO / "docs" / "AI_EVALUATION.md").read_text()


def report(name: str) -> str:
    return (REPO / "reports" / name).read_text()


def wape_row(md: str, label: str) -> str:
    row = next(line for line in md.splitlines() if line.startswith(f"| {label}"))
    return row.split("|")[4].strip()  # Model | MAE | RMSE | WAPE | Bias


def test_forecast_numbers_in_the_docs_match_the_generated_report() -> None:
    md = report("forecasting_real.md")
    expected = {
        "LightGBM (Poisson)": wape_row(md, "LightGBM (Poisson)"),
        "Seasonal mean": wape_row(md, "Seasonal mean"),
        "Seasonal naive": wape_row(md, "Seasonal naive"),
        "Naive": wape_row(md, "Naive"),
    }
    assert "real data" in md.splitlines()[0]
    for label, value in expected.items():
        assert value in EVAL, f"{label} WAPE {value} missing from docs/EVALUATION.md"
    assert expected["LightGBM (Poisson)"] in README and expected["Seasonal mean"] in README
    assert expected["Seasonal naive"] in README and expected["Naive"] in README
    coverage = re.search(r"empirical coverage on the test days \*\*(\d+\.\d)%\*\*", md)
    assert coverage and f"{coverage.group(1)}%" in README and f"{coverage.group(1)}%" in EVAL
    gain = re.search(r"differs from it by (\d+\.\d) percentage points", md)
    assert gain and f"{gain.group(1)} percentage points" in README


def test_anomaly_numbers_match() -> None:
    md = report("anomalies_real.md")
    events = re.search(r"Events: \*\*(\d+)\*\*", md)
    assert events
    assert f"{events.group(1)} events" in README and events.group(1) in EVAL
    assert "UNVERIFIED" in md and "UNVERIFIED" in README


def test_optimization_numbers_match() -> None:
    md = report("optimization_real.md")
    lgbm = re.search(r"LightGBM plan vs no repositioning \| \+(\d\.\d\d)", md)
    oracle = re.search(r"Oracle plan vs no repositioning[^|]*\| \+(\d\.\d\d)", md)
    assert lgbm and oracle
    for text in (README, EVAL):
        assert lgbm.group(1) in text and oracle.group(1) in text
    assert "SIMULATED" in md


def test_ai_benchmark_numbers_match_the_stored_runs() -> None:
    history = json.loads((REPO / "reports" / "ai_benchmark_real.json").read_text())["history"]
    first = next(h for h in history if h["label"] == "first-run")
    hold = next(h for h in history if h["label"] == "holdout-first-run")
    dev_last = [
        h
        for h in history
        if h.get("question_set", "analyst_questions.json").startswith("analyst_questions.json")
    ][-1]
    assert f"{100 * first['pass_rate']:.1f}%" in README and f"{100 * first['pass_rate']:.1f}%" in AI
    assert f"{100 * hold['pass_rate']:.1f}%" in README and f"{100 * hold['pass_rate']:.1f}%" in AI
    assert f"{hold['passed']} / {hold['questions']}" in AI
    assert f"{first['passed']} / {first['questions']}" in AI
    assert (
        dev_last["pass_rate"] == 1.0 and "100" in AI
    )  # documented as optimistic (tuned on this set)
    hold2 = next(h for h in history if h["label"] == "holdout2-first-run")
    assert f"{100 * hold2['pass_rate']:.1f}%" in README and f"{100 * hold2['pass_rate']:.1f}%" in AI
    assert f"{hold2['passed']} / {hold2['questions']}" in AI
    md = report("ai_evaluation_real.md")
    assert f"{hold['passed']}" in md and "UNVERIFIED" in md


def test_every_status_word_claim_has_the_unverified_caveats_in_place() -> None:
    for text in (README, EVAL, AI):
        assert "UNVERIFIED" in text
    assert "NOT IMPLEMENTED" in README
    assert "LLM mode" in AI and "UNVERIFIED" in AI


def test_committed_reports_never_mix_synthetic_and_real() -> None:
    for name in (
        "forecasting_real.md",
        "anomalies_real.md",
        "optimization_real.md",
        "ai_evaluation_real.md",
    ):
        head = report(name).splitlines()[0]
        assert "real data" in head and "SYNTHETIC" not in head, name


def test_documents_linked_from_the_readme_exist() -> None:
    for target in re.findall(
        r"\]\((docs/[A-Za-z_]+\.md|reports/[A-Za-z_.]+|docs/images/[A-Za-z_-]+\.png)\)", README
    ):
        assert (REPO / target).exists(), target
    required = ["ARCHITECTURE", "DATA_DICTIONARY", "MODELING", "EVALUATION", "AI_EVALUATION",
                "SECURITY", "LIMITATIONS", "DECISIONS", "CONTRIBUTING"]  # fmt: skip
    for name in required:
        assert (REPO / "docs" / f"{name}.md").exists(), name
