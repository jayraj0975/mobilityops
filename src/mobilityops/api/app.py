"""The HTTP API: a thin, validated, read-only layer over analytics, forecasts and scenarios.

Design rules (see docs/SECURITY.md):

* Every input is a typed, bounded parameter; nothing is interpolated into SQL here.
* Every endpoint is read-only. The single compute endpoint (repositioning scenarios) is capped in
  duration, size and concurrency.
* Errors share one shape and never leak stack traces. Every response carries a request id.
* Responses say what data they come from (``X-Data-Label``): synthetic sample data can never be
  mistaken for real data.
* If ``MOBILITYOPS_API_KEY`` is set, all ``/api/v1`` routes require it.
"""

from __future__ import annotations

import re
import secrets
import time
import uuid
from collections.abc import Awaitable, Callable
from datetime import date, timedelta
from pathlib import Path as FsPath
from typing import Annotated, Any, Literal

import numpy as np
import pandas as pd
from fastapi import (
    APIRouter,
    Depends,
    FastAPI,
    Header,
    HTTPException,
    Path,
    Query,
    Request,
    Response,
)
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from mobilityops import __version__
from mobilityops.analyst.agent import Analyst, tool_catalog
from mobilityops.analyst.llm import AnthropicPlanner
from mobilityops.analyst.planner import Planner, RulePlanner
from mobilityops.analytics.queries import AnalyticsError, InvalidQuery, NoData
from mobilityops.api import schemas as s
from mobilityops.api.limits import BodyLimitMiddleware, RateLimiter, client_ip
from mobilityops.api.metrics import Metrics
from mobilityops.api.services import NotReady, Services
from mobilityops.config import Settings
from mobilityops.log import get_logger
from mobilityops.optimization.model import RebalanceParams
from mobilityops.optimization.run import scenario_report
from mobilityops.optimization.scenario import Window
from mobilityops.pipeline import quality_dir

log = get_logger("api")

MAX_BODY_BYTES = 16 * 1024
# The single-page app: same-origin scripts and API calls only (charts set inline styles).
CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; "
    "form-action 'self'"
)
WEB_DIST_ENV = "MOBILITYOPS_WEB_DIST"
SOLVER_TIME_LIMIT_S = 10.0
_REQUEST_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

ZoneId = Annotated[int, Query(ge=1, le=400, description="TLC location id")]
OptZoneId = Annotated[int | None, Query(ge=1, le=400, description="TLC location id")]
Limit = Annotated[int, Query(ge=1, le=100)]


class Busy(RuntimeError):
    """All solver slots are in use."""


def _clean(value: Any) -> Any:
    """NaN -> None, numpy scalars -> Python scalars, arrays -> lists (for JSON models)."""
    if isinstance(value, np.ndarray):
        return [_clean(v) for v in value.tolist()]
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float) and np.isnan(value):
        return None
    if value is pd.NaT:
        return None
    return value


def _records(df: pd.DataFrame) -> list[dict[str, Any]]:
    return [{str(k): _clean(v) for k, v in row.items()} for row in df.to_dict("records")]


