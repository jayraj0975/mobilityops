"""Residual-based anomaly detection on out-of-sample forecasts.

Idea
----
An "anomaly" here is a stretch of hours where a zone's pickups differ from what the forecaster
expected *by much more than its usual forecast error at that demand level*. Every score uses
predictions that were made without seeing the day being scored (the walk-forward test folds), so a
hard-to-predict day is not flagged merely because the model was fitted on it.

Steps
-----
1. ``residual = actual - forecast`` for each zone-hour.
2. **Scale.** The typical error grows with demand, so the spread of residuals is measured in bands
   of forecast demand and interpolated between bands (``ScaleModel``). The spread is taken from the
   95th percentile of ``|residual - median|`` divided by 1.96 rather than from the MAD: real
   errors are heavy-tailed, and a MAD-based scale understates them badly (a first version did, and
   flagged 25 events a day). Very quiet zones use a floor of ``min_scale`` pickups.
3. ``z = residual / scale(forecast)``. Hours with ``|z| >= z_seed`` are *seeds*.
4. **Events.** Consecutive same-sign seeds in one zone (gaps of up to ``max_gap_hours``) form a
   candidate event spanning ``n`` hours. Evidence is pooled over the span:
   ``sum(residual) / sqrt(sum(scale^2))``. A drop can never score below ``-forecast / scale`` in a
   single hour, so a six-hour collapse that anyone would call obvious only reaches z of about -3 per
   hour, yet is overwhelming as a run.
5. **Empirical null.** Forecast errors are correlated across hours, so the pooled score spreads out
   more than an independence assumption predicts. The spread of the pooled score over *all*
   n-hour windows (robust, MAD-based, windows with forecast >= ``null_min_forecast``) is measured
   from the data (``NullModel``) and each event's pooled score is divided by it. The result,
   ``event_z``, is in units of "typical n-hour fluctuation". Events with ``|event_z| >=
   event_threshold`` and total deviation of at least ``min_excess`` pickups are kept: a few pickups
   either way is not operationally meaningful however unusual it is statistically.
6. Each event is annotated with context (holiday, weather, whether other zones deviated too).

Limits stated up front: the null is estimated from the same data being scored (anomalies are rare
enough for MAD to ignore them, but they are not removed); real-data accuracy has no ground truth
and is UNVERIFIED; thresholds are conventions, not calibrated probabilities.

Language
--------
Detection says *what* deviated, not *why*. Explanations say the deviation "coincided with"
context. Nothing here establishes a cause.

Severity is a heuristic on ``|event_z|`` (low < 8 <= medium < 15 <= high), not a probability.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any, cast

import numpy as np
import pandas as pd

from mobilityops.forecasting.features import DemandTensor

TAIL_Z = 1.96  # 95th percentile of |N(0,1)|
HOURS = 24
BAND_EDGES: tuple[float, ...] = (0.5, 2.0, 5.0, 10.0, 20.0, 50.0, 100.0, 200.0, 400.0)


@dataclass(frozen=True)
class AnomalyConfig:
    z_seed: float = 2.0  # an hour this far from forecast can start or extend an event
    event_threshold: float = 5.0  # pooled evidence (see module docstring) needed to keep it
    min_excess: float = 10.0  # pickups: total |actual - forecast| over the event's flagged hours
    min_scale: float = 1.0  # a forecast error of ~1 pickup is noise at any volume
    null_min_forecast: float = 3.0  # windows at least this busy inform the empirical null
    null_max_hours: int = 48  # longest run length for which a null spread is measured
    max_gap_hours: int = 1  # unflagged hours tolerated inside one event
    min_band_rows: int = 300  # bands with fewer rows are not used to build the scale curve
    context_z: float = 2.0  # |z| at which another zone counts as "also deviating"
    widespread_share: float = 0.25  # share of zones deviating together => city-wide pattern
    isolated_share: float = 0.05


@dataclass(frozen=True)
class ScaleModel:
    """Piecewise-linear (in log space) interpolation of the residual spread by forecast level."""

    log_forecast: tuple[float, ...]  # log(mean forecast + 1) of each band with enough rows
    log_sigma: tuple[float, ...]
    floor: float
    details: list[dict[str, float]] = field(default_factory=list)

    def __call__(self, forecast: np.ndarray) -> np.ndarray:
        x = np.log(np.maximum(forecast, 0.0) + 1.0)
        raw = np.exp(np.interp(x, self.log_forecast, self.log_sigma))
        return np.maximum(raw, self.floor)


def fit_scale(pred: np.ndarray, resid: np.ndarray, cfg: AnomalyConfig) -> ScaleModel:
    """Measure the residual spread per forecast band from out-of-sample residuals."""
    band = np.digitize(pred, BAND_EDGES)
    xs: list[float] = []
    ys: list[float] = []
    details: list[dict[str, float]] = []
    for b in range(len(BAND_EDGES) + 1):
        m = band == b
        n = int(m.sum())
        if n < cfg.min_band_rows:
            continue
        r = resid[m]
        centre = float(np.median(r))
        sigma = float(np.quantile(np.abs(r - centre), 0.95)) / TAIL_Z
        mean_pred = float(pred[m].mean())
        details.append({"band": b, "rows": n, "mean_forecast": mean_pred, "sigma": sigma})
        xs.append(float(np.log(mean_pred + 1.0)))
        ys.append(float(np.log(max(sigma, 1e-3))))
    if not xs:
        centre = float(np.median(resid))
        overall = float(np.quantile(np.abs(resid - centre), 0.95)) / TAIL_Z
        return ScaleModel((0.0,), (float(np.log(max(overall, 1e-3))),), cfg.min_scale, [])
    return ScaleModel(tuple(xs), tuple(ys), cfg.min_scale, details)


class Series:
    """Per-zone hourly series (zones x hours) with prefix sums, for sums over arbitrary spans."""

    def __init__(self, scored: pd.DataFrame) -> None:
        self.n_zones = int(scored["zone_index"].max()) + 1
        self.n_hours = (int(scored["day_index"].max()) + 1) * HOURS
        idx = (
            scored["zone_index"].to_numpy(),
            scored["day_index"].to_numpy() * HOURS + scored["hour"].to_numpy(),
        )

        def fill(col: str) -> np.ndarray:
            a = np.full((self.n_zones, self.n_hours), np.nan)
            a[idx] = scored[col].to_numpy(dtype=float)
            return a

        self.resid = fill("residual")
        self.scale_sq = fill("scale") ** 2
        self.forecast = fill("lightgbm")
        self._c_resid = self._prefix(self.resid)
        self._c_var = self._prefix(self.scale_sq)
        self._c_fc = self._prefix(self.forecast)
        self._c_bad = self._prefix(np.isnan(self.resid).astype(float), nan=False)

    @staticmethod
    def _prefix(a: np.ndarray, nan: bool = True) -> np.ndarray:
        c = np.cumsum(np.nan_to_num(a) if nan else a, axis=1)
        return np.concatenate([np.zeros((a.shape[0], 1)), c], axis=1)

    def window_sums(self, n: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Sum of residuals, of variances and mean forecast per n-hour window (NaN if a gap)."""
        s = self._c_resid[:, n:] - self._c_resid[:, :-n]
        v = self._c_var[:, n:] - self._c_var[:, :-n]
        f = (self._c_fc[:, n:] - self._c_fc[:, :-n]) / n
        bad = (self._c_bad[:, n:] - self._c_bad[:, :-n]) > 0
        s[bad] = np.nan
        return s, v, f

    def span(self, zone: int, start: int, end: int) -> tuple[float, float]:
        """(sum of residuals, sum of variances) over hours ``[start, end)``."""
        r = self._c_resid[zone, end] - self._c_resid[zone, start]
        v = self._c_var[zone, end] - self._c_var[zone, start]
        return float(r), float(v)


