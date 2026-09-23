"""Render ``evaluation.json`` as Markdown so documented numbers are generated, never hand-typed."""

from __future__ import annotations

from typing import Any

MODEL_ORDER = ("lightgbm", "seasonal_mean_4w", "seasonal_naive", "naive")
LABELS = {
    "lightgbm": "LightGBM (Poisson)",
    "seasonal_mean_4w": "Seasonal mean (same weekday+hour, last 4 weeks)",
    "seasonal_naive": "Seasonal naive (same weekday+hour, last week)",
    "naive": "Naive (same hour yesterday)",
}


def _f(x: float | None, digits: int = 2) -> str:
    return "n/a" if x is None else f"{x:.{digits}f}"


def _p(x: float | None, digits: int = 1) -> str:
    return "n/a" if x is None else f"{100 * x:.{digits}f}%"


def _pp(x: float | None, digits: int = 1) -> str:
    """A difference between two percentages, in percentage points."""
    return "n/a" if x is None else f"{100 * x:.{digits}f}"


def _metric_table(table: dict[str, dict[str, Any]]) -> list[str]:
    rows = ["| Model | MAE | RMSE | WAPE | Bias |", "|---|---:|---:|---:|---:|"]
    for m in MODEL_ORDER:
        if m in table:
            v = table[m]
            rows.append(
                f"| {LABELS[m]} | {_f(v['mae'])} | {_f(v['rmse'])} | {_p(v['wape'])} "
                f"| {_p(v['bias'])} |"
            )
    return rows


def _segment_table(rows_in: list[dict[str, Any]], models: tuple[str, ...], title: str) -> list[str]:
    head = (
        "| " + title + " | rows | mean actual | " + " | ".join(f"{m} WAPE" for m in models) + " |"
    )
    out = [head, "|---|---:|---:|" + "---:|" * len(models)]
    for r in rows_in:
        cells = " | ".join(_p(r[m]["wape"]) if m in r else "n/a" for m in models)
        out.append(f"| {r['segment']} | {r['n']:,} | {_f(r['mean_actual'])} | {cells} |")
    return out


