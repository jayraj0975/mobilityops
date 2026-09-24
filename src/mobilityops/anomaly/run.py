"""Run anomaly detection over the saved out-of-sample predictions and write the artifacts."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import pandas as pd

from mobilityops.anomaly.detect import AnomalyConfig, run_detection
from mobilityops.anomaly.validate import InjectionSpec, injection_experiment, match_planted
from mobilityops.config import Settings
from mobilityops.forecasting.evaluate import data_run_id
from mobilityops.forecasting.features import load_demand
from mobilityops.sample import SampleSpec


def anomaly_dir(settings: Settings):  # type: ignore[no-untyped-def]
    return settings.artifacts_dir / "anomaly"


def load_predictions(settings: Settings) -> pd.DataFrame:
    path = settings.artifacts_dir / "forecast" / "predictions.parquet"
    if not path.exists():
        raise FileNotFoundError(f"{path} not found; run `forecast-eval` first")
    return pd.read_parquet(path)


def accuracy_status(mode: str) -> str:
    if mode == "sample":
        return "verified against planted ground truth (synthetic data only)"
    if mode == "pune":
        return (
            "SIMULATED: events are the ones the generator planted, so detection rates describe "
            "the detector on simulated demand, not real Pune traffic"
        )
    return (
        "UNVERIFIED: real data has no anomaly labels; only injection-based sensitivity and "
        "manual plausibility review are available"
    )


def _busiest_days(events: pd.DataFrame, top: int = 8) -> list[dict[str, Any]]:
    if events.empty:
        return []
    days = events.assign(date=events["start"].dt.date.astype(str))
    counts = days.groupby("date").size().sort_values(ascending=False).head(top)
    return [
        {"date": d, "events": int(n), "share_of_all": float(n / len(events))}
        for d, n in counts.items()
    ]


def _threshold_sensitivity(
    preds: pd.DataFrame, t: Any, cfg: AnomalyConfig, zone_days: int
) -> list[dict[str, Any]]:
    """Event rate vs. injection recall as ``event_threshold`` varies (all else fixed)."""
    spec = InjectionSpec(factors=(0.5, 2.0), durations=(3, 6), trials=60, seed=cfg_seed())
    rows: list[dict[str, Any]] = []
    for thr in (4.0, 5.0, 6.0):
        c = replace(cfg, event_threshold=thr)
        ev, _, scale, null = run_detection(preds, t, c)
        inj = pd.DataFrame(injection_experiment(preds, scale, null, t.n_zones, t.n_days, c, spec))
        busy = inj[inj["band"].isin(["20-100/h", ">=100/h"])]
        recall = busy.groupby(["factor", "duration_hours"])["recall"].mean()
        rows.append(
            {
                "event_threshold": thr,
                "events": len(ev),
                "events_per_1000_zone_days": 1000 * len(ev) / zone_days if zone_days else None,
                "busy_zone_recall_surge_2x_3h": float(recall.get((2.0, 3), float("nan"))),
                "busy_zone_recall_surge_2x_6h": float(recall.get((2.0, 6), float("nan"))),
                "busy_zone_recall_drop_0.5x_3h": float(recall.get((0.5, 3), float("nan"))),
                "busy_zone_recall_drop_0.5x_6h": float(recall.get((0.5, 6), float("nan"))),
            }
        )
    return rows


def cfg_seed() -> int:
    return InjectionSpec().seed


def run_anomaly_detection(
    settings: Settings, cfg: AnomalyConfig | None = None, *, injection: bool = True
) -> dict[str, Any]:
    cfg = cfg or AnomalyConfig()
    t = load_demand(settings.db_path, settings.city)
    preds = load_predictions(settings)
    events, scored, scale, null = run_detection(preds, t, cfg)
    zone_days = int(preds.groupby(["zone_index", "day_index"]).ngroups)
    report: dict[str, Any] = {
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "mode": settings.mode,
        "data_label": settings.data_label,
        "data_run_id": data_run_id(settings.db_path),
        "method": "out-of-sample forecast residuals scaled by a tail-aware error curve; seed hours "
        "merged into events; pooled evidence standardised by an empirical null",
        "config": cfg.__dict__,
        "scale_model": {"floor": scale.floor, "bands": scale.details},
        "null_model_robust_sd_by_run_hours": {
            str(n): round(v, 3)
            for n, v in enumerate(null.sd, start=1)
            if n in (1, 2, 3, 6, 12, 24, 48)
        },
        "seed_share": float((scored["z"].abs() >= cfg.z_seed).mean()),
        "scored_zone_hours": len(scored),
        "scored_zone_days": zone_days,
        "scored_days": [
            t.days[int(preds["day_index"].min())].date().isoformat(),
            t.days[int(preds["day_index"].max())].date().isoformat(),
        ],
        "events_total": len(events),
        "events_per_1000_zone_days": 1000 * len(events) / zone_days if zone_days else None,
        "by_severity": events["severity"].value_counts().to_dict() if len(events) else {},
        "by_direction": events["direction"].value_counts().to_dict() if len(events) else {},
        "by_scope": events["scope"].value_counts().to_dict() if len(events) else {},
        "top_explanations": events["explanation"].head(15).tolist() if len(events) else [],
        "accuracy_status": accuracy_status(settings.mode),
    }
    if settings.mode == "sample":
        planted = SampleSpec().anomalies
        report["planted_truth"] = match_planted(events, planted, t, zone_days)
    if injection:
        rows = injection_experiment(preds, scale, null, t.n_zones, t.n_days, cfg, InjectionSpec())
        report["injection_experiment"] = {
            "label": "SEMI-SYNTHETIC: artificial surges/drops injected into real out-of-sample "
            "actuals; measures sensitivity, not real-world precision",
            "results": rows,
        }
    if injection:
        report["threshold_sensitivity"] = _threshold_sensitivity(preds, t, cfg, zone_days)
        report["busiest_days"] = _busiest_days(events)
    out = anomaly_dir(settings)
    out.mkdir(parents=True, exist_ok=True)
    events.to_parquet(out / "events.parquet", index=False)
    (out / "report.json").write_text(json.dumps(report, indent=2, default=str))
    return report
