"""LightGBM (Poisson) forecaster with split-conformal prediction intervals, and its registry.

Why these choices
-----------------
* **Poisson objective**: hourly zone pickups are non-negative counts, 57% of which are zero in the
  real data, and their variance grows with their mean.
* **Conformal intervals**: the model is fitted on early days, residuals are measured on a later
  calibration block it never saw, and the interval half-width is an empirical quantile of those
  residuals. The quantile is computed *separately for each band of predicted demand* (Mondrian
  conformal). A first version used one quantile scaled by ``sqrt(prediction + 1)`` (a Poisson
  assumption); the first real-data evaluation showed it covered only 41% of hours in busy zones
  and 95% in quiet ones, because real demand is over-dispersed. That change was made after seeing
  test-fold coverage; it is a calibration fix, not a model-accuracy tweak, and is recorded in
  docs/DECISIONS.md. The *empirical* coverage on held-out test days is measured and reported.
* **No hyper-parameter search**: parameters are fixed a priori (below). Tuning on the test folds
  would leak; a proper nested search is listed as future work rather than done sloppily.
* **Registry**: a model is a text file plus a JSON sidecar recording data run, window, features,
  parameters and metrics. That is all the reproducibility this scale needs (ADR-006).
"""

from __future__ import annotations

import json
import math
import platform
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import lightgbm as lgb
import numpy as np
import pandas as pd

from mobilityops.config import Settings

DEFAULT_PARAMS: dict[str, Any] = {
    "objective": "poisson",
    "learning_rate": 0.05,
    "num_boost_round": 400,
    "num_leaves": 63,
    "min_data_in_leaf": 50,
    "feature_fraction": 0.8,
    "bagging_fraction": 0.8,
    "bagging_freq": 1,
    "lambda_l2": 1.0,
    "seed": 7,
    "deterministic": True,
    "force_row_wise": True,
    "verbosity": -1,
}
DEFAULT_COVERAGE = 0.8


# Bands of predicted pickups per hour. Each band gets its own residual quantile.
PRED_BIN_EDGES: tuple[float, ...] = (0.5, 2.0, 5.0, 10.0, 20.0, 50.0)
MIN_BIN_ROWS = 200  # a band with fewer calibration rows falls back to the pooled quantile


def pred_bin(pred: np.ndarray) -> np.ndarray:
    return np.digitize(pred, PRED_BIN_EDGES)


def _quantile(scores: np.ndarray, coverage: float) -> float:
    n = len(scores)
    level = min(1.0, math.ceil((n + 1) * coverage) / n)  # finite-sample correction
    return float(np.quantile(scores, level, method="higher"))


def conformal_quantiles(y: np.ndarray, pred: np.ndarray, coverage: float) -> list[float]:
    """One absolute-residual quantile per prediction band (pooled quantile for sparse bands)."""
    if not 0 < coverage < 1:
        raise ValueError("coverage must be strictly between 0 and 1")
    if len(y) == 0:
        raise ValueError("cannot calibrate on zero rows")
    resid = np.abs(y - pred)
    pooled = _quantile(resid, coverage)
    band = pred_bin(pred)
    out: list[float] = []
    for b in range(len(PRED_BIN_EDGES) + 1):
        r = resid[band == b]
        out.append(_quantile(r, coverage) if len(r) >= MIN_BIN_ROWS else pooled)
    return out


@dataclass
class ForecastModel:
    booster: lgb.Booster
    features: list[str]
    categorical: list[str]
    q_bins: list[float]  # absolute-residual quantile for each prediction band
    coverage: float
    params: dict[str, Any]
    meta: dict[str, Any] = field(default_factory=dict)

    def predict(self, frame: pd.DataFrame) -> pd.DataFrame:
        raw = self.booster.predict(_matrix(frame, self.features, self.categorical))
        pred = np.asarray(raw, dtype=float)
        half = np.asarray(self.q_bins)[pred_bin(pred)]
        return pd.DataFrame({"pred": pred, "lo": np.maximum(pred - half, 0.0), "hi": pred + half})

    def feature_importance(self) -> dict[str, float]:
        gain = self.booster.feature_importance(importance_type="gain")
        total = float(gain.sum()) or 1.0
        pairs = sorted(zip(self.features, gain, strict=True), key=lambda p: -p[1])
        return {name: round(float(g) / total, 4) for name, g in pairs}