@dataclass(frozen=True)
class NullModel:
    """Robust spread of the pooled score for runs of n hours (index n-1), measured from data."""

    sd: tuple[float, ...]

    def __call__(self, n: int) -> float:
        return self.sd[min(max(n, 1), len(self.sd)) - 1]


def fit_null(series: Series, cfg: AnomalyConfig) -> NullModel:
    """Robust sd of the pooled score over all n-hour windows, for n = 1..null_max_hours.

    Never below 1: where quiet-zone discreteness makes the spread smaller than an independent
    unit-variance score, using 1 is the conservative choice.
    """
    sds: list[float] = []
    for n in range(1, min(cfg.null_max_hours, series.n_hours - 1) + 1):
        s, v, f = series.window_sums(n)
        ok = ~np.isnan(s) & (f >= cfg.null_min_forecast) & (v > 0)
        if int(ok.sum()) < 500:
            sds.append(sds[-1] if sds else 1.0)
            continue
        pooled = s[ok] / np.sqrt(v[ok])
        sds.append(max(1.0, float(1.4826 * np.median(np.abs(pooled - np.median(pooled))))))
    return NullModel(tuple(np.maximum.accumulate(sds)))  # spread cannot shrink as runs lengthen


def score(
    predictions: pd.DataFrame, scale: ScaleModel, model_col: str = "lightgbm"
) -> pd.DataFrame:
    """Add ``residual``, ``scale`` and ``z`` columns to a copy of ``predictions``."""
    out = predictions.copy()
    out["residual"] = out["y"] - out[model_col]
    out["scale"] = scale(out[model_col].to_numpy(dtype=float))
    out["z"] = out["residual"] / out["scale"]
    return out