def _error(code: str, message: str, status: int, request: Request, **extra: Any) -> JSONResponse:
    rid = getattr(request.state, "request_id", "unknown")
    body = {"error": {"code": code, "message": message, "request_id": rid, **extra}}
    return JSONResponse(body, status_code=status)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    services = Services(settings)
    metrics = Metrics()
    limiter = RateLimiter()
    planner: Planner = (
        AnthropicPlanner(settings.anthropic_api_key, settings.llm_model)  # type: ignore[arg-type]
        if settings.llm_configured
        else RulePlanner()
    )
    analyst = Analyst(services, planner)
    app = FastAPI(
        title="MobilityOps API",
        version=__version__,
        description=(
            "Read-only analytics, forecasts, anomaly events and simulated repositioning scenarios "
            "over NYC yellow-taxi demand. Sample mode serves TEST / SYNTHETIC DATA; the "
            "`X-Data-Label` response header always says which is being served. Optimization "
            "outputs are SIMULATED SCENARIOS under explicit assumptions."
        ),
    )
    app.state.services = services
    app.state.metrics = metrics
    app.state.analyst = analyst

    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["X-API-Key", "Content-Type", "X-Request-ID"],
        allow_credentials=False,
        expose_headers=["X-Request-ID", "X-Data-Label", "X-Data-Mode"],
    )

    # ------------------------------------------------------------------------ middleware
    @app.middleware("http")
    async def observe(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        incoming = request.headers.get("x-request-id", "")
        who = client_ip(
            request.client.host if request.client else None,
            request.headers.get("x-forwarded-for"),
            settings.trust_proxy,
        )
        rid = incoming if _REQUEST_ID.match(incoming) else uuid.uuid4().hex
        request.state.request_id = rid
        started = time.perf_counter()
        length = request.headers.get("content-length")
        limited: tuple[bool, float] = (True, 0.0)
        if request.url.path.startswith("/api/v1/") and request.method != "OPTIONS":
            heavy = request.url.path.startswith(
                ("/api/v1/analyst/ask", "/api/v1/optimization/scenario")
            )
            limited = limiter.check(
                who,
                "heavy" if heavy else "api",
                settings.rate_limit_heavy if heavy else settings.rate_limit,
            )
        if not limited[0]:
            metrics.event("rate_limited")
            response: Response = _error(
                "rate_limited",
                "too many requests; slow down and retry shortly",
                429,
                request,
            )
            response.headers["Retry-After"] = str(int(limited[1]) + 1)
        elif length and length.isdigit() and int(length) > MAX_BODY_BYTES:
            response = _error(
                "payload_too_large", f"request body exceeds {MAX_BODY_BYTES} bytes", 413, request
            )
        else:
            try:
                response = await call_next(request)
            except Exception:
                log.exception("unhandled error", extra={"ctx": {"request_id": rid}})
                response = _error("internal_error", "internal server error", 500, request)
        response.headers["X-Request-ID"] = rid
        response.headers["X-Data-Mode"] = settings.mode
        response.headers["X-Data-Label"] = services.data_label
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        if settings.trust_proxy and request.headers.get("x-forwarded-proto") == "https":
            response.headers["Strict-Transport-Security"] = "max-age=31536000"
        response.headers.setdefault("Cache-Control", "no-store")
        path = request.url.path
        if not path.startswith(("/api", "/docs", "/redoc", "/openapi", "/health", "/ready")):
            response.headers["Content-Security-Policy"] = CSP
        route = request.scope.get("route")
        elapsed_ms = (time.perf_counter() - started) * 1000
        template = getattr(route, "path", "(unmatched)")
        metrics.request(request.method, template, response.status_code, elapsed_ms)
        log.info(
            "request",
            extra={
                "ctx": {
                    "request_id": rid,
                    "method": request.method,
                    "path": getattr(route, "path", request.url.path),
                    "status": response.status_code,
                    "ms": round(elapsed_ms, 1),
                    # only while rate limiting is on: the address is what the limit counts by
                    **({"client": who} if settings.rate_limit > 0 else {}),
                }
            },
        )
        return response

    # ------------------------------------------------------------------------- errors
    @app.exception_handler(NoData)
    async def _no_data(request: Request, exc: NoData) -> JSONResponse:
        return _error("no_data", str(exc), 404, request)

    @app.exception_handler(InvalidQuery)
    async def _invalid(request: Request, exc: InvalidQuery) -> JSONResponse:
        return _error("invalid_query", str(exc), 422, request)

    @app.exception_handler(AnalyticsError)
    async def _analytics(request: Request, exc: AnalyticsError) -> JSONResponse:
        return _error("analytics_error", str(exc), 400, request)

    @app.exception_handler(NotReady)
    async def _not_ready(request: Request, exc: NotReady) -> JSONResponse:
        return _error("not_ready", str(exc), 503, request)

    @app.exception_handler(Busy)
    async def _busy(request: Request, exc: Busy) -> JSONResponse:
        metrics.event("scenario_solver_busy")
        return _error("busy", str(exc), 429, request)

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        details = [
            {"field": ".".join(str(p) for p in e["loc"]), "message": str(e["msg"])}
            for e in exc.errors()[:10]
        ]
        return _error("validation_error", "invalid request", 422, request, details=details)

    @app.exception_handler(HTTPException)
    async def _http(request: Request, exc: HTTPException) -> JSONResponse:
        return _error("http_error", str(exc.detail), exc.status_code, request)

    # -------------------------------------------------------------------------- auth
    def require_key(x_api_key: Annotated[str | None, Header()] = None) -> None:
        if settings.api_key is None:
            return
        if x_api_key is None or not secrets.compare_digest(x_api_key, settings.api_key):
            raise HTTPException(status_code=401, detail="missing or invalid X-API-Key")

    ops = APIRouter(tags=["operations"])
    api = APIRouter(prefix="/api/v1", dependencies=[Depends(require_key)])

    # ---------------------------------------------------------------------- operations
    @ops.get("/health", response_model=s.Health, summary="Liveness")
    def health() -> s.Health:
        return s.Health()

    @ops.get("/ready", response_model=s.Ready, summary="Readiness: which parts are available")
    def ready(response: Response) -> s.Ready:
        comps = services.available()
        if not comps["database"]:
            response.status_code = 503
            return s.Ready(
                status="degraded", components=comps, hint="run `ingest` and `build` first"
            )
        return s.Ready(status="ready" if all(comps.values()) else "degraded", components=comps)

    @api.get("/meta", response_model=s.Meta, tags=["operations"])
    def meta() -> s.Meta:
        r = services.analytics().data_range()
        return s.Meta(
            api_version=__version__,
            mode=settings.mode,
            data_label=services.data_label,
            synthetic=r.synthetic,
            data_start=r.start,
            data_end=r.end,
            n_zones=r.n_zones,
            rows_valid=r.rows_valid,
            run_id=r.run_id,
            built_at_utc=r.built_at_utc,
            llm_configured=settings.llm_configured,
            artifacts=services.available(),
        )

    @api.get("/ops/metrics", response_model=s.ArtifactDocument, tags=["operations"])
    def ops_metrics() -> dict[str, Any]:
        """Request counts and latency percentiles per route template, plus analyst counters."""
        return metrics.snapshot()

    @api.get("/quality", response_model=list[s.QualityStage], tags=["operations"])
    def quality() -> list[s.QualityStage]:
        import json

        out: list[s.QualityStage] = []
        for stage in ("bronze", "silver", "gold"):
            path: FsPath = quality_dir(settings) / f"{stage}.json"
            if path.exists():
                out.append(s.QualityStage(**json.loads(path.read_text())))
        if not out:
            raise NotReady("no quality reports; run `ingest` and `build` first")
        return out

    # --------------------------------------------------------------------------- zones
    @api.get("/zones", response_model=list[s.Zone], tags=["zones"])
    def zones(
        borough: Annotated[str | None, Query(max_length=40)] = None,
        q: Annotated[str | None, Query(max_length=50, description="name contains")] = None,
    ) -> list[s.Zone]:
        df = services.analytics().zones()
        if borough:
            df = df[df["borough"].str.lower() == borough.lower()]
        if q:
            df = df[df["zone"].str.contains(q, case=False, regex=False)]
        return [s.Zone(**r) for r in _records(df)]

    @api.get("/zones/{zone_id}", response_model=s.Zone, tags=["zones"])
    def zone(zone_id: Annotated[int, Path(ge=1, le=400)]) -> s.Zone:
        df = services.analytics().zones()
        row = df[df["location_id"] == zone_id]
        if row.empty:
            raise NoData(f"unknown zone id {zone_id}")
        return s.Zone(**_records(row)[0])

    # -------------------------------------------------------------------------- demand
    @api.get("/demand/series", response_model=s.SeriesResponse, tags=["demand"])
    def demand_series(
        start: date,
        end: date,
        zone_id: OptZoneId = None,
        grain: s.Grain = "day",
        metric: s.Metric = "pickups",
    ) -> s.SeriesResponse:
        a = services.analytics()
        df = a.demand_series(start, end, zone_id=zone_id, grain=grain, metric=metric)
        return s.SeriesResponse(
            zone_id=zone_id,
            zone_name=a.zone_name(zone_id) if zone_id else None,
            grain=grain,
            metric=metric,
            start=start,
            end=end,
            points=[s.SeriesPoint(**r) for r in _records(df)],
        )

    @api.get("/demand/top-zones", response_model=list[s.TopZone], tags=["demand"])
    def top_zones(
        start: date,
        end: date,
        metric: s.Metric = "pickups",
        limit: Limit = 10,
        ascending: bool = False,
    ) -> list[s.TopZone]:
        df = services.analytics().top_zones(
            start, end, metric=metric, limit=limit, ascending=ascending
        )
        return [s.TopZone(**r) for r in _records(df)]

    @api.get("/demand/profile/hourly", response_model=list[s.HourProfilePoint], tags=["demand"])
    def hourly_profile(
        start: date, end: date, zone_id: OptZoneId = None
    ) -> list[s.HourProfilePoint]:
        df = services.analytics().hourly_profile(start, end, zone_id=zone_id)
        return [s.HourProfilePoint(**r) for r in _records(df)]

    @api.get("/demand/profile/weekday", response_model=list[s.WeekdayPoint], tags=["demand"])
    def weekday_profile(start: date, end: date, zone_id: OptZoneId = None) -> list[s.WeekdayPoint]:
        df = services.analytics().weekday_profile(start, end, zone_id=zone_id)
        return [s.WeekdayPoint(**r) for r in _records(df)]

    @api.get("/demand/compare", response_model=s.Comparison, tags=["demand"])
    def compare(
        a_start: date,
        a_end: date,
        b_start: date,
        b_end: date,
        zone_id: OptZoneId = None,
        metric: s.Metric = "pickups",
    ) -> s.Comparison:
        d = services.analytics().compare_periods(
            a_start, a_end, b_start, b_end, zone_id=zone_id, metric=metric
        )
        return s.Comparison(**{k: _clean(v) for k, v in d.items()})

    @api.get("/demand/growth", response_model=s.Comparison, tags=["demand"])
    def growth(
        end: date,
        window_days: Annotated[int, Query(ge=1, le=90)] = 7,
        zone_id: OptZoneId = None,
    ) -> s.Comparison:
        d = services.analytics().growth(end, window_days=window_days, zone_id=zone_id)
        return s.Comparison(**{k: _clean(v) for k, v in d.items()})

    @api.get("/demand/volatility", response_model=s.Volatility, tags=["demand"])
    def volatility(start: date, end: date, zone_id: ZoneId) -> s.Volatility:
        d = services.analytics().volatility(start, end, zone_id)
        return s.Volatility(**{k: _clean(v) for k, v in d.items()})

    @api.get("/demand/concentration", response_model=s.Concentration, tags=["demand"])
    def concentration(
        start: date, end: date, top_n: Annotated[int, Query(ge=1, le=100)] = 10
    ) -> s.Concentration:
        d = services.analytics().concentration(start, end, top_n=top_n)
        return s.Concentration(**{k: _clean(v) for k, v in d.items()})

    @api.get("/demand/weather-comparison", response_model=s.WeatherComparison, tags=["demand"])
    def weather_comparison(
        start: date,
        end: date,
        condition: Literal["rain", "snow", "freezing"] = "rain",
        zone_id: OptZoneId = None,
    ) -> s.WeatherComparison:
        d = services.analytics().weather_comparison(
            start,
            end,
            condition=condition,
            zone_id=zone_id,
        )
        return s.WeatherComparison(**{k: _clean(v) for k, v in d.items()})

    # ------------------------------------------------------------------------ forecast
    @api.get("/forecast/performance", response_model=s.ArtifactDocument, tags=["forecast"])
    def forecast_performance() -> dict[str, Any]:
        """The latest walk-forward evaluation (metrics, baselines, error analysis, intervals)."""
        return services.evaluation()

    @api.get("/forecast/model", response_model=s.ArtifactDocument, tags=["forecast"])
    def forecast_model() -> dict[str, Any]:
        """The registered model's metadata (training windows, features, parameters)."""
        return services.model_meta()

    @api.get("/forecast/backtest", response_model=s.BacktestForecast, tags=["forecast"])
    def forecast_backtest(zone_id: ZoneId, day: Annotated[date, Query(alias="date")]) -> Any:
        """Out-of-sample forecast vs actual for one zone and day, from the evaluation folds."""
        t = services.tensor()
        preds = services.predictions()
        ts = pd.Timestamp(day)
        if ts not in t.days:
            raise NoData(f"{day} is outside the data range")
        di = int((ts - t.days[0]).days)
        ids = t.zones["location_id"].to_numpy()
        if zone_id not in set(ids.tolist()):
            raise NoData(f"unknown zone id {zone_id}")
        zi = int(np.nonzero(ids == zone_id)[0][0])
        sel = preds[(preds["zone_index"] == zi) & (preds["day_index"] == di)].sort_values("hour")
        if sel.empty:
            lo, hi = int(preds["day_index"].min()), int(preds["day_index"].max())
            raise NoData(
                f"no out-of-sample forecast for {day}; evaluation days are "
                f"{t.days[lo].date()} to {t.days[hi].date()}"
            )
        return s.BacktestForecast(
            data_label=services.data_label,
            zone_id=zone_id,
            zone_name=str(t.zones["zone"].iloc[zi]),
            date=day,
            note="Forecast made from 00:00 of the day using only earlier days; the model never "
            "saw this day (walk-forward fold).",
            points=[
                s.ForecastPoint(
                    hour_ts=r["hour_ts"],
                    forecast=float(r["lightgbm"]),
                    lo=float(r["lo"]),
                    hi=float(r["hi"]),
                    actual=float(r["y"]),
                )
                for r in _records(sel)
            ],
        )

    @api.get("/forecast/next-day", response_model=s.NextDayForecast, tags=["forecast"])
    def forecast_next_day(zone_id: OptZoneId = None) -> Any:
        """Forecast for the day after the last observed day, per zone or city-wide total."""
        frame, model_id = services.next_day()
        t = services.tensor()
        model = services.model()
        target = (t.days[-1] + timedelta(days=1)).date()
        empirical: float | None = None
        try:
            empirical = float(services.evaluation()["interval"]["overall"]["coverage"])
        except (NotReady, KeyError):
            empirical = None
        zone_name: str | None = None
        if zone_id is not None:
            sel = frame[frame["location_id"] == zone_id]
            if sel.empty:
                raise NoData(f"unknown zone id {zone_id}")
            zone_name = str(t.zones.set_index("location_id")["zone"].get(zone_id, "?"))
            pts = [
                s.ForecastPoint(
                    hour_ts=r["hour_ts"],
                    forecast=float(r["pred"]),
                    lo=float(r["lo"]),
                    hi=float(r["hi"]),
                )
                for r in _records(sel.sort_values("hour_ts"))
            ]
            note = "Point forecast with an empirical 80% interval per zone-hour."
        else:
            agg = (
                frame.groupby("hour_ts", as_index=False)
                .agg(pred=("pred", "sum"))
                .sort_values("hour_ts")
            )
            pts = [
                s.ForecastPoint(hour_ts=r["hour_ts"], forecast=float(r["pred"]))
                for r in _records(agg)
            ]
            note = (
                "City-wide total of the zone point forecasts. No interval is given: zone "
                "intervals cannot be added into a valid total interval."
            )
        return s.NextDayForecast(
            data_label=services.data_label,
            model_id=model_id,
            target_date=target,
            zone_id=zone_id,
            zone_name=zone_name,
            nominal_coverage=model.coverage,
            empirical_coverage_in_evaluation=empirical,
            note=note,
            points=pts,
        )

    # ---------------------------------------------------------------------- anomalies
    @api.get("/anomalies", response_model=s.AnomalyPage, tags=["anomalies"])
    def anomalies(
        severity: s.Severity | None = None,
        direction: s.Direction | None = None,
        zone_id: OptZoneId = None,
        start: date | None = None,
        end: date | None = None,
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
        offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
    ) -> s.AnomalyPage:
        """Detected events, largest first. Explanations describe coincidence, never cause."""
        df = services.events()
        if severity:
            df = df[df["severity"] == severity]
        if direction:
            df = df[df["direction"] == direction]
        if zone_id is not None:
            df = df[df["location_id"] == zone_id]
        if start:
            df = df[df["end"] > pd.Timestamp(start)]
        if end:
            df = df[df["start"] < pd.Timestamp(end)]
        page = df.iloc[offset : offset + limit]
        report = services.anomaly_report()
        return s.AnomalyPage(
            data_label=services.data_label,
            accuracy_status=str(report.get("accuracy_status", "")),
            total=len(df),
            limit=limit,
            offset=offset,
            items=[
                s.AnomalyItem(**{k: r[k] for k in s.AnomalyItem.model_fields})
                for r in _records(page)
            ],
        )

    @api.get("/anomalies/summary", response_model=s.ArtifactDocument, tags=["anomalies"])
    def anomalies_summary() -> dict[str, Any]:
        return services.anomaly_report()

    # -------------------------------------------------------------------- optimization
    @api.get("/optimization/backtest", response_model=s.ArtifactDocument, tags=["optimization"])
    def optimization_backtest() -> dict[str, Any]:
        """The latest repositioning backtest. SIMULATED under explicit assumptions."""
        return services.backtest_report()

    @api.post("/optimization/scenario", response_model=s.ScenarioResponse, tags=["optimization"])
    def optimization_scenario(req: s.ScenarioRequest) -> Any:
        """Run one repositioning what-if. SIMULATED SCENARIO under the stated assumptions.

        Bounded: at most a few solves run at once (others get 429) and each stops after
        ``SOLVER_TIME_LIMIT_S`` seconds.
        """
        if not services.solver_slots.acquire(blocking=False):
            raise Busy("all scenario solver slots are in use; retry shortly")
        try:
            params = RebalanceParams(
                trips_per_vehicle=req.trips_per_vehicle,
                max_km=req.max_km,
                cost_per_km=req.cost_per_km,
                max_move_share=req.max_move_share,
                min_service_share=req.min_service_share,
                time_limit_s=SOLVER_TIME_LIMIT_S,
            )
            try:
                rep = scenario_report(
                    settings,
                    req.date,
                    Window(req.start_hour, req.end_hour),
                    params,
                    coverage=req.coverage,
                    multipliers=req.demand_multipliers or None,
                    t=services.tensor(),
                    preds=services.predictions(),
                )
            except ValueError as exc:
                raise InvalidQuery(str(exc)) from exc
        finally:
            services.solver_slots.release()
        return s.ScenarioResponse(**{k: rep[k] for k in s.ScenarioResponse.model_fields})

    # ---------------------------------------------------------------------- analyst
    @api.get("/analyst/status", response_model=s.AnalystStatus, tags=["analyst"])
    def analyst_status() -> s.AnalystStatus:
        llm = settings.llm_configured
        return s.AnalystStatus(
            planner=planner.name,
            llm_configured=llm,
            llm_status=(
                "UNVERIFIED: configured but never validated against the live service"
                if llm
                else "not configured (no key): deterministic planner in use"
            ),
            tools=len(tool_catalog()),
            note="Answers are built only from read-only tool results and checked for grounding.",
        )

    @api.get("/analyst/tools", tags=["analyst"])
    def analyst_tools() -> list[dict[str, Any]]:
        return tool_catalog()

    @api.post("/analyst/ask", response_model=s.AnalystResponse, tags=["analyst"])
    def analyst_ask(req: s.AnalystRequest) -> Any:
        """Ask a question. Refusals, clarifications and partial answers are normal results."""
        ans = analyst.ask(req.question)
        metrics.analyst_outcome(
            ans.status,
            ans.grounding.get("removed", 0),
            any("instruction-override" in w for w in ans.warnings),
        )
        return s.AnalystResponse(
            question=ans.question,
            status=ans.status,
            mode=ans.mode,
            intent=ans.intent,
            data_label=ans.data_label,
            statements=[
                s.AnalystStatement(kind=x.kind, text=x.text, fact_ids=list(x.fact_ids))
                for x in ans.statements
            ],
            tools_used=[s.AnalystToolTrace(**t.__dict__) for t in ans.tools_used],
            warnings=ans.warnings,
            grounding=ans.grounding,
        )

    app.include_router(ops)
    app.include_router(api)
    _mount_web(app)
    app.add_middleware(BodyLimitMiddleware, max_bytes=MAX_BODY_BYTES)
    return app


def _mount_web(app: FastAPI) -> None:
    """Serve the built frontend at ``/`` when it exists (single-process local deployment)."""
    import os

    from fastapi.staticfiles import StaticFiles

    default = FsPath(__file__).resolve().parents[3] / "apps" / "web" / "dist"
    dist = FsPath(os.environ.get(WEB_DIST_ENV, str(default)))
    if (dist / "index.html").exists():
        app.mount("/", StaticFiles(directory=dist, html=True), name="web")
