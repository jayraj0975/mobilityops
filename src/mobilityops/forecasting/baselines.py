"""Baselines the model must beat. They use the same leak-free history features as the model.

* ``naive``: demand at the same hour yesterday (persistence).
* ``seasonal_naive``: demand at the same hour, same weekday, one week ago.
* ``seasonal_mean_4w``: mean of that weekday+hour over the previous four weeks; a much harder
  baseline because averaging removes the noise a single-week copy carries.

A baseline value can be missing (for example a lag that falls on the skipped spring-forward hour).
The fallback chain below is applied identically to every baseline, and the number of fallbacks is
reported so it is never hidden.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

BASELINES: dict[str, str] = {
    "naive": "lag_1d",
    "seasonal_naive": "lag_7d",
    "seasonal_mean_4w": "same_dow_hour_mean_4w",
}
_FALLBACKS: tuple[str, ...] = ("same_dow_hour_mean_4w", "lag_7d", "lag_1d", "same_hour_mean_7d")


def baseline_forecasts(frame: pd.DataFrame) -> tuple[dict[str, np.ndarray], dict[str, int]]:
    """Return ``({name: predictions}, {name: number of rows that needed a fallback})``."""
    out: dict[str, np.ndarray] = {}
    fallbacks: dict[str, int] = {}
    for name, primary in BASELINES.items():
        pred = frame[primary].to_numpy(dtype=float).copy()
        missing = np.isnan(pred)
        fallbacks[name] = int(missing.sum())
        for col in _FALLBACKS:
            still = np.isnan(pred)
            if not still.any():
                break
            pred[still] = frame[col].to_numpy(dtype=float)[still]
        pred[np.isnan(pred)] = 0.0  # only possible with no history at all
        out[name] = pred
    return out, fallbacks