def severity(event_z: float) -> str:
    a = abs(event_z)
    return "high" if a >= 15 else "medium" if a >= 8 else "low"


def _group_seeds(flagged: pd.DataFrame, cfg: AnomalyConfig) -> pd.DataFrame:
    """Label runs of same-sign seed hours in one zone (allowing ``max_gap_hours`` unflagged)."""
    flagged = flagged.sort_values(["zone_index", "hour_ts"]).reset_index(drop=True)
    gap = flagged["hour_ts"].diff() > pd.Timedelta(hours=cfg.max_gap_hours + 1)
    new = (
        (flagged["zone_index"] != flagged["zone_index"].shift())
        | (flagged["sign"] != flagged["sign"].shift())
        | gap
    )
    flagged["event_id"] = new.cumsum() - 1
    return flagged


EVENT_COLUMNS = [
    "event_id", "zone_index", "location_id", "direction", "start", "end", "hours_flagged",
    "hours_span", "event_z", "peak_z", "actual", "forecast", "excess", "ratio", "severity",
]  # fmt: skip


def detect_events(
    scored: pd.DataFrame,
    cfg: AnomalyConfig,
    series: Series,
    null: NullModel,
    model_col: str = "lightgbm",
) -> pd.DataFrame:
    """Merge seed hours into events; keep those with enough null-standardised pooled evidence."""
    flagged = scored[scored["z"].abs() >= cfg.z_seed].copy()
    if flagged.empty:
        return pd.DataFrame(columns=EVENT_COLUMNS)
    flagged["sign"] = np.sign(flagged["z"]).astype(int)
    flagged["abs_hour"] = flagged["day_index"] * HOURS + flagged["hour"]
    flagged = _group_seeds(flagged, cfg)
    g = flagged.groupby("event_id")
    events = pd.DataFrame(
        {
            "zone_index": g["zone_index"].first(),
            "location_id": g["location_id"].first(),
            "direction": np.where(g["sign"].first() > 0, "surge", "drop"),
            "first_hour": g["abs_hour"].min(),
            "last_hour": g["abs_hour"].max(),
            "start": g["hour_ts"].min(),
            "end": g["hour_ts"].max() + pd.Timedelta(hours=1),
            "hours_flagged": g.size(),
            "peak_z": g["z"].agg(lambda s: s.iloc[int(np.argmax(np.abs(s.to_numpy())))]),
        }
    ).reset_index()
    span_n = (events["last_hour"] - events["first_hour"] + 1).to_numpy(dtype=int)
    sums = [
        series.span(int(z), int(a), int(b) + 1)
        for z, a, b in zip(
            events["zone_index"], events["first_hour"], events["last_hour"], strict=True
        )
    ]
    events["excess"] = [r for r, _ in sums]
    var = np.array([v for _, v in sums])
    spread = np.array([null(int(n)) for n in span_n])
    events["hours_span"] = span_n
    events["event_z"] = events["excess"] / (np.sqrt(var) * spread)
    # actual/forecast over the whole span, not just the seed hours
    fc = [
        float(series._c_fc[int(z), int(b) + 1] - series._c_fc[int(z), int(a)])
        for z, a, b in zip(
            events["zone_index"], events["first_hour"], events["last_hour"], strict=True
        )
    ]
    events["forecast"] = fc
    events["actual"] = events["forecast"] + events["excess"]
    events["ratio"] = events["actual"] / events["forecast"].where(events["forecast"] > 0)
    events["severity"] = events["event_z"].map(severity)
    keep = (events["event_z"].abs() >= cfg.event_threshold) & (
        events["excess"].abs() >= cfg.min_excess
    )
    events = events[keep]
    order = events["excess"].abs().sort_values(ascending=False).index
    return events.loc[order].reset_index(drop=True)[EVENT_COLUMNS]