def render(report: dict[str, Any]) -> str:
    label = report["data_label"]
    ov = report["overall"]
    best = report["best_baseline"]
    boot = report["bootstrap"]
    imp = boot["improvement"][best]
    iv = report["interval"]
    seg_models = (
        ("lightgbm", "seasonal_naive", best)
        if best != "seasonal_naive"
        else (
            "lightgbm",
            "seasonal_naive",
        )
    )
    lines = [
        f"# Forecast evaluation ({label})",
        "",
        f"_Generated {report['generated_at_utc']} from data run `{report['data_run_id']}`; "
        f"data days {report['data_days'][0]} to {report['data_days'][1]}. "
        "This file is produced by `python -m mobilityops.cli forecast-report`; do not edit._",
        "",
        "**Task.** " + report["problem"] + ".",
        "",
        f"**Test set.** {report['test_rows']:,} zone-hours, {report['test_days']} days, "
        f"{report['zones']} zones, {len(report['folds'])} walk-forward folds "
        f"(model refitted at each fold boundary; calibration block precedes each test block).",
        "",
        "## Overall accuracy (all test folds pooled)",
        "",
        *_metric_table(ov),
        "",
        f"Strongest baseline: **{LABELS[best]}**. LightGBM's WAPE differs from it by "
        f"{_pp(imp['wape_point_difference'])} percentage points "
        f"({_p(imp['relative_reduction_point'])} relative; positive = LightGBM better); "
        f"day-level bootstrap 95% interval for the difference "
        f"[{_pp(imp['difference_ci95'][0])}, {_pp(imp['difference_ci95'][1])}] percentage points "
        f"({boot['resamples']} resamples over {boot['n_days']} test days). "
        "All baselines:",
        "",
        "| Baseline | WAPE difference (baseline - model), pp | 95% interval, pp | relative |",
        "|---|---:|---|---:|",
        *[
            f"| {LABELS[b]} | {_pp(v['wape_point_difference'])} | "
            f"[{_pp(v['difference_ci95'][0])}, {_pp(v['difference_ci95'][1])}] | "
            f"{_p(v['relative_reduction_point'])} |"
            for b, v in boot["improvement"].items()
        ],
        "",
        "WAPE = sum of absolute errors / sum of actual pickups. "
        "Bias = (sum forecast - sum actual) / sum actual. "
        "MAE and RMSE are in pickups per zone-hour.",
        "",
        "## City-wide hourly total (zone forecasts summed)",
        "",
        *_metric_table(report["city_total_hourly"]),
        "",
        "## By fold",
        "",
        "| Fold | test days | " + " | ".join(f"{m} WAPE" for m in MODEL_ORDER) + " |",
        "|---|---|" + "---:|" * len(MODEL_ORDER),
    ]
    for f in report["folds"]:
        k = str(f["fold"])
        cells = " | ".join(_p(report["by_fold"][k][m]["wape"]) for m in MODEL_ORDER)
        lines.append(f"| {k} | {f['test_days'][0]} to {f['test_days'][1]} | {cells} |")
    lines += ["", "## Error analysis", ""]
    lines += _segment_table(
        report["by_volume"], seg_models, "Zone volume (mean pickups/hour, last 28 days)"
    )
    for key, title in (
        ("by_holiday", "Day type"),
        ("by_weekday", "Weekday"),
        ("by_weather_context", "Weather (context only, not a model input)"),
        ("by_borough", "Borough"),
    ):
        lines += ["", *_segment_table(report[key], seg_models, title)]
    lines += [
        "",
        "### Largest zone-day errors (LightGBM)",
        "",
        "| Zone | Borough | Date | Actual | Forecast | Abs. error | Federal holiday |",
        "|---|---|---|---:|---:|---:|---|",
        *[
            f"| {w['zone']} | {w['borough']} | {w['date']} | {w['actual_day_pickups']:,.0f} | "
            f"{w['forecast_day_pickups']:,.0f} | {w['abs_error']:,.0f} | "
            f"{'yes' if w['is_holiday'] else 'no'} |"
            for w in report["worst_zone_days"]
        ],
        "",
        "Wording note: dates listed here *coincided with* the largest misses; this evaluation does "
        "not establish why demand differed.",
        "",
        "### Feature importance (gain share, last fold's model)",
        "",
        "| Feature | Share |",
        "|---|---:|",
        *[
            f"| `{k}` | {_p(v)} |"
            for k, v in list(report["feature_importance_last_fold"].items())[:8]
        ],
        "",
        "## Prediction intervals",
        "",
        f"Nominal central coverage {_p(iv['nominal'], 0)}; empirical coverage on the test days "
        f"**{_p(iv['overall']['coverage'])}**, "
        f"mean width {_f(iv['overall']['mean_width'])} pickups.",
        "",
        "| Slice | coverage | mean width |",
        "|---|---:|---:|",
        *[
            f"| fold {k} | {_p(v['coverage'])} | {_f(v['mean_width'])} |"
            for k, v in iv["by_fold"].items()
        ],
        *[
            f"| volume {k} | {_p(v['coverage'])} | {_f(v['mean_width'])} |"
            for k, v in iv["by_volume"].items()
        ],
    ]
    hours = [v["coverage"] for v in iv["by_hour"].values()]
    lines += [
        "",
        f"Coverage by hour of day ranges from {_p(min(hours))} to {_p(max(hours))}. Coverage for "
        "near-zero demand is conservative because counts are discrete.",
    ]
    if "oracle_weather_experiment" in report:
        o = report["oracle_weather_experiment"]
        lines += [
            "",
            "## Weather experiment (ORACLE, not a deployable result)",
            "",
            o["label"],
            "",
            f"WAPE without weather {_p(o['wape_without_weather'])}, with actual same-day weather "
            f"{_p(o['wape_with_oracle_weather'])}; MAE {_f(o['mae_without_weather'], 3)} vs "
            f"{_f(o['mae_with_oracle_weather'], 3)}.",
        ]
    lines += [
        "",
        "## Baseline fallbacks",
        "",
        f"Rows where a baseline's primary value was missing and a fallback was used: "
        f"{report['baseline_fallback_rows']}.",
        "",
    ]
    return "\n".join(lines)