def _matrix(frame: pd.DataFrame, features: list[str], categorical: list[str]) -> pd.DataFrame:
    x = frame[features].copy()
    for c in categorical:
        x[c] = x[c].astype("category")
    return x


def fit_model(
    train: pd.DataFrame,
    calibration: pd.DataFrame,
    features: list[str],
    categorical: list[str],
    *,
    coverage: float = DEFAULT_COVERAGE,
    params: dict[str, Any] | None = None,
    meta: dict[str, Any] | None = None,
) -> ForecastModel:
    """Fit on ``train``; calibrate on ``calibration`` (which must come after ``train``)."""
    merged = {**DEFAULT_PARAMS, **(params or {})}
    train = train[train["target"].notna()]
    calibration = calibration[calibration["target"].notna()]
    if train.empty or calibration.empty:
        raise ValueError("training and calibration sets must both contain observed targets")
    native = dict(merged)
    rounds = int(native.pop("num_boost_round"))
    data = lgb.Dataset(
        _matrix(train, features, categorical),
        label=train["target"].to_numpy(dtype=float),
        categorical_feature=categorical,
    )
    booster = lgb.train(native, data, num_boost_round=rounds)
    raw = booster.predict(_matrix(calibration, features, categorical))
    pred = np.asarray(raw, dtype=float)
    q_bins = conformal_quantiles(calibration["target"].to_numpy(dtype=float), pred, coverage)
    return ForecastModel(
        booster, list(features), list(categorical), q_bins, coverage, merged, meta or {}
    )


# ------------------------------------------------------------------------------------ registry
def models_dir(settings: Settings) -> Path:
    return settings.artifacts_dir / "forecast" / "models"


def save_model(settings: Settings, model: ForecastModel, metrics: dict[str, Any]) -> Path:
    """Write ``model.txt`` and ``meta.json`` under a new id and point ``latest.json`` at it."""
    created = datetime.now(UTC)
    model_id = created.strftime("%Y%m%dT%H%M%SZ")
    out = models_dir(settings) / model_id
    out.mkdir(parents=True, exist_ok=True)
    model.booster.save_model(str(out / "model.txt"))
    meta = {
        "model_id": model_id,
        "created_at_utc": created.isoformat(),
        "mode": settings.mode,
        "data_label": "TEST / SYNTHETIC DATA" if settings.mode == "sample" else "real data",
        "features": model.features,
        "categorical": model.categorical,
        "conformal_q_bins": model.q_bins,
        "pred_bin_edges": list(PRED_BIN_EDGES),
        "nominal_coverage": model.coverage,
        "params": model.params,
        "metrics": metrics,
        "versions": {"python": platform.python_version(), "lightgbm": lgb.__version__},
        **model.meta,
    }
    (out / "meta.json").write_text(json.dumps(meta, indent=2, default=str))
    (models_dir(settings) / "latest.json").write_text(json.dumps({"model_id": model_id}))
    return out


def load_model(settings: Settings, model_id: str | None = None) -> ForecastModel:
    root = models_dir(settings)
    if model_id is None:
        pointer = root / "latest.json"
        if not pointer.exists():
            raise FileNotFoundError(f"no trained model in {root}; run `forecast-train` first")
        model_id = str(json.loads(pointer.read_text())["model_id"])
    folder = root / model_id
    if not (folder / "model.txt").exists():
        raise FileNotFoundError(f"model {model_id} not found in {root}")
    meta = json.loads((folder / "meta.json").read_text())
    booster = lgb.Booster(model_file=str(folder / "model.txt"))
    extra = {k: v for k, v in meta.items() if k not in {"params", "features", "categorical"}}
    return ForecastModel(
        booster,
        list(meta["features"]),
        list(meta["categorical"]),
        [float(q) for q in meta["conformal_q_bins"]],
        float(meta["nominal_coverage"]),
        dict(meta["params"]),
        extra,
    )
