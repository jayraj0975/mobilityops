"""Walk-forward (rolling-origin) evaluation, error analysis and the final-model workflow.

Validation design
-----------------
Data are cut in time, never shuffled. The last ``n_folds * fold_days`` days are test days, split
into consecutive folds. For each fold ``k`` starting at day ``F``::

    train        : days [MIN_HISTORY, F - calib_days)     model is fitted here
    calibration  : days [F - calib_days, F)               interval width is measured here
    test         : days [F, F + fold_days)                scored; never seen in any earlier step

Every test day is forecast from its own 00:00 origin using only earlier days (see ``features``),
with the model held fixed inside the fold and refitted at the next fold boundary: exactly how a
scheduled retrain would run. Because folds move forward, later folds train on more data.

Metrics: MAE, RMSE and WAPE (sum |error| / sum actual: unlike MAPE it is defined when demand is
zero and is not dominated by tiny zones). Uncertainty is judged by *empirical* coverage of the 80%
interval on the test days. Improvement over each baseline comes with a day-level bootstrap
interval, because days (not rows) are the independent-ish units.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd

from mobilityops.config import Settings
from mobilityops.forecasting.baselines import BASELINES, baseline_forecasts
from mobilityops.forecasting.features import (
    CATEGORICAL_FEATURES,
    HOURS,
    LONGEST_LOOKBACK_DAYS,
    MIN_HISTORY_DAYS,
    DemandTensor,
    build_features,
    feature_columns,
    hour_timestamps,
    load_demand,
)
from mobilityops.forecasting.model import (
    DEFAULT_COVERAGE,
    ForecastModel,
    fit_model,
    save_model,
)
from mobilityops.log import get_logger

log = get_logger("forecasting.evaluate")

MODEL = "lightgbm"
ALL_MODELS: tuple[str, ...] = (MODEL, *BASELINES)
VOLUME_BINS = [-np.inf, 1.0, 5.0, 20.0, np.inf]
VOLUME_LABELS = ["<1/h", "1-5/h", "5-20/h", ">=20/h"]
MIN_TRAIN_DAYS = 14
BOOTSTRAP_RESAMPLES = 2000


@dataclass(frozen=True)
class EvalConfig:
    n_folds: int = 4
    fold_days: int = 14
    calib_days: int = 14
    coverage: float = DEFAULT_COVERAGE
    oracle_weather: bool = False
    holiday_features: bool = False  # pre-registered experiment; the shipped model leaves it off
    params: dict[str, Any] = field(default_factory=dict)
    seed: int = 7


def default_config(n_days: int) -> EvalConfig:
    """Sensible fold sizes for the amount of history available."""
    if n_days >= 120:
        return EvalConfig(n_folds=4, fold_days=14, calib_days=14)
    if n_days >= 56:
        return EvalConfig(n_folds=3, fold_days=7, calib_days=7)
    return EvalConfig(n_folds=2, fold_days=4, calib_days=4)


@dataclass(frozen=True)
class Fold:
    index: int
    train: range
    calibration: range
    test: range


def fold_windows(n_days: int, cfg: EvalConfig) -> list[Fold]:
    first_test = n_days - cfg.n_folds * cfg.fold_days
    folds: list[Fold] = []
    for i in range(cfg.n_folds):
        f = first_test + i * cfg.fold_days
        train = range(MIN_HISTORY_DAYS, f - cfg.calib_days)
        if len(train) < MIN_TRAIN_DAYS:
            raise ValueError(
                f"fold {i} would train on only {len(train)} days (need >= {MIN_TRAIN_DAYS}); "
                f"have {n_days} days of data. Use fewer/shorter folds or ingest more months."
            )
        folds.append(Fold(i, train, range(f - cfg.calib_days, f), range(f, f + cfg.fold_days)))
    return folds


# ---------------------------------------------------------------------------------- metrics
def metrics(y: np.ndarray, p: np.ndarray) -> dict[str, float | int | None]:
    """MAE, RMSE, WAPE and relative bias. ``None`` where a ratio is undefined (no demand)."""
    n = len(y)
    if n == 0:
        return {"n": 0, "mae": None, "rmse": None, "wape": None, "bias": None}
    err = p - y
    total = float(np.sum(y))
    return {
        "n": int(n),
        "mae": float(np.mean(np.abs(err))),
        "rmse": float(np.sqrt(np.mean(err**2))),
        "wape": float(np.sum(np.abs(err)) / total) if total > 0 else None,
        "bias": float(np.sum(err) / total) if total > 0 else None,
    }


def _groups(df: pd.DataFrame, key: Any) -> list[tuple[Any, pd.DataFrame]]:
    """``groupby`` with untyped keys; pandas' stubs type them too loosely to convert cleanly."""
    return [(k, g) for k, g in df.groupby(key, observed=True)]