def hourly_counts(scored: pd.DataFrame, cfg: AnomalyConfig) -> pd.DataFrame:
    """Per hour: zones scored, and zones deviating up / down by at least ``context_z``."""
    flags = scored.assign(up=scored["z"] >= cfg.context_z, down=scored["z"] <= -cfg.context_z)
    out = flags.groupby("hour_ts")[["up", "down"]].sum()
    out["zones"] = flags.groupby("hour_ts").size()
    return out


def share_in_other_zones(
    counts: pd.DataFrame, own: pd.DataFrame, hours: pd.DatetimeIndex, col: str
) -> float:
    """Mean over ``hours`` of the share of *other* zones deviating in direction ``col``.

    The event's own zone is excluded: with few zones a single zone would otherwise look like a
    large share, and the label would depend on how many zones exist.
    """
    c = counts.reindex(hours)
    mine = own.reindex(hours)[col].fillna(False).astype(float)
    others = (c[col] - mine) / (c["zones"] - 1).where(c["zones"] > 1)
    return float(others.mean())


def annotate(
    events: pd.DataFrame,
    scored: pd.DataFrame,
    t: DemandTensor,
    cfg: AnomalyConfig,
) -> pd.DataFrame:
    """Add zone names, calendar/weather context, co-movement and a non-causal explanation."""
    if events.empty:
        return events.assign(
            zone=[],
            borough=[],
            citywide_share=[],
            overlapping_events=[],
            scope=[],
            context=[],
            explanation=[],
        )
    counts = hourly_counts(scored, cfg)
    n_zones = int(scored["zone_index"].nunique())
    flags = scored.assign(up=scored["z"] >= cfg.context_z, down=scored["z"] <= -cfg.context_z)
    by_zone: dict[int, pd.DataFrame] = {}
    for z_key, g in flags.groupby("zone_index"):
        by_zone[int(cast(Any, z_key))] = g.set_index("hour_ts")[["up", "down"]]
    rows: list[dict[str, Any]] = []
    for rec in events.to_dict("records"):
        e = SimpleNamespace(
            **{str(k): v for k, v in rec.items()}
        )  # attribute access on untyped pandas values
        hours = pd.date_range(e.start, e.end, freq="h", inclusive="left")
        col = "up" if e.direction == "surge" else "down"
        s = share_in_other_zones(counts, by_zone[int(e.zone_index)], hours, col)
        others = s * (n_zones - 1)  # average number of other zones deviating in those hours
        scope = (
            "city-wide"
            if s >= cfg.widespread_share
            else "localised"
            if s <= cfg.isolated_share or others <= 1.0
            else "partly shared"
        )
        day = pd.Timestamp(e.start).normalize()
        d_idx = int((day - t.days[0]).days)
        same = events[(events["direction"] == e.direction) & (events["zone_index"] != e.zone_index)]
        overlapping = int(((same["start"] < e.end) & (same["end"] > e.start)).sum())
        context = _context(t, d_idx, s, scope, overlapping)
        zone = str(t.zones["zone"].iloc[int(e.zone_index)])
        borough = str(t.zones["borough"].iloc[int(e.zone_index)])
        rows.append(
            {
                "zone": zone,
                "borough": borough,
                "citywide_share": s,
                "overlapping_events": overlapping,
                "scope": scope,
                "context": context,
                "explanation": _explain(e, zone, borough, context),
            }
        )
    return pd.concat([events.reset_index(drop=True), pd.DataFrame(rows)], axis=1)


