"""How do we know the detector works? Two checks, both honest about what they are.

1. **Planted ground truth (synthetic sample only).** The synthetic generator records exactly which
   anomalies it planted. We measure how many were found and how many events are not planted ones.
   This proves the mechanism works on data where the truth is known; it says nothing about real
   taxi demand.

2. **Injection experiment (any data, including real).** Real data has no ground-truth anomaly
   labels, so detection accuracy on it is UNVERIFIED. What can be measured is *sensitivity*: take
   the real out-of-sample forecasts and residuals, multiply the actuals in a random window of a
   random zone by a chosen factor, and ask whether the detector would have flagged that window.
   The noise is the real forecast error; the anomaly is artificial ("semi-synthetic"). It answers
   "how big must a deviation be, at each demand level, before we would notice it?".
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from mobilityops.anomaly.detect import AnomalyConfig, NullModel, ScaleModel
from mobilityops.forecasting.features import HOURS, DemandTensor
from mobilityops.sample import Anomaly


# --------------------------------------------------------------------------- planted truth
def match_planted(
    events: pd.DataFrame,
    planted: tuple[Anomaly, ...],
    t: DemandTensor,
    n_scored_zone_days: int,
) -> dict[str, Any]:
    """Recall against planted anomalies, and events that match none of them."""
    matched_events: set[int] = set()
    found: list[dict[str, Any]] = []
    for a in planted:
        s = t.days[0] + pd.Timedelta(days=a.day, hours=a.start_hour)
        e = s + pd.Timedelta(hours=a.hours)
        hit = events[
            (events["location_id"] == a.zone)
            & (events["direction"] == a.kind)
            & (events["start"] < e)
            & (events["end"] > s)
        ]
        matched_events.update(int(i) for i in hit.index)
        found.append(
            {
                "zone": a.zone,
                "kind": a.kind,
                "start": s.isoformat(),
                "hours": a.hours,
                "found": bool(len(hit)),
                "event_z": float(hit["event_z"].iloc[0]) if len(hit) else None,
            }
        )
    unmatched = len(events) - len(matched_events)
    return {
        "planted": len(planted),
        "found": sum(f["found"] for f in found),
        "recall": sum(f["found"] for f in found) / len(planted) if planted else None,
        "events_total": len(events),
        "events_not_planted": unmatched,
        "not_planted_per_1000_zone_days": 1000 * unmatched / n_scored_zone_days
        if n_scored_zone_days
        else None,
        "details": found,
    }


# ----------------------------------------------------------------------------- injection
@dataclass(frozen=True)
class InjectionSpec:
    factors: tuple[float, ...] = (0.2, 0.5, 1.5, 2.0, 3.0)
    durations: tuple[int, ...] = (1, 3, 6)
    trials: int = 40
    seed: int = 11
    bands: tuple[tuple[str, float, float], ...] = (
        ("1-5/h", 1.0, 5.0),
        ("5-20/h", 5.0, 20.0),
        ("20-100/h", 20.0, 100.0),
        (">=100/h", 100.0, float("inf")),
    )


def _cube(predictions: pd.DataFrame, n_zones: int, n_days: int, col: str) -> np.ndarray:
    a = np.full((n_zones, n_days, HOURS), np.nan)
    a[
        predictions["zone_index"].to_numpy(),
        predictions["day_index"].to_numpy(),
        predictions["hour"].to_numpy(),
    ] = predictions[col].to_numpy(dtype=float)
    return a


def _detected(
    z: np.ndarray,
    resid: np.ndarray,
    scale: np.ndarray,
    sign: int,
    cfg: AnomalyConfig,
    null: NullModel,
) -> bool:
    """Window-local version of the event rule (seed, merge, pool, standardise, size filter)."""
    hit = np.where(sign * z >= cfg.z_seed)[0]
    if len(hit) == 0:
        return False
    for g in np.split(hit, np.where(np.diff(hit) > cfg.max_gap_hours + 1)[0] + 1):
        lo, hi = int(g[0]), int(g[-1]) + 1
        excess = float(resid[lo:hi].sum())
        pooled = excess / float(np.sqrt(np.sum(scale[lo:hi] ** 2)))
        if abs(pooled) / null(hi - lo) >= cfg.event_threshold and abs(excess) >= cfg.min_excess:
            return True
    return False


def injection_experiment(
    predictions: pd.DataFrame,
    scale: ScaleModel,
    null: NullModel,
    n_zones: int,
    n_days: int,
    cfg: AnomalyConfig,
    spec: InjectionSpec | None = None,
) -> list[dict[str, Any]]:
    """Recall of artificial surges/drops by demand band, factor and duration."""
    spec = spec or InjectionSpec()
    y = _cube(predictions, n_zones, n_days, "y")
    p = _cube(predictions, n_zones, n_days, "lightgbm")
    rng = np.random.default_rng(spec.seed)
    rows: list[dict[str, Any]] = []
    for dur in spec.durations:
        # window mean forecast and validity for every (zone, day, start hour)
        starts = HOURS - dur + 1
        win_mean = np.stack([p[:, :, s : s + dur].mean(axis=2) for s in range(starts)], axis=2)
        valid = np.stack(
            [~np.isnan(y[:, :, s : s + dur]).any(axis=2) for s in range(starts)], axis=2
        ) & ~np.isnan(win_mean)
        for name, lo, hi in spec.bands:
            cand = np.argwhere(valid & (win_mean >= lo) & (win_mean < hi))
            if len(cand) == 0:
                continue
            picks = cand[rng.integers(0, len(cand), size=spec.trials)]
            for factor in spec.factors:
                sign = 1 if factor > 1 else -1
                found = 0
                for z, d, s in picks:
                    pred = p[z, d, s : s + dur]
                    injected = np.rint(y[z, d, s : s + dur] * factor)
                    resid = injected - pred
                    sc = scale(pred)
                    found += _detected(resid / sc, resid, sc, sign, cfg, null)
                rows.append(
                    {
                        "band": name,
                        "duration_hours": dur,
                        "factor": factor,
                        "trials": len(picks),
                        "detected": int(found),
                        "recall": found / len(picks),
                    }
                )
    return rows
