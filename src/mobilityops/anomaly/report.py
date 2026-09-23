"""Render the anomaly report as Markdown so documented numbers are generated, not typed."""

from __future__ import annotations

from typing import Any

import pandas as pd


def _p(x: float | None, digits: int = 0) -> str:
    return "n/a" if x is None or pd.isna(x) else f"{100 * x:.{digits}f}%"


def render(report: dict[str, Any], events: pd.DataFrame, top: int = 15) -> str:
    cfg = report["config"]
    lines = [
        f"# Anomaly detection ({report['data_label']})",
        "",
        f"_Generated {report['generated_at_utc']} from data run `{report['data_run_id']}`; "
        f"scored days {report['scored_days'][0]} to {report['scored_days'][1]}. "
        "Produced by `python -m mobilityops.cli anomaly-report`; do not edit._",
        "",
        f"**Accuracy status: {report['accuracy_status']}.**",
        "",
        f"**Method.** {report['method']}. Scores use only out-of-sample forecasts "
        f"({report['scored_zone_hours']:,} zone-hours, {report['scored_zone_days']:,} zone-days). "
        f"Seed hours: |z| >= {cfg['z_seed']}; an event is kept when its standardised pooled score "
        f"is at least {cfg['event_threshold']} and its total deviation is at least "
        f"{cfg['min_excess']:.0f} pickups.",
        "",
        "## Summary",
        "",
        f"* Events: **{report['events_total']}** "
        f"({report['events_per_1000_zone_days']:.1f} per 1,000 zone-days)",
        "* Severity (heuristic on |score|; low < 8 <= medium < 15 <= high): "
        f"{report['by_severity']}",
        f"* Direction: {report['by_direction']}",
        f"* Scope (share of *other* zones deviating in the same hours): {report['by_scope']}",
    ]
    if report.get("busiest_days"):
        lines += [
            "",
            "### Days with the most events",
            "",
            "| Date | Events | Share of all events |",
            "|---|---:|---:|",
            *[
                f"| {d['date']} | {d['events']} | {_p(d['share_of_all'])} |"
                for d in report["busiest_days"]
            ],
        ]
    if "planted_truth" in report:
        pt = report["planted_truth"]
        lines += [
            "",
            "## Check against planted ground truth (synthetic data only)",
            "",
            f"Planted anomalies found: **{pt['found']} of {pt['planted']}**; events that match no "
            f"planted anomaly: **{pt['events_not_planted']}**. Only a handful of anomalies exist, "
            "so this shows the mechanism works, not a precise error rate.",
            "",
            "| Zone | Kind | Start | Hours | Found | Score |",
            "|---:|---|---|---:|---|---:|",
            *[
                f"| {d['zone']} | {d['kind']} | {d['start']} | {d['hours']} | "
                f"{'yes' if d['found'] else 'NO'} | "
                f"{'n/a' if d['event_z'] is None else format(d['event_z'], '+.1f')} |"
                for d in pt["details"]
            ],
        ]
    lines += [
        "",
        f"## Top {min(top, len(events))} events by size (coincidence, not cause)",
        "",
    ]
    for i, text in enumerate(events["explanation"].head(top), start=1):
        lines.append(f"{i}. {text}")
    if "injection_experiment" in report:
        inj = pd.DataFrame(report["injection_experiment"]["results"])
        lines += [
            "",
            "## Sensitivity: what size of deviation would be noticed?",
            "",
            report["injection_experiment"]["label"] + ".",
            "",
            "Share of injected events detected (`event_threshold` "
            f"{cfg['event_threshold']}), by demand level, duration and multiplier. "
            "Multipliers below 1 are drops; a drop can never fall below zero, so drops are "
            "structurally harder to detect than surges of the same relative size.",
            "",
        ]
        for dur, sub in inj.groupby("duration_hours"):
            table = sub.pivot_table(index="band", columns="factor", values="recall")
            table = table.reindex(
                [b for b in ("1-5/h", "5-20/h", "20-100/h", ">=100/h") if b in table.index]
            )
            lines += [
                f"**{dur}-hour event**",
                "",
                "| Forecast demand | " + " | ".join(f"x{f:g}" for f in table.columns) + " |",
                "|---|" + "---:|" * len(table.columns),
                *[
                    f"| {band} | " + " | ".join(_p(v) for v in row) + " |"
                    for band, row in table.iterrows()
                ],
                "",
            ]
    if report.get("threshold_sensitivity"):
        lines += [
            "## Threshold trade-off",
            "",
            "Lowering `event_threshold` finds more real deviations and more marginal ones. "
            "Recall is for injected events in zones forecast at 20+ pickups/hour.",
            "",
            "| event_threshold | events | per 1,000 zone-days | surge x2, 3 h | surge x2, 6 h "
            "| drop x0.5, 3 h | drop x0.5, 6 h |",
            "|---:|---:|---:|---:|---:|---:|---:|",
            *[
                f"| {r['event_threshold']:g} | {r['events']} | "
                f"{r['events_per_1000_zone_days']:.1f} | "
                f"{_p(r['busy_zone_recall_surge_2x_3h'])} | "
                f"{_p(r['busy_zone_recall_surge_2x_6h'])} | "
                f"{_p(r['busy_zone_recall_drop_0.5x_3h'])} | "
                f"{_p(r['busy_zone_recall_drop_0.5x_6h'])} |"
                for r in report["threshold_sensitivity"]
            ],
        ]
    lines += [
        "",
        "## Error model",
        "",
        "Residual spread by forecast level (95th-percentile based; the floor is "
        f"{report['scale_model']['floor']:g} pickup):",
        "",
        "| Forecast (mean) | rows | sigma |",
        "|---:|---:|---:|",
        *[
            f"| {b['mean_forecast']:.1f} | {b['rows']:,} | {b['sigma']:.2f} |"
            for b in report["scale_model"]["bands"]
        ],
        "",
        f"Spread of the pooled score by run length (empirical null; 1 = independent errors): "
        f"{report['null_model_robust_sd_by_run_hours']}.",
        "",
        "## Limitations",
        "",
        "* Only the out-of-sample test days can be scored, not the whole history.",
        "* Real-data precision is UNVERIFIED: there are no labelled anomalies. Events are "
        "candidates for a person to review.",
        "* Explanations list calendar and weather context that *coincided* with an event; they do "
        "not establish a cause.",
        "* Weather is daily and city-wide; it cannot resolve an hour or a neighbourhood.",
        "* Drops are structurally harder to detect than surges (see sensitivity tables).",
        "",
    ]
    return "\n".join(lines)