def _long_weekend(t: DemandTensor, d_idx: int) -> bool:
    """Saturday/Sunday next to a Monday or Friday federal holiday (a 'long weekend')."""
    dow = int(t.calendar["day_of_week"].iloc[d_idx])
    if dow not in (5, 6):
        return False
    nearby = [d_idx + 2, d_idx - 1] if dow == 5 else [d_idx + 1, d_idx - 2]
    return any(0 <= i < t.n_days and bool(t.calendar["is_holiday"].iloc[i]) for i in nearby)


def _context(
    t: DemandTensor, d_idx: int, share: float, scope: str, overlapping: int = 0
) -> list[str]:
    out: list[str] = []
    if 0 <= d_idx < t.n_days:
        cal = t.calendar.iloc[d_idx]
        if bool(cal["is_holiday"]):
            out.append("a US federal holiday")
        if bool(cal["is_day_after_holiday"]):
            out.append("the day after a US federal holiday")
        if bool(cal["is_day_before_holiday"]):
            out.append("the day before a US federal holiday")
        if _long_weekend(t, d_idx):
            out.append("a weekend adjoining a US federal holiday")
        w = t.weather.iloc[d_idx]
        prcp = pd.to_numeric(pd.Series([w["prcp_mm"]]), errors="coerce").iloc[0]
        tmax = pd.to_numeric(pd.Series([w["tmax_c"]]), errors="coerce").iloc[0]
        if pd.notna(prcp) and prcp >= 1.0:
            out.append(f"rain ({prcp:.1f} mm recorded that day)")
        if str(w.get("is_snow")) == "True":
            out.append("snowfall")
        if pd.notna(tmax) and tmax <= 0:
            out.append(f"freezing temperatures (daily high {tmax:.1f} C)")
    if scope == "city-wide":
        out.append(f"similar hourly deviations in {share:.0%} of zones in the same hours")
    if overlapping:
        noun = "zone" if overlapping == 1 else "zones"
        out.append(f"events in {overlapping} other {noun} in overlapping hours, same direction")
    elif scope == "localised":
        out.append("no similar event in any other zone in overlapping hours")
    return out


def _explain(e: Any, zone: str, borough: str, context: list[str]) -> str:
    start, end = pd.Timestamp(e.start), pd.Timestamp(e.end)
    when = (
        f"between {start:%H:%M} and {end:%H:%M} on {start:%a %d %b %Y}"
        if start.normalize() == (end - pd.Timedelta(seconds=1)).normalize()
        else f"between {start:%a %d %b %H:%M} and {end:%a %d %b %H:%M} {end:%Y}"
    )
    ratio = f"{e.ratio:.1f}x" if pd.notna(e.ratio) else "n/a"
    what = (
        f"{zone} ({borough}) had {e.actual:.0f} pickups {when}, {ratio} the forecast of "
        f"{e.forecast:.0f} ({e.direction}; standardised score {e.event_z:+.1f} over "
        f"{e.hours_span} h, largest single hour {e.peak_z:+.1f})."
    )
    ctx = (
        "This coincided with: " + "; ".join(context) + "."
        if context
        else "No holiday or notable weather is recorded for that day."
    )
    return f"{what} {ctx} This describes co-occurrence in the data, not a cause."


def run_detection(
    predictions: pd.DataFrame, t: DemandTensor, cfg: AnomalyConfig | None = None
) -> tuple[pd.DataFrame, pd.DataFrame, ScaleModel, NullModel]:
    """Fit scale and null, score, group and annotate. Returns ``(events, scored, scale, null)``."""
    cfg = cfg or AnomalyConfig()
    resid = (predictions["y"] - predictions["lightgbm"]).to_numpy(dtype=float)
    scale = fit_scale(predictions["lightgbm"].to_numpy(dtype=float), resid, cfg)
    scored = score(predictions, scale)
    series = Series(scored)
    null = fit_null(series, cfg)
    events = annotate(detect_events(scored, cfg, series, null), scored, t, cfg)
    return events, scored, scale, null
