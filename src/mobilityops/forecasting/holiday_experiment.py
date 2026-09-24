"""The pre-registered holiday / long-weekend experiment (docs/PREREGISTRATION_HOLIDAY.md).

Two models are evaluated with identical settings on identical walk-forward folds: ``base`` (the
shipped feature set) and ``holiday`` (the same plus ``is_long_weekend`` and ``days_to_holiday``).
The metrics and the decision rule are the ones written down before the run; the decision is computed
here, not judged afterwards.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import numpy as np
import pandas as pd

from mobilityops.config import Settings
from mobilityops.forecasting.evaluate import (
    BOOTSTRAP_RESAMPLES,
    MODEL,
    VOLUME_BINS,
    VOLUME_LABELS,
    _segments,
    _with_threads,
    data_run_id,
    default_config,
    metrics,
    walk_forward,
)
from mobilityops.forecasting.features import DemandTensor, load_demand
from mobilityops.log import get_logger

log = get_logger(__name__)

PAIR = ("base", "holiday")
WORSE_BY = 0.01  # condition 3: no slice may worsen by more than one WAPE point
SECONDARY_END = "2024-09-30"


def _paired(
    t: DemandTensor, *, settings: Settings, label: str
) -> tuple[pd.DataFrame, dict[str, Any]]:
    cfg = _with_threads(default_config(t.n_days), settings)
    base = walk_forward(t, replace(cfg, holiday_features=False))
    hol = walk_forward(t, replace(cfg, holiday_features=True))
    key = ["fold", "zone_index", "day_index", "hour"]
    a, b = base.predictions, hol.predictions
    if len(a) != len(b) or not a[key].equals(b[key]) or not np.array_equal(a["y"], b["y"]):
        raise RuntimeError("the two runs did not score identical rows; the comparison is invalid")
    df = a[[*key, "y", "mean_28d", "hour_ts"]].copy()
    df["base"] = a[MODEL].to_numpy()
    df["holiday"] = b[MODEL].to_numpy()
    log.info("paired run done", extra={"ctx": {"label": label, "rows": len(df)}})
    return df, {"folds": base.folds, "n_days": t.n_days}


def _bootstrap(df: pd.DataFrame, seed: int) -> dict[str, Any]:
    """Day-level bootstrap of WAPE(base) - WAPE(holiday): positive means the new features help."""
    uniq, inv = np.unique(df["day_index"].to_numpy(), return_inverse=True)
    y_day = np.bincount(inv, weights=df["y"].to_numpy(float))
    err = {
        m: np.bincount(inv, weights=np.abs(df[m].to_numpy(float) - df["y"].to_numpy(float)))
        for m in PAIR
    }
    rng = np.random.default_rng(seed)
    draws = rng.integers(0, len(uniq), size=(BOOTSTRAP_RESAMPLES, len(uniq)))
    denom = y_day[draws].sum(axis=1)
    diff = (err["base"][draws].sum(axis=1) - err["holiday"][draws].sum(axis=1)) / denom
    point = float((err["base"].sum() - err["holiday"].sum()) / y_day.sum())
    return {
        "resamples": BOOTSTRAP_RESAMPLES,
        "unit": "test day",
        "n_days": len(uniq),
        "point_difference": point,
        "difference_ci95": [float(np.percentile(diff, 2.5)), float(np.percentile(diff, 97.5))],
        "share_of_resamples_holiday_better": float(np.mean(diff > 0)),
    }


def _wape_pair(df: pd.DataFrame) -> dict[str, Any]:
    out: dict[str, Any] = {"n": len(df), "days": int(df["day_index"].nunique())}
    for m in PAIR:
        out[m] = metrics(df["y"].to_numpy(float), df[m].to_numpy(float))["wape"]
    out["difference"] = (
        None if out["base"] is None or out["holiday"] is None else out["base"] - out["holiday"]
    )
    return out


def _slices(df: pd.DataFrame, t: DemandTensor) -> dict[str, list[dict[str, Any]]]:
    di = df["day_index"].to_numpy()
    dow = pd.DatetimeIndex(t.days[di]).dayofweek
    weekday = pd.Series(dow, index=df.index).map(
        dict(enumerate(["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]))
    )
    holiday = pd.Series(t.calendar["is_holiday"].to_numpy()[di], index=df.index).map(
        {True: "holiday", False: "ordinary day"}
    )
    volume = pd.cut(df["mean_28d"], VOLUME_BINS, labels=VOLUME_LABELS)
    out: dict[str, list[dict[str, Any]]] = {}
    for name, key in (("weekday", weekday), ("holiday", holiday), ("volume", volume)):
        rows = _segments(df, key, PAIR)
        for r in rows:
            b, h = r["base"]["wape"], r["holiday"]["wape"]
            r["difference"] = None if b is None or h is None else b - h
        out[name] = rows
    return out


def _decide(result: dict[str, Any]) -> dict[str, Any]:
    """The pre-registered rule: all three conditions must hold."""
    boot = result["pooled"]["bootstrap"]
    c1 = boot["point_difference"] > 0 and boot["difference_ci95"][0] > 0
    hol = result["holiday_hours"]["difference"]
    c2 = hol is not None and hol >= 0
    worst = min(
        (
            r["difference"]
            for rows in result["slices"].values()
            for r in rows
            if r["difference"] is not None
        ),
        default=0.0,
    )
    c3 = worst >= -WORSE_BY
    return {
        "condition_1_pooled_improves_and_interval_excludes_zero": bool(c1),
        "condition_2_holiday_hours_not_worse": bool(c2),
        "condition_3_no_slice_worse_by_more_than_one_point": bool(c3),
        "worst_slice_difference": float(worst),
        "adopted": bool(c1 and c2 and c3),
    }


def analyse(t: DemandTensor, settings: Settings, *, label: str) -> dict[str, Any]:
    df, info = _paired(t, settings=settings, label=label)
    di = df["day_index"].to_numpy()
    is_hol = t.calendar["is_holiday"].to_numpy()[di]
    adjoining = (
        t.calendar["is_day_before_holiday"].to_numpy()[di]
        | t.calendar["is_day_after_holiday"].to_numpy()[di]
    ) & ~is_hol
    long_we = t.calendar["is_long_weekend"].to_numpy()[di].astype(bool)
    holiday_dates = sorted({t.days[d].date().isoformat() for d in np.unique(di[is_hol])})
    cfg = default_config(t.n_days)
    result: dict[str, Any] = {
        "label": label,
        "data_days": [t.days[0].date().isoformat(), t.days[-1].date().isoformat()],
        "test_days": [
            t.days[int(di.min())].date().isoformat(),
            t.days[int(di.max())].date().isoformat(),
        ],
        "folds": info["folds"],
        "n_folds": cfg.n_folds,
        "fold_days": cfg.fold_days,
        "test_rows": len(df),
        "pooled": {**_wape_pair(df), "bootstrap": _bootstrap(df, cfg.seed)},
        "holiday_hours": {**_wape_pair(df[is_hol]), "dates": holiday_dates},
        "adjoining_hours": _wape_pair(df[adjoining]),
        "long_weekend_hours": _wape_pair(df[long_we]),
        "slices": _slices(df, t),
    }
    result["decision"] = _decide(result)
    return result


def run_experiment(settings: Settings) -> dict[str, Any]:
    t = load_demand(settings.db_path)
    primary = analyse(t, settings, label="primary: last 56 days of the data")
    secondary = None
    cutoff = pd.Timestamp(SECONDARY_END)
    if t.days[-1] > cutoff:
        head = t.head(int((cutoff - t.days[0]).days) + 1)
        secondary = analyse(head, settings, label=f"secondary: test folds end {SECONDARY_END}")
    return {
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "mode": settings.mode,
        "data_label": "TEST / SYNTHETIC DATA" if settings.mode == "sample" else "real data",
        "data_run_id": data_run_id(settings.db_path),
        "preregistration": "docs/PREREGISTRATION_HOLIDAY.md",
        "primary": primary,
        "secondary": secondary,
    }


# ------------------------------------------------------------------------------------ report
def _p(x: float | None) -> str:
    return "n/a" if x is None else f"{100 * x:.1f}%"


def _pp(x: float | None) -> str:
    return "n/a" if x is None else f"{100 * x:+.2f}"


def _section(r: dict[str, Any], title: str) -> list[str]:
    boot = r["pooled"]["bootstrap"]
    lo, hi = boot["difference_ci95"]
    d = r["decision"]
    yes = {True: "yes", False: "NO"}
    lines = [
        f"## {title}",
        "",
        f"Test days {r['test_days'][0]} to {r['test_days'][1]} ({r['n_folds']} folds of "
        f"{r['fold_days']} days, {r['test_rows']:,} zone-hours). Positive differences mean the "
        "holiday features are better (WAPE of `base` minus WAPE of `holiday`, in percentage "
        "points).",
        "",
        "| Slice | Zone-hours | Days | Base WAPE | Holiday-features WAPE | Difference (pp) |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for name, key in (
        ("All test hours", "pooled"),
        ("Federal-holiday hours", "holiday_hours"),
        ("Days adjoining a holiday", "adjoining_hours"),
        ("Long-weekend days", "long_weekend_hours"),
    ):
        x = r[key]
        lines.append(
            f"| {name} | {x['n']:,} | {x['days']} | {_p(x['base'])} | {_p(x['holiday'])} "
            f"| {_pp(x['difference'])} |"
        )
    lines += [
        "",
        "Federal holidays in this test window: "
        f"{', '.join(r['holiday_hours']['dates']) or 'none'}.",
        "",
        f"Day-level bootstrap ({boot['resamples']:,} resamples of {boot['n_days']} test days): "
        f"pooled difference {_pp(boot['point_difference'])} pp, 95% interval "
        f"{_pp(lo)} to {_pp(hi)}; the holiday features were better in "
        f"{100 * boot['share_of_resamples_holiday_better']:.1f}% of resamples.",
        "",
        "### Decision rule (fixed in advance)",
        "",
        "1. Pooled WAPE improves and the 95% interval excludes zero: "
        f"**{yes[d['condition_1_pooled_improves_and_interval_excludes_zero']]}**",
        "2. Holiday-hour WAPE does not get worse: "
        f"**{yes[d['condition_2_holiday_hours_not_worse']]}**",
        f"3. No weekday, holiday or volume slice worsens by more than one point "
        f"(worst slice {_pp(d['worst_slice_difference'])} pp): "
        f"**{yes[d['condition_3_no_slice_worse_by_more_than_one_point']]}**",
        "",
        f"Result: features **{'ADOPTED' if d['adopted'] else 'NOT ADOPTED'}** on this test.",
        "",
        "### Slices",
        "",
    ]
    for name, rows in r["slices"].items():
        lines += [
            f"**{name}**",
            "",
            "| Segment | Zone-hours | Base | Holiday features | Difference (pp) |",
            "|---|---:|---:|---:|---:|",
        ]
        for row in rows:
            lines.append(
                f"| {row['segment']} | {row['n']:,} | {_p(row['base']['wape'])} "
                f"| {_p(row['holiday']['wape'])} | {_pp(row['difference'])} |"
            )
        lines.append("")
    return lines


def render(report: dict[str, Any]) -> str:
    lines = [
        f"# Holiday and long-weekend features: pre-registered experiment ({report['data_label']})",
        "",
        f"Generated {report['generated_at_utc']} from data run `{report['data_run_id']}`. "
        "Hypothesis, features, evaluation and decision rule were committed before any of this was "
        f"run: [{report['preregistration']}](../{report['preregistration']}). Both models use "
        "identical settings and folds; only the two calendar features differ.",
        "",
    ]
    lines += _section(report["primary"], "Primary test")
    if report["secondary"]:
        lines += _section(report["secondary"], "Secondary check (cannot overrule the primary)")
    return "\n".join(lines).rstrip() + "\n"
