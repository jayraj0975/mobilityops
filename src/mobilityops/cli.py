"""Command-line entry point: ``python -m mobilityops.cli <command>``.

Commands are added phase by phase; each does one obvious thing and prints what it did.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence

from mobilityops.config import Settings
from mobilityops.ingestion.download import DownloadError
from mobilityops.ingestion.pipeline import MonthRange, ingest_real, ingest_sample, parse_month
from mobilityops.log import configure_logging, get_logger
from mobilityops.pipeline import build_all, quality_dir
from mobilityops.quality.checks import QualityGateError
from mobilityops.sample import SYNTHETIC_LABEL, SampleSpec, generate_sample

log = get_logger("cli")


def cmd_sample(settings: Settings, args: argparse.Namespace) -> int:
    """Generate the synthetic sample into data/raw/sample (never into the real-data folder)."""
    if settings.mode != "sample":
        print("refusing to write synthetic data while MOBILITYOPS_MODE=real", file=sys.stderr)
        return 2
    settings.ensure_dirs()
    files = generate_sample(settings.raw_dir, SampleSpec(seed=args.seed, n_days=args.days))
    truth = json.loads(files.ground_truth.read_text())
    print(f"{SYNTHETIC_LABEL}: wrote {truth['rows_total']:,} trips to {files.directory}")
    return 0


def cmd_ingest(settings: Settings, args: argparse.Namespace) -> int:
    """Sample mode: register the synthetic files. Real mode: download and validate."""
    try:
        if settings.mode == "sample":
            m = ingest_sample(settings)
        else:
            if not (args.start and args.end):
                print("real mode needs --start YYYY-MM and --end YYYY-MM", file=sys.stderr)
                return 2
            m = ingest_real(settings, MonthRange(parse_month(args.start), parse_month(args.end)))
    except (DownloadError, FileNotFoundError, ValueError) as exc:
        print(f"ingestion failed: {exc}", file=sys.stderr)
        return 1
    print(f"ingested {len(m.entries)} files for window {m.window} ({settings.mode} mode)")
    return 0


def cmd_build(settings: Settings, args: argparse.Namespace) -> int:
    """Run bronze -> silver -> gold with quality gates."""
    try:
        res = build_all(settings)
    except QualityGateError as exc:
        print(f"BUILD STOPPED by the quality gate: {exc}", file=sys.stderr)
        return 1
    except FileNotFoundError as exc:
        print(f"cannot build: {exc}", file=sys.stderr)
        return 1
    rej = res.silver.rows_rejected
    print(f"built {res.db_path} (run {res.run_id})")
    print(f"  trips: {res.silver.rows_valid:,} valid, {rej:,} rejected of {res.silver.rows_in:,}")
    for stage, rep in res.reports.items():
        print(f"  quality[{stage}]: {rep.overall.value}")
    return 0


def cmd_status(settings: Settings, args: argparse.Namespace) -> int:
    """Print the latest quality reports."""
    found = False
    for stage in ("bronze", "silver", "gold"):
        path = quality_dir(settings) / f"{stage}.json"
        if not path.exists():
            continue
        found = True
        rep = json.loads(path.read_text())
        print(f"[{rep['stage']}] {rep['overall']}")
        for r in rep["results"]:
            print(f"  {r['status']:<4} {r['name']}: {r['message']}")
    if not found:
        print("no quality reports yet; run `ingest` and `build`", file=sys.stderr)
        return 1
    return 0


def _fmt(x: float | None, pct: bool = False) -> str:
    if x is None:
        return "n/a"
    return f"{x:.1%}" if pct else f"{x:.3f}"


def cmd_forecast_eval(settings: Settings, args: argparse.Namespace) -> int:
    """Walk-forward evaluation of the forecaster against baselines."""
    from mobilityops.forecasting.evaluate import EvalConfig, default_config, run_evaluation
    from mobilityops.forecasting.features import load_demand

    if not settings.db_path.exists():
        print("no database yet; run `ingest` and `build` first", file=sys.stderr)
        return 1
    cfg = default_config(load_demand(settings.db_path).n_days)
    if args.folds or args.fold_days or args.calib_days:
        cfg = EvalConfig(
            n_folds=args.folds or cfg.n_folds,
            fold_days=args.fold_days or cfg.fold_days,
            calib_days=args.calib_days or cfg.calib_days,
        )
    try:
        rep = run_evaluation(settings, cfg, oracle_experiment=not args.no_oracle)
    except ValueError as exc:
        print(f"cannot evaluate: {exc}", file=sys.stderr)
        return 1
    print(f"[{rep['data_label']}] {rep['test_rows']:,} test rows, {rep['test_days']} test days")
    print(f"{'model':<18}{'MAE':>8}{'RMSE':>8}{'WAPE':>8}")
    for name, m in rep["overall"].items():
        print(f"{name:<18}{_fmt(m['mae']):>8}{_fmt(m['rmse']):>8}{_fmt(m['wape'], True):>8}")
    iv = rep["interval"]["overall"]
    print(f"80% interval: empirical coverage {_fmt(iv['coverage'], True)}")
    return 0


def cmd_forecast_train(settings: Settings, args: argparse.Namespace) -> int:
    """Fit the final model on all data and register it."""
    from mobilityops.forecasting.evaluate import train_final

    try:
        path = train_final(settings)
    except (ValueError, FileNotFoundError) as exc:
        print(f"cannot train: {exc}", file=sys.stderr)
        return 1
    print(f"registered model at {path}")
    return 0


def cmd_forecast_report(settings: Settings, args: argparse.Namespace) -> int:
    """Render the latest evaluation.json as Markdown (numbers are generated, not typed)."""
    from pathlib import Path

    from mobilityops.forecasting.report import render

    src = settings.artifacts_dir / "forecast" / "evaluation.json"
    if not src.exists():
        print("no evaluation yet; run `forecast-eval` first", file=sys.stderr)
        return 1
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(json.loads(src.read_text())))
    print(f"wrote {out}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="mobilityops", description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)
    s = sub.add_parser("sample", help="generate deterministic SYNTHETIC sample data")
    s.add_argument("--seed", type=int, default=7)
    s.add_argument("--days", type=int, default=56)
    s.set_defaults(func=cmd_sample)
    i = sub.add_parser("ingest", help="register sample files, or download real data")
    i.add_argument("--start", help="first month, YYYY-MM (real mode)")
    i.add_argument("--end", help="last month, YYYY-MM (real mode)")
    i.set_defaults(func=cmd_ingest)
    sub.add_parser("build", help="run the pipeline with quality gates").set_defaults(func=cmd_build)
    sub.add_parser("status", help="show the latest quality reports").set_defaults(func=cmd_status)
    fe = sub.add_parser("forecast-eval", help="walk-forward evaluation vs baselines")
    fe.add_argument("--folds", type=int, default=0)
    fe.add_argument("--fold-days", type=int, default=0)
    fe.add_argument("--calib-days", type=int, default=0)
    fe.add_argument("--no-oracle", action="store_true", help="skip the oracle-weather experiment")
    fe.set_defaults(func=cmd_forecast_eval)
    sub.add_parser("forecast-train", help="fit and register the final model").set_defaults(
        func=cmd_forecast_train
    )
    fr = sub.add_parser("forecast-report", help="render the latest evaluation as Markdown")
    fr.add_argument("--out", default="reports/forecasting.md")
    fr.set_defaults(func=cmd_forecast_report)
    return p


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = Settings.from_env()
    configure_logging(settings.log_level)
    return int(args.func(settings, args))


if __name__ == "__main__":
    raise SystemExit(main())
