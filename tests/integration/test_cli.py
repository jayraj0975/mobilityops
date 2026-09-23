"""Drive every CLI command through a complete workflow in an isolated directory."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mobilityops.cli import main


@pytest.fixture(scope="module")
def env(tmp_path_factory: pytest.TempPathFactory):  # type: ignore[no-untyped-def]
    root = tmp_path_factory.mktemp("cli")
    mp = pytest.MonkeyPatch()
    mp.setenv("MOBILITYOPS_DATA_DIR", str(root / "data"))
    mp.setenv("MOBILITYOPS_MODE", "sample")
    mp.setenv("MOBILITYOPS_LOG_LEVEL", "ERROR")
    yield root
    mp.undo()


def run(argv: list[str], capsys) -> tuple[int, str, str]:  # type: ignore[no-untyped-def]
    code = main(argv)
    cap = capsys.readouterr()
    return code, cap.out, cap.err


def test_full_workflow_produces_every_artifact_and_readable_reports(env, capsys) -> None:  # type: ignore[no-untyped-def]
    root: Path = env
    code, out, _ = run(["sample"], capsys)
    assert code == 0 and "TEST / SYNTHETIC DATA" in out
    assert run(["ingest"], capsys)[0] == 0
    code, out, _ = run(["build"], capsys)
    assert code == 0 and "quality[gold]: PASS" in out
    code, out, _ = run(["status"], capsys)
    assert code == 0 and "[gold] PASS" in out

    code, out, _ = run(["forecast-eval", "--no-oracle"], capsys)
    assert code == 0 and "lightgbm" in out and "empirical coverage" in out
    code, out, _ = run(
        ["forecast-eval", "--folds", "2", "--fold-days", "7", "--calib-days", "7"], capsys
    )
    assert code == 0
    md = root / "reports" / "f.md"
    assert run(["forecast-report", "--out", str(md)], capsys)[0] == 0
    ev = json.loads((root / "artifacts" / "sample" / "forecast" / "evaluation.json").read_text())
    text = md.read_text()
    # every headline number in the rendered file is the one in the JSON, formatted, not retyped
    assert f"{100 * ev['overall']['lightgbm']['wape']:.1f}%" in text
    assert f"{ev['overall']['lightgbm']['mae']:.2f}" in text
    assert f"{100 * ev['interval']['overall']['coverage']:.1f}%" in text
    assert "TEST / SYNTHETIC DATA" in text and "ORACLE" in text and "percentage points" in text
    assert "0.0% points" not in text  # the wording bug fixed earlier stays fixed

    assert run(["forecast-train"], capsys)[0] == 0
    code, out, _ = run(["anomalies"], capsys)
    assert code == 0 and "planted anomalies found" in out
    an_md = root / "reports" / "a.md"
    assert run(["anomaly-report", "--out", str(an_md)], capsys)[0] == 0
    an = an_md.read_text()
    assert "Accuracy status" in an and "co-occurrence" in an and "Threshold trade-off" in an
    rep = json.loads((root / "artifacts" / "sample" / "anomaly" / "report.json").read_text())
    assert f"**{rep['events_total']}**" in an

    code, out, _ = run(["optimize", "--date", ev["data_days"][1], "--min-service", "0.999"], capsys)
    assert code == 0 and "SIMULATED" in out and "infeasible" in out
    code, out, _ = run(["optimize-backtest", "--no-sensitivity"], capsys)
    assert code == 0 and "SIMULATED" in out and "LightGBM plan vs no repositioning" in out
    op_md = root / "reports" / "o.md"
    assert run(["optimize-report", "--out", str(op_md)], capsys)[0] == 0
    op = op_md.read_text()
    assert "SIMULATED SCENARIO" in op and "What this is and is not" in op and "Assumptions" in op

    code, out, _ = run(["analyst-benchmark", "--label", "cli-test"], capsys)
    assert code == 0 and "questions passed" in out
    ab_md = root / "reports" / "ab.md"
    assert run(["analyst-benchmark-report", "--out", str(ab_md)], capsys)[0] == 0
    assert "LLM mode: UNVERIFIED" in ab_md.read_text()

    spec = root / "openapi.json"
    assert run(["openapi", "--out", str(spec)], capsys)[0] == 0
    assert "/api/v1/analyst/ask" in json.loads(spec.read_text())["paths"]


def test_commands_fail_clearly_when_prerequisites_are_missing(
    tmp_path, monkeypatch, capsys
) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("MOBILITYOPS_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("MOBILITYOPS_MODE", "sample")
    monkeypatch.setenv("MOBILITYOPS_LOG_LEVEL", "ERROR")
    for argv, hint in (
        (["status"], "ingest"),
        (["build"], "cannot build"),
        (["forecast-eval"], "build"),
        (["forecast-report"], "forecast-eval"),
        (["forecast-train"], "cannot train"),
        (["anomalies"], "build"),
        (["anomaly-report"], "anomalies"),
        (["optimize-backtest"], "cannot run"),
        (["optimize-report"], "optimize-backtest"),
        (["analyst-benchmark-report"], "analyst-benchmark"),
    ):
        code, _, err = run(argv, capsys)
        assert code == 1 and hint in err, (argv, err)


def test_safety_refusals_at_the_command_line(tmp_path, monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("MOBILITYOPS_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("MOBILITYOPS_LOG_LEVEL", "ERROR")
    monkeypatch.delenv("MOBILITYOPS_API_KEY", raising=False)
    monkeypatch.setenv("MOBILITYOPS_MODE", "real")
    code, _, err = run(["sample"], capsys)  # never write synthetic data while in real mode
    assert code == 2 and "real" in err
    code, _, err = run(["ingest"], capsys)  # real mode needs an explicit month range
    assert code == 2 and "--start" in err
    monkeypatch.setenv("MOBILITYOPS_MODE", "sample")
    code, _, err = run(["serve", "--host", "0.0.0.0"], capsys)  # no key, non-local: refused
    assert code == 2 and "MOBILITYOPS_API_KEY" in err and "--allow-unauthenticated" in err
    code, _, _ = run(["optimize", "--date", "2024-01-01"], capsys)
    assert code == 1
