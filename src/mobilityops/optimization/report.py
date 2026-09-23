"""Render the repositioning backtest as Markdown (numbers are generated, not typed)."""

from __future__ import annotations

from typing import Any

NAMES = {
    "no_repositioning": "No repositioning (vehicles stay where habit put them)",
    "plan_seasonal_mean": "Plan with the seasonal-mean forecast",
    "plan_lightgbm": "Plan with the LightGBM forecast",
    "plan_oracle": "Plan with the actual demand (ORACLE, unattainable upper bound)",
}
ORDER = ("no_repositioning", "plan_seasonal_mean", "plan_lightgbm", "plan_oracle")


def _p(x: float | None, digits: int = 2) -> str:
    return "n/a" if x is None else f"{100 * x:.{digits}f}%"


def _pp(x: float, digits: int = 2) -> str:
    return f"{100 * x:+.{digits}f}"


def render(rep: dict[str, Any]) -> str:
    a = rep["assumptions"]
    lv = rep["lightgbm_vs_none"]
    lm = rep["lightgbm_vs_seasonal_mean_planning"]
    ov = rep["oracle_vs_none"]
    gap = rep["share_of_oracle_gap_closed_by_lightgbm"]
    lines = [
        f"# Repositioning backtest ({rep['data_label']})",
        "",
        f"> **{rep['label']}.**",
        "",
        f"_Generated {rep['generated_at_utc']} from data run `{rep['data_run_id']}`; "
        f"days {rep['days_scored'][0]} to {rep['days_scored'][1]}. "
        "Produced by `python -m mobilityops.cli optimize-report`; do not edit._",
        "",
        "## What this is and is not",
        "",
        rep["design"],
        "",
        "It measures how much a *better demand forecast* would change a stylised repositioning "
        "decision under the assumptions below. It is **not** evidence of what a real fleet would "
        "achieve: no fleet, dispatch or vehicle-location data exist in the open data, so supply "
        "and vehicle capacity are assumptions.",
        "",
        "## Assumptions (all explicit; change them in `RebalanceParams` / `BacktestConfig`)",
        "",
        f"* Windows per day: {', '.join(a['windows'])}",
        f"* Fleet capacity = {a['coverage']:.0%} of the LightGBM-forecast demand in the window "
        f"(so some demand is unmet by construction); one vehicle serves "
        f"{a['trips_per_vehicle']:g} trips per window",
        f"* Repositioning: at most {a['max_move_share']:.0%} of the fleet, at most "
        f"{a['max_km']:g} km centroid-to-centroid, cost {a['cost_per_km']:g} trips of value per "
        "vehicle-km",
        f"* {a['supply']}; {a['service model']}",
        "* Vehicles reach their destination before the window starts; the cost is linear in km; "
        "zones without a known centroid cannot send or receive vehicles",
        "",
        "## Results",
        "",
        f"{rep['windows_scored']} day-windows over {rep['days']} days "
        f"(skipped for unobserved hours: {rep['skipped']['dst_or_missing_actuals']}). "
        "Served share = trips served / actual trips demanded.",
        "",
        "| Planner | Served share | Vehicles moved / window | km / window |",
        "|---|---:|---:|---:|",
        *[
            f"| {NAMES[p]} | {_p(rep['planners'][p]['served_share'])} | "
            f"{rep['planners'][p]['vehicles_moved_per_window']:.0f} | "
            f"{rep['planners'][p]['km_per_window']:.0f} |"
            for p in ORDER
        ],
        "",
        "Paired differences in served share (percentage points), day-level bootstrap 95% interval:",
        "",
        "| Comparison | Difference (pp) | 95% interval (pp) |",
        "|---|---:|---|",
        f"| LightGBM plan vs no repositioning | {_pp(lv['point'])} | "
        f"[{_pp(lv['ci95'][0])}, {_pp(lv['ci95'][1])}] |",
        f"| LightGBM plan vs seasonal-mean plan | {_pp(lm['point'])} | "
        f"[{_pp(lm['ci95'][0])}, {_pp(lm['ci95'][1])}] |",
        f"| Oracle plan vs no repositioning (the most repositioning could add here) | "
        f"{_pp(ov['point'])} | [{_pp(ov['ci95'][0])}, {_pp(ov['ci95'][1])}] |",
        "",
        "Share of the oracle's improvement that the LightGBM plan captures: "
        + (
            f"{_p(gap['point'], 0)}"
            + (
                f" (95% interval {_p(gap['ci95'][0], 0)} to {_p(gap['ci95'][1], 0)})"
                if gap["ci95"]
                else ""
            )
            if gap["point"] is not None
            else "n/a"
        )
        + ".",
        "",
        "### By day type and window",
        "",
        "| Slice | windows | " + " | ".join(NAMES[p].split(" (")[0] for p in ORDER) + " |",
        "|---|---:|" + "---:|" * len(ORDER),
        *[
            f"| {k} | {v['windows']} | " + " | ".join(_p(v[p]) for p in ORDER) + " |"
            for k, v in rep["by_day_type"].items()
        ],
        *[
            f"| window {k} | | " + " | ".join(_p(v[p]) for p in ORDER) + " |"
            for k, v in rep["by_window"].items()
        ],
    ]
    if "sensitivity" in rep:
        lines += [
            "",
            "## Sensitivity to the assumptions",
            "",
            rep["sensitivity"]["note"] + ". Served share by planner; last column is LightGBM plan "
            "minus no repositioning, in percentage points.",
            "",
            "| Scenario | windows | none | seasonal | LightGBM | oracle | LightGBM - none (pp) |",
            "|---|---:|---:|---:|---:|---:|---:|",
            *[
                f"| {r['scenario']} | {r['windows']} | {_p(r['no_repositioning'])} | "
                f"{_p(r['plan_seasonal_mean'])} | {_p(r['plan_lightgbm'])} | "
                f"{_p(r['plan_oracle'])} | {r['lightgbm_vs_none_pp']:+.2f} |"
                for r in rep["sensitivity"]["rows"]
            ],
        ]
    lines += [
        "",
        f"Solver status counts (repositioning plans): {rep['solver_status_counts']}.",
        "",
        "## Limitations",
        "",
        "* Supply, vehicle capacity and repositioning cost are assumptions; conclusions are "
        "conditional on them (see the sensitivity table).",
        "* Demand is served only in the zone where a vehicle stands; real demand spills over to "
        "neighbouring zones, which would reduce the value of exact placement.",
        "* Habit-based starting positions are a modelling choice; a different operator behaviour "
        "changes the baseline.",
        "* Only the out-of-sample days are scored.",
        "",
    ]
    return "\n".join(lines)
