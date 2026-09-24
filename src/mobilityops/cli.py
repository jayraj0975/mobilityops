"""Command-line entry point: ``python -m mobilityops.cli <command>``.

Commands are added phase by phase; each does one obvious thing and prints what it did.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence

import duckdb

from mobilityops.config import Settings
from mobilityops.ingestion.download import DownloadError
from mobilityops.ingestion.pipeline import MonthRange, ingest_real, ingest_sample, parse_month
from mobilityops.log import configure_logging, get_logger
from mobilityops.pipeline import build_all, quality_dir
from mobilityops.quality.checks import QualityGateError
from mobilityops.sample import SYNTHETIC_LABEL, SampleSpec, generate_sample

log = get_logger("cli")
GRACEFUL_SHUTDOWN_SECONDS = 5


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
            services = tuple(x for x in (args.services or "").split(",") if x)
            m = ingest_real(
                settings,
                MonthRange(parse_month(args.start), parse_month(args.end)),
                services=services,
            )
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


def cmd_pune_build(settings: Settings, args: argparse.Namespace) -> int:
    """Build the Pune database: real rain history and geography, SIMULATED demand."""
    from datetime import date

    from mobilityops.pune.build import build_pune
    from mobilityops.pune.sources.base import SourceError

    if settings.mode != "pune":
        print("pune-build needs MOBILITYOPS_MODE=pune", file=sys.stderr)
        return 2
    window = (date.fromisoformat(args.start), date.fromisoformat(args.end)) if args.start else None
    try:
        res = build_pune(settings, window, refresh_weather=args.refresh_weather)
    except SourceError as exc:
        print(f"cannot fetch the rain history: {exc}", file=sys.stderr)
        return 1
    except (QualityGateError, ValueError) as exc:
        print(f"BUILD STOPPED: {exc}", file=sys.stderr)
        return 1
    print(f"built {res.db_path} (run {res.run_id})")
    start, end = res.window
    print(f"  SIMULATED demand: {res.trips:,} trips, {res.zones} zones, {start} to {end}")
    print(f"  quality[gold]: {res.report.overall.value}; planted events: {len(res.events)}")
    return 0


def cmd_pune_worker(settings: Settings, args: argparse.Namespace) -> int:
    """Run the Pune ingestion worker (weather, air quality, rain, simulated demand, forecast)."""
    import httpx

    from mobilityops.pune.store import StateStore
    from mobilityops.pune.worker import Worker

    if settings.mode != "pune":
        print("pune-worker needs MOBILITYOPS_MODE=pune", file=sys.stderr)
        return 2
    if not settings.db_path.exists():
        print("no Pune database yet; run `pune-build` first", file=sys.stderr)
        return 1
    settings.ensure_dirs()
    with httpx.Client(follow_redirects=False) as client:
        worker = Worker(settings, StateStore(settings.state_path), client)
        if args.once:
            worker.tick()
            for run in worker.store.runs(len(worker.jobs) + 2):
                state = "ok" if run["ok"] else f"FAILED: {run['error']}"
                print(f"  {run['source']:<26} {state} ({run['records_ok']} records)")
            return 0
        worker.run_forever()
    return 0


def cmd_status(settings: Settings, args: argparse.Namespace) -> int:
    """Print the latest quality reports."""
    found = False
    for stage in ("bronze", "silver", "services", "gold"):
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
    cfg = default_config(load_demand(settings.db_path, settings.city).n_days)
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


def cmd_forecast_holiday_experiment(settings: Settings, args: argparse.Namespace) -> int:
    """Run the pre-registered holiday-feature experiment and write its report."""
    from pathlib import Path

    from mobilityops.forecasting.holiday_experiment import render, run_experiment

    if not settings.db_path.exists():
        print("no database yet; run `ingest` and `build` first", file=sys.stderr)
        return 1
    try:
        report = run_experiment(settings)
    except ValueError as exc:
        print(f"cannot run the experiment: {exc}", file=sys.stderr)
        return 1
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(report))
    out.with_suffix(".json").write_text(json.dumps(report, indent=2, default=str))
    verdict = report["primary"]["decision"]["adopted"]
    print(f"wrote {out}; holiday features {'ADOPTED' if verdict else 'NOT ADOPTED'} (primary test)")
    return 0


def cmd_anomalies(settings: Settings, args: argparse.Namespace) -> int:
    """Detect anomalies in the out-of-sample forecasts from `forecast-eval`."""
    from mobilityops.anomaly.run import run_anomaly_detection

    try:
        rep = run_anomaly_detection(settings)
    except FileNotFoundError as exc:
        print(f"cannot detect: {exc}", file=sys.stderr)
        return 1
    print(f"[{rep['data_label']}] {rep['scored_zone_hours']:,} out-of-sample zone-hours scored")
    print(
        f"events: {rep['events_total']} (high {rep['by_severity'].get('high', 0)}, "
        f"medium {rep['by_severity'].get('medium', 0)}, low {rep['by_severity'].get('low', 0)})"
    )
    for line in rep["top_explanations"][:5]:
        print(f"  - {line}")
    if rep.get("planted_truth"):
        pt = rep["planted_truth"]
        print(
            f"planted anomalies found: {pt['found']}/{pt['planted']}; "
            f"events not planted: {pt['events_not_planted']}"
        )
    return 0


def cmd_anomaly_report(settings: Settings, args: argparse.Namespace) -> int:
    """Render the latest anomaly report as Markdown."""
    from pathlib import Path

    import pandas as pd

    from mobilityops.anomaly.report import render
    from mobilityops.anomaly.run import anomaly_dir

    src = anomaly_dir(settings)
    if not (src / "report.json").exists():
        print("no anomaly report yet; run `anomalies` first", file=sys.stderr)
        return 1
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    text = render(
        json.loads((src / "report.json").read_text()), pd.read_parquet(src / "events.parquet")
    )
    out.write_text(text)
    print(f"wrote {out}")
    return 0


def cmd_optimize_backtest(settings: Settings, args: argparse.Namespace) -> int:
    """Backtest repositioning plans against actual demand (SIMULATED, assumption-driven)."""
    from mobilityops.optimization.run import run_backtest

    try:
        rep = run_backtest(settings, sensitivity=not args.no_sensitivity)
    except (FileNotFoundError, ValueError) as exc:
        print(f"cannot run: {exc}", file=sys.stderr)
        return 1
    print(f"[{rep['data_label']}] {rep['label']}")
    print(f"{rep['windows_scored']} day-windows over {rep['days']} days")
    for name, v in rep["planners"].items():
        print(
            f"  {name:<20} served share {v['served_share']:.2%}  "
            f"moved/window {v['vehicles_moved_per_window']:.0f}"
        )
    d = rep["lightgbm_vs_none"]
    print(
        f"  LightGBM plan vs no repositioning: {100 * d['point']:+.2f} pp "
        f"(95% CI {100 * d['ci95'][0]:+.2f} to {100 * d['ci95'][1]:+.2f})"
    )
    return 0


def cmd_optimize(settings: Settings, args: argparse.Namespace) -> int:
    """Run one repositioning what-if for a date and window (SIMULATED)."""
    from datetime import date as _date

    from mobilityops.optimization.model import RebalanceParams
    from mobilityops.optimization.run import optimization_dir, scenario_report
    from mobilityops.optimization.scenario import Window

    try:
        mult = {}
        for item in args.surge or []:
            zone, factor = item.split(":")
            mult[int(zone)] = float(factor)
        params = RebalanceParams(
            max_km=args.max_km,
            max_move_share=args.max_move_share,
            min_service_share=args.min_service,
        )
        rep = scenario_report(
            settings,
            _date.fromisoformat(args.date),
            Window(args.start_hour, args.end_hour),
            params,
            coverage=args.coverage,
            multipliers=mult or None,
        )
    except (FileNotFoundError, ValueError) as exc:
        print(f"cannot run: {exc}", file=sys.stderr)
        return 1
    out = optimization_dir(settings)
    out.mkdir(parents=True, exist_ok=True)
    (out / f"scenario_{args.date}.json").write_text(json.dumps(rep, indent=2, default=str))
    print(f"[{rep['data_label']}] {rep['label']}")
    print(f"{rep['context']['date']} {rep['context']['window']}: status {rep['status']}")
    print(f"  {rep['message']}")
    if rep["status"] in ("optimal", "feasible_time_limit"):
        print(
            f"  served share {rep['service_share_before']:.2%} -> {rep['service_share_after']:.2%}"
            f" with {rep['vehicles_moved']} of {rep['fleet']} vehicles moved "
            f"({rep['km_total']:.0f} km)"
        )
        for m in rep["moves"][:5]:
            print(f"  move {m['vehicles']} x {m['from_name']} -> {m['to_name']} ({m['km']} km)")
    return 0


def cmd_optimize_report(settings: Settings, args: argparse.Namespace) -> int:
    """Render the latest repositioning backtest as Markdown."""
    from pathlib import Path

    from mobilityops.optimization.report import render
    from mobilityops.optimization.run import optimization_dir

    src = optimization_dir(settings) / "backtest.json"
    if not src.exists():
        print("no backtest yet; run `optimize-backtest` first", file=sys.stderr)
        return 1
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(json.loads(src.read_text())))
    print(f"wrote {out}")
    return 0


def cmd_serve(settings: Settings, args: argparse.Namespace) -> int:
    """Start the HTTP API (binds to localhost unless told otherwise)."""
    import uvicorn

    from mobilityops.api.app import create_app

    local = args.host in ("127.0.0.1", "localhost", "::1")
    if not local and settings.api_key is None and not args.allow_unauthenticated:
        print(
            "refusing to listen on a non-local address without MOBILITYOPS_API_KEY set "
            "(pass --allow-unauthenticated only if the port is published to localhost, for "
            "example by Docker with -p 127.0.0.1:8000:8000)",
            file=sys.stderr,
        )
        return 2
    # Event streams never end on their own, so uvicorn's graceful shutdown would wait for every
    # connected viewer forever and `docker stop` / `systemctl stop` would hang until killed. Bound
    # it: in-flight requests get a few seconds, open streams are then cancelled (clients reconnect).
    uvicorn.run(
        create_app(settings),
        host=args.host,
        port=args.port,
        log_config=None,
        timeout_graceful_shutdown=GRACEFUL_SHUTDOWN_SECONDS,
    )
    return 0


def cmd_analyst_benchmark(settings: Settings, args: argparse.Namespace) -> int:
    """Run the analyst benchmark against independent ground truth; append to the history."""
    from mobilityops.analyst.benchmark import run_benchmark, save

    try:
        from mobilityops.analyst.benchmark import (
            HOLDOUT2_PATH,
            HOLDOUT3_PATH,
            HOLDOUT_PATH,
            QUESTIONS_PATH,
        )

        path_in = (
            HOLDOUT3_PATH
            if args.holdout3
            else HOLDOUT2_PATH
            if args.holdout2
            else HOLDOUT_PATH
            if args.holdout
            else QUESTIONS_PATH
        )
        run = run_benchmark(settings, label=args.label, questions=path_in)
    except (FileNotFoundError, ValueError) as exc:
        print(f"cannot run: {exc}", file=sys.stderr)
        return 1
    path = save(settings, run)
    print(
        f"[{run['data_label']}] {run['passed']}/{run['questions']} questions passed "
        f"({run['pass_rate']:.1%}); history: {path}"
    )
    for name, v in run["per_check"].items():
        print(f"  {name:<11} {v['passed']}/{v['applicable']}")
    for r in run["results"]:
        if not r["passed"]:
            why = "; ".join(r["reasons"])[:120]
            print(f"  FAIL {r['id']} [{r['category']}] {r['question'][:70]} :: {why}")
    return 0


def cmd_analyst_benchmark_report(settings: Settings, args: argparse.Namespace) -> int:
    """Render the benchmark history as Markdown."""
    from pathlib import Path

    from mobilityops.analyst.benchmark_report import render

    src = settings.artifacts_dir / "analyst" / "benchmark.json"
    if not src.exists():
        print("no benchmark yet; run `analyst-benchmark` first", file=sys.stderr)
        return 1
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(json.loads(src.read_text())["history"]))
    print(f"wrote {out}")
    return 0


def cmd_openapi(settings: Settings, args: argparse.Namespace) -> int:
    """Write the API's OpenAPI document (used to generate the frontend's types)."""
    from pathlib import Path

    from mobilityops.api.app import create_app

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(create_app(settings).openapi(), indent=2, sort_keys=True) + "\n")
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
    i.add_argument(
        "--services", help="also fetch these services, comma separated: green, fhvhv (real mode)"
    )
    i.set_defaults(func=cmd_ingest)
    sub.add_parser("build", help="run the pipeline with quality gates").set_defaults(func=cmd_build)
    pb = sub.add_parser("pune-build", help="build the Pune database (SIMULATED demand)")
    pb.add_argument("--start", help="first day, YYYY-MM-DD (default: one year ending a week ago)")
    pb.add_argument("--end", help="end day, exclusive, YYYY-MM-DD")
    pb.add_argument("--refresh-weather", action="store_true", help="fetch the rain history again")
    pb.set_defaults(func=cmd_pune_build)
    pw = sub.add_parser("pune-worker", help="run the Pune ingestion worker")
    pw.add_argument("--once", action="store_true", help="run every job once and exit")
    pw.set_defaults(func=cmd_pune_worker)
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
    he = sub.add_parser(
        "forecast-holiday-experiment", help="pre-registered holiday-feature comparison"
    )
    he.add_argument("--out", default="reports/holiday_experiment.md")
    he.set_defaults(func=cmd_forecast_holiday_experiment)
    sub.add_parser("anomalies", help="detect anomalies in out-of-sample forecasts").set_defaults(
        func=cmd_anomalies
    )
    ar = sub.add_parser("anomaly-report", help="render the latest anomaly report as Markdown")
    ar.add_argument("--out", default="reports/anomalies.md")
    ar.set_defaults(func=cmd_anomaly_report)
    ob = sub.add_parser("optimize-backtest", help="backtest repositioning plans (SIMULATED)")
    ob.add_argument("--no-sensitivity", action="store_true")
    ob.set_defaults(func=cmd_optimize_backtest)
    op = sub.add_parser("optimize", help="one repositioning what-if (SIMULATED)")
    op.add_argument("--date", required=True, help="YYYY-MM-DD, an out-of-sample day")
    op.add_argument("--start-hour", type=int, default=17)
    op.add_argument("--end-hour", type=int, default=20)
    op.add_argument("--coverage", type=float, default=0.85)
    op.add_argument("--max-km", type=float, default=6.0)
    op.add_argument("--max-move-share", type=float, default=0.30)
    op.add_argument("--min-service", type=float, default=None, help="required served share")
    op.add_argument("--surge", nargs="*", help="demand shocks as ZONE_ID:FACTOR, e.g. 79:1.5")
    op.set_defaults(func=cmd_optimize)
    orr = sub.add_parser("optimize-report", help="render the latest backtest as Markdown")
    orr.add_argument("--out", default="reports/optimization.md")
    orr.set_defaults(func=cmd_optimize_report)
    sv = sub.add_parser("serve", help="start the HTTP API")
    sv.add_argument("--host", default="127.0.0.1")
    sv.add_argument("--port", type=int, default=8000)
    sv.add_argument(
        "--allow-unauthenticated",
        action="store_true",
        help="listen on a non-local address without an API key (container use only)",
    )
    sv.set_defaults(func=cmd_serve)
    ab = sub.add_parser("analyst-benchmark", help="run the AI analyst benchmark")
    ab.add_argument("--label", default="run")
    ab.add_argument("--holdout", action="store_true", help="run the first held-out question set")
    ab.add_argument("--holdout2", action="store_true", help="run the second held-out question set")
    ab.add_argument("--holdout3", action="store_true", help="run the third held-out question set")
    ab.set_defaults(func=cmd_analyst_benchmark)
    abr = sub.add_parser("analyst-benchmark-report", help="render the benchmark as Markdown")
    abr.add_argument("--out", default="reports/ai_evaluation.md")
    abr.set_defaults(func=cmd_analyst_benchmark_report)
    oa = sub.add_parser("openapi", help="write the OpenAPI document")
    oa.add_argument("--out", default="apps/web/openapi.json")
    oa.set_defaults(func=cmd_openapi)
    return p


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = Settings.from_env()
    configure_logging(settings.log_level)
    try:
        return int(args.func(settings, args))
    except (FileNotFoundError, duckdb.IOException) as exc:
        # A missing prerequisite (database, model, artifact) is a user-facing condition, not a bug.
        log.debug("command failed", exc_info=True)
        print(
            f"missing prerequisite: {exc}\nrun the earlier steps first "
            "(ingest, build, forecast-eval, forecast-train, anomalies)",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