def _table(df: pd.DataFrame, models: tuple[str, ...]) -> dict[str, dict[str, Any]]:
    return {m: metrics(df["y"].to_numpy(float), df[m].to_numpy(float)) for m in models}


def _segments(df: pd.DataFrame, key: pd.Series, models: tuple[str, ...]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for label, part in df.groupby(key, observed=True):
        row: dict[str, Any] = {
            "segment": str(label),
            "n": len(part),
            "mean_actual": float(part["y"].mean()),
        }
        for m in models:
            mm = metrics(part["y"].to_numpy(float), part[m].to_numpy(float))
            row[m] = {"mae": mm["mae"], "wape": mm["wape"]}
        rows.append(row)
    return rows


def _interval_stats(df: pd.DataFrame) -> dict[str, Any]:
    covered = (df["y"] >= df["lo"]) & (df["y"] <= df["hi"])
    return {
        "n": len(df),
        "coverage": float(covered.mean()) if len(df) else None,
        "mean_width": float((df["hi"] - df["lo"]).mean()) if len(df) else None,
    }


def _bootstrap(df: pd.DataFrame, seed: int) -> dict[str, Any]:
    """Day-level bootstrap of WAPE(baseline) - WAPE(model): positive means the model is better."""
    day = df["day_index"].to_numpy()
    uniq, inv = np.unique(day, return_inverse=True)
    y_by_day = np.bincount(inv, weights=df["y"].to_numpy(float))
    abs_by_day = {
        m: np.bincount(inv, weights=np.abs(df[m].to_numpy(float) - df["y"].to_numpy(float)))
        for m in ALL_MODELS
    }
    rng = np.random.default_rng(seed)
    draws = rng.integers(0, len(uniq), size=(BOOTSTRAP_RESAMPLES, len(uniq)))
    denom = y_by_day[draws].sum(axis=1)
    wape = {m: abs_by_day[m][draws].sum(axis=1) / denom for m in ALL_MODELS}
    point = {m: float(abs_by_day[m].sum() / y_by_day.sum()) for m in ALL_MODELS}

    def ci(a: np.ndarray) -> list[float]:
        return [float(np.percentile(a, 2.5)), float(np.percentile(a, 97.5))]

    out: dict[str, Any] = {
        "resamples": BOOTSTRAP_RESAMPLES,
        "unit": "test day",
        "n_days": len(uniq),
        "wape_ci95": {m: ci(wape[m]) for m in ALL_MODELS},
        "improvement": {},
    }
    for b in BASELINES:
        diff = wape[b] - wape[MODEL]
        out["improvement"][b] = {
            "wape_point_difference": point[b] - point[MODEL],
            "relative_reduction_point": (point[b] - point[MODEL]) / point[b],
            "difference_ci95": ci(diff),
            "model_better_in_share_of_resamples": float(np.mean(diff > 0)),
        }
    return out


# ---------------------------------------------------------------------------- walk-forward
@dataclass
class WalkForward:
    predictions: pd.DataFrame
    folds: list[dict[str, Any]]
    last_model: ForecastModel
    fallbacks: dict[str, int]


def walk_forward(t: DemandTensor, cfg: EvalConfig) -> WalkForward:
    frame = build_features(
        t, oracle_weather=cfg.oracle_weather, holiday_features=cfg.holiday_features
    )
    features = feature_columns(cfg.oracle_weather, cfg.holiday_features)
    base, fallbacks = baseline_forecasts(frame)
    day = frame["day_index"].to_numpy()
    observed = frame["target"].notna().to_numpy()
    parts: list[pd.DataFrame] = []
    info: list[dict[str, Any]] = []
    model: ForecastModel | None = None
    for fold in fold_windows(t.n_days, cfg):
        in_train = (day >= fold.train.start) & (day < fold.train.stop)
        in_cal = (day >= fold.calibration.start) & (day < fold.calibration.stop)
        in_test = (day >= fold.test.start) & (day < fold.test.stop) & observed
        model = fit_model(
            frame[in_train],
            frame[in_cal],
            features,
            list(CATEGORICAL_FEATURES),
            coverage=cfg.coverage,
            params=cfg.params,
        )
        test = frame[in_test]
        pred = model.predict(test)
        part = pd.DataFrame(
            {
                "fold": fold.index,
                "zone_index": test["zone_index"].to_numpy(),
                "location_id": test["location_id"].to_numpy(),
                "day_index": test["day_index"].to_numpy(),
                "hour": test["hour"].to_numpy(),
                "mean_28d": test["mean_28d"].to_numpy(),
                "y": test["target"].to_numpy(dtype=float),
                MODEL: pred["pred"].to_numpy(),
                "lo": pred["lo"].to_numpy(),
                "hi": pred["hi"].to_numpy(),
            }
        )
        for name, values in base.items():
            part[name] = values[in_test]
        parts.append(part)
        info.append(
            {
                "fold": fold.index,
                "train_days": [t.days[fold.train.start].date(), t.days[fold.train.stop - 1].date()],
                "calibration_days": [
                    t.days[fold.calibration.start].date(),
                    t.days[fold.calibration.stop - 1].date(),
                ],
                "test_days": [t.days[fold.test.start].date(), t.days[fold.test.stop - 1].date()],
                "train_rows": int(np.sum(in_train & observed)),
                "conformal_q_bins": [round(q, 3) for q in model.q_bins],
            }
        )
        log.info("fold done", extra={"ctx": {"fold": fold.index, "test_rows": len(test)}})
    assert model is not None
    preds = pd.concat(parts, ignore_index=True)
    preds["hour_ts"] = hour_timestamps(t, preds)
    return WalkForward(preds, info, model, fallbacks)


def summarize(t: DemandTensor, wf: WalkForward, cfg: EvalConfig) -> dict[str, Any]:
    df = wf.predictions
    dates = pd.DatetimeIndex(t.days[df["day_index"].to_numpy()])
    df = df.assign(
        dow=dates.dayofweek.to_numpy(),
        holiday=t.calendar["is_holiday"].to_numpy()[df["day_index"].to_numpy()],
        rain=t.weather["is_rain"].astype("object").to_numpy()[df["day_index"].to_numpy()],
        borough=t.zones["borough"].to_numpy()[df["zone_index"].to_numpy()],
    )
    volume = pd.cut(df["mean_28d"], VOLUME_BINS, labels=VOLUME_LABELS)
    weekday = df["dow"].map(dict(enumerate(["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"])))
    rain = df["rain"].map({True: "rain day", False: "dry day"}).fillna("no weather data")
    holiday = df["holiday"].map({True: "holiday", False: "ordinary day"})

    city = (
        df.groupby("hour_ts")[["y", *ALL_MODELS]].sum().reset_index()
    )  # forecasts summed over zones vs actual city total, per hour

    df["abs_err"] = (df[MODEL] - df["y"]).abs()
    zone_day = df.groupby(["zone_index", "day_index"], as_index=False).agg(
        y=("y", "sum"), pred=(MODEL, "sum"), abs_err=("abs_err", "sum")
    )
    worst = zone_day.sort_values("abs_err", ascending=False).head(10)
    worst_rows = [
        {
            "location_id": int(t.zones["location_id"].iloc[z]),
            "zone": str(t.zones["zone"].iloc[z]),
            "borough": str(t.zones["borough"].iloc[z]),
            "date": t.days[d].date().isoformat(),
            "actual_day_pickups": float(actual),
            "forecast_day_pickups": round(float(pred), 1),
            "abs_error": round(float(err), 1),
            "is_holiday": bool(t.calendar["is_holiday"].iloc[d]),
        }
        for z, d, actual, pred, err in zip(
            worst["zone_index"].to_numpy(dtype=int),
            worst["day_index"].to_numpy(dtype=int),
            worst["y"].to_numpy(dtype=float),
            worst["pred"].to_numpy(dtype=float),
            worst["abs_err"].to_numpy(dtype=float),
            strict=True,
        )
    ]

    overall = _table(df, ALL_MODELS)
    best_baseline = min(BASELINES, key=lambda m: overall[m]["wape"] or np.inf)
    seg_models = tuple(dict.fromkeys((MODEL, "seasonal_naive", best_baseline)))
    return {
        "test_rows": len(df),
        "test_days": int(df["day_index"].nunique()),
        "zones": int(df["zone_index"].nunique()),
        "overall": overall,
        "best_baseline": best_baseline,
        "by_fold": {int(k): _table(g, ALL_MODELS) for k, g in _groups(df, "fold")},
        "city_total_hourly": _table(city, ALL_MODELS),
        "bootstrap": _bootstrap(df, cfg.seed),
        "by_volume": _segments(df, volume, seg_models),
        "by_hour": _segments(df, df["hour"], seg_models),
        "by_weekday": _segments(df, weekday, seg_models),
        "by_holiday": _segments(df, holiday, seg_models),
        "by_weather_context": _segments(df, rain, seg_models),
        "by_borough": _segments(df, df["borough"], seg_models),
        "interval": {
            "nominal": cfg.coverage,
            "overall": _interval_stats(df),
            "by_fold": {int(k): _interval_stats(g) for k, g in _groups(df, "fold")},
            "by_volume": {str(k): _interval_stats(g) for k, g in _groups(df, volume)},
            "by_hour": {int(k): _interval_stats(g) for k, g in _groups(df, "hour")},
        },
        "worst_zone_days": worst_rows,
        "baseline_fallback_rows": wf.fallbacks,
        "feature_importance_last_fold": wf.last_model.feature_importance(),
    }


# ------------------------------------------------------------------------------ orchestration
def _with_threads(cfg: EvalConfig, settings: Settings) -> EvalConfig:
    """Apply MOBILITYOPS_THREADS (0 = leave LightGBM's default) unless the config sets its own."""
    if settings.threads and "num_threads" not in cfg.params:
        return replace(cfg, params={**cfg.params, "num_threads": settings.threads})
    return cfg


def data_run_id(db_path: Path) -> str | None:
    con = duckdb.connect(str(db_path), read_only=True)
    try:
        row = con.execute(
            "SELECT run_id FROM pipeline_run ORDER BY built_at_utc DESC LIMIT 1"
        ).fetchone()
    finally:
        con.close()
    return str(row[0]) if row else None


def run_evaluation(
    settings: Settings, cfg: EvalConfig | None = None, *, oracle_experiment: bool = True
) -> dict[str, Any]:
    """Walk-forward evaluation on the gold layer; writes the report and predictions to artifacts."""
    t = load_demand(settings.db_path)
    cfg = cfg or default_config(t.n_days)
    cfg = _with_threads(cfg, settings)
    wf = walk_forward(t, cfg)
    report: dict[str, Any] = {
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "mode": settings.mode,
        "data_label": "TEST / SYNTHETIC DATA" if settings.mode == "sample" else "real data",
        "data_run_id": data_run_id(settings.db_path),
        "data_days": [t.days[0].date(), t.days[-1].date()],
        "config": asdict(cfg),
        "folds": wf.folds,
        "problem": (
            "day-ahead hourly pickups per zone; origin = 00:00 of the target day; "
            "history features use only earlier days; weather is not a feature"
        ),
        **summarize(t, wf, cfg),
    }
    if oracle_experiment:
        ocfg = EvalConfig(**{**asdict(cfg), "oracle_weather": True})
        owf = walk_forward(t, ocfg)
        o = _table(owf.predictions, (MODEL,))[MODEL]
        base = report["overall"][MODEL]
        report["oracle_weather_experiment"] = {
            "label": "ORACLE: uses the target day's ACTUAL weather, which would have to be "
            "forecast in operation. An upper bound on what weather could add, not a result.",
            "wape_without_weather": base["wape"],
            "wape_with_oracle_weather": o["wape"],
            "mae_without_weather": base["mae"],
            "mae_with_oracle_weather": o["mae"],
        }
    out = settings.artifacts_dir / "forecast"
    out.mkdir(parents=True, exist_ok=True)
    (out / "evaluation.json").write_text(json.dumps(report, indent=2, default=str))
    keep = wf.predictions.drop(columns=["mean_28d"]).assign(y=lambda d: d["y"].astype("float32"))
    keep.to_parquet(out / "predictions.parquet", index=False)
    log.info("evaluation written", extra={"ctx": {"path": str(out / "evaluation.json")}})
    return report


def train_final(settings: Settings, cfg: EvalConfig | None = None) -> Path:
    """Fit on all data up to the last day (minus a calibration block) and register the model."""
    t = load_demand(settings.db_path)
    cfg = _with_threads(cfg or default_config(t.n_days), settings)
    frame = build_features(t)
    day = frame["day_index"].to_numpy()
    cal_start = t.n_days - cfg.calib_days
    train_rows = frame[(day < cal_start)]
    cal_rows = frame[(day >= cal_start)]
    if train_rows["day_index"].nunique() < MIN_TRAIN_DAYS:
        raise ValueError("not enough history to train a final model; ingest more months")
    model = fit_model(
        train_rows,
        cal_rows,
        feature_columns(),
        list(CATEGORICAL_FEATURES),
        coverage=cfg.coverage,
        params=cfg.params,
    )
    report_path = settings.artifacts_dir / "forecast" / "evaluation.json"
    metrics: dict[str, Any] = {}
    if report_path.exists():
        rep = json.loads(report_path.read_text())
        metrics = {
            "source": "walk-forward evaluation of this same procedure; this final model has no "
            "held-out test of its own",
            "overall": rep.get("overall"),
            "interval": rep.get("interval", {}).get("overall"),
        }
    model.meta = {
        "data_run_id": data_run_id(settings.db_path),
        "train_days": [
            t.days[MIN_HISTORY_DAYS].date(),
            t.days[cal_start - 1].date(),
        ],
        "calibration_days": [t.days[cal_start].date(), t.days[-1].date()],
        "horizon": "day-ahead, origin 00:00 local",
        "hours_per_day": HOURS,
    }
    return save_model(settings, model, metrics)


def forecast_next_day(t: DemandTensor, model: ForecastModel) -> pd.DataFrame:
    """Forecast every zone-hour of the day after the last observed day."""
    # Only the last weeks matter to the features; slicing keeps memory small (DemandTensor.tail).
    ext = t.tail(LONGEST_LOOKBACK_DAYS + MIN_HISTORY_DAYS + 3).extended(1)
    idx = ext.n_days - 1
    frame = build_features(ext, days=range(idx, idx + 1))
    pred = model.predict(frame)
    out = pd.DataFrame(
        {
            "location_id": frame["location_id"].to_numpy(),
            "hour_ts": hour_timestamps(ext, frame),
            "pred": pred["pred"].to_numpy(),
            "lo": pred["lo"].to_numpy(),
            "hi": pred["hi"].to_numpy(),
        }
    )
    return out
