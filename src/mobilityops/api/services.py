"""Shared, cached access to the database and the artifacts the API serves.

Everything here is read-only. Heavy objects (the demand tensor, forecasts, the model) are loaded
once and reloaded automatically when their file changes on disk, so rebuilding the data while the
server runs is safe and needs no restart.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any, TypeVar

import pandas as pd

from mobilityops.analytics.queries import Analytics
from mobilityops.config import Settings
from mobilityops.forecasting.features import DemandTensor, load_demand
from mobilityops.forecasting.model import ForecastModel, load_model, models_dir

T = TypeVar("T")

MAX_CONCURRENT_SOLVES = 2


class NotReady(RuntimeError):
    """A derived artifact has not been generated yet; the message says which command creates it."""


class Services:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._lock = threading.RLock()
        self._cache: dict[str, tuple[Any, Any]] = {}
        self._flight: dict[str, threading.Lock] = {}  # one loader per key at a time
        self.solver_slots = threading.BoundedSemaphore(MAX_CONCURRENT_SOLVES)

    # ---------------------------------------------------------------------------- plumbing
    def _flight_lock(self, key: str) -> threading.Lock:
        with self._lock:
            return self._flight.setdefault(key, threading.Lock())

    def _cached(self, key: str, path: Path, loader: Callable[[], T], missing_hint: str) -> T:
        """Load once per file version. Concurrent callers wait for one load instead of each
        repeating it (single-flight), which matters for the multi-second loads."""
        if not path.exists():
            raise NotReady(f"{path.name} not found; {missing_hint}")
        mtime = path.stat().st_mtime_ns
        with self._lock:
            hit = self._cache.get(key)
            if hit is not None and hit[0] == mtime:
                return hit[1]
        with self._flight_lock(key):
            with self._lock:  # someone else may have loaded it while we waited
                hit = self._cache.get(key)
                if hit is not None and hit[0] == mtime:
                    return hit[1]
            value = loader()
            with self._lock:
                self._cache[key] = (mtime, value)
            return value

    @property
    def artifacts(self) -> Path:
        return self.settings.artifacts_dir

    # ------------------------------------------------------------------------------ data
    def has_database(self) -> bool:
        return self.settings.db_path.exists()

    def analytics(self) -> Analytics:
        if not self.has_database():
            raise NotReady("database not found; run `ingest` and `build` first")
        return Analytics(self.settings.db_path)

    def tensor(self) -> DemandTensor:
        return self._cached(
            "tensor",
            self.settings.db_path,
            lambda: load_demand(self.settings.db_path, self.settings.city),
            "run `ingest` and `build` first",
        )

    # -------------------------------------------------------------------------- artifacts
    def _json(self, key: str, rel: str, hint: str) -> dict[str, Any]:
        path = self.artifacts / rel
        return self._cached(key, path, lambda: dict(json.loads(path.read_text())), hint)

    def evaluation(self) -> dict[str, Any]:
        return self._json("evaluation", "forecast/evaluation.json", "run `forecast-eval` first")

    def anomaly_report(self) -> dict[str, Any]:
        return self._json("anomaly_report", "anomaly/report.json", "run `anomalies` first")

    def backtest_report(self) -> dict[str, Any]:
        return self._json("backtest", "optimization/backtest.json", "run `optimize-backtest` first")

    def predictions(self) -> pd.DataFrame:
        path = self.artifacts / "forecast" / "predictions.parquet"
        return self._cached(
            "predictions", path, lambda: pd.read_parquet(path), "run `forecast-eval` first"
        )

    def events(self) -> pd.DataFrame:
        path = self.artifacts / "anomaly" / "events.parquet"
        return self._cached("events", path, lambda: pd.read_parquet(path), "run `anomalies` first")

    def model(self) -> ForecastModel:
        pointer = models_dir(self.settings) / "latest.json"
        return self._cached(
            "model", pointer, lambda: load_model(self.settings), "run `forecast-train` first"
        )

    def model_meta(self) -> dict[str, Any]:
        pointer = models_dir(self.settings) / "latest.json"
        model_id = str(json.loads(pointer.read_text())["model_id"]) if pointer.exists() else None
        if model_id is None:
            raise NotReady("no trained model; run `forecast-train` first")
        meta = models_dir(self.settings) / model_id / "meta.json"
        return dict(json.loads(meta.read_text()))

    def next_day(self) -> tuple[pd.DataFrame, str]:
        """Forecast for the day after the last observed day, cached per data+model version."""
        from mobilityops.forecasting.evaluate import forecast_next_day

        stamp = (
            self.settings.db_path.stat().st_mtime_ns if self.has_database() else 0,
            (models_dir(self.settings) / "latest.json").stat().st_mtime_ns
            if (models_dir(self.settings) / "latest.json").exists()
            else 0,
        )
        with self._lock:
            hit = self._cache.get("next_day")
            if hit is not None and hit[0] == stamp:
                return hit[1]
        with self._flight_lock("next_day"):
            with self._lock:
                hit = self._cache.get("next_day")
                if hit is not None and hit[0] == stamp:
                    return hit[1]
            model = self.model()
            frame = forecast_next_day(self.tensor(), model)
            model_id = str(self.model_meta()["model_id"])
            with self._lock:
                self._cache["next_day"] = (stamp, (frame, model_id))
            return frame, model_id

    def available(self) -> dict[str, bool]:
        a = self.artifacts
        return {
            "database": self.has_database(),
            "forecast_evaluation": (a / "forecast" / "evaluation.json").exists(),
            "forecast_model": (models_dir(self.settings) / "latest.json").exists(),
            "anomalies": (a / "anomaly" / "events.parquet").exists(),
            "optimization_backtest": (a / "optimization" / "backtest.json").exists(),
        }

    @property
    def data_label(self) -> str:
        return self.settings.data_label
