import type { components } from "./schema";

export type Schemas = components["schemas"];

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly requestId: string | null;
  readonly details: { field: string; message: string }[];

  constructor(
    status: number,
    code: string,
    message: string,
    requestId: string | null,
    details: { field: string; message: string }[] = [],
  ) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.requestId = requestId;
    this.details = details;
  }
}

interface ErrorBody {
  code?: string;
  message?: string;
  request_id?: string;
  details?: { field?: string; message?: string }[] | null;
}

type Query = Record<string, string | number | boolean | null | undefined>;

const qs = (q?: Query): string => {
  if (!q) return "";
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(q)) {
    if (v !== undefined && v !== null && v !== "") p.set(k, String(v));
  }
  const s = p.toString();
  return s ? `?${s}` : "";
};

/** Every error from the API has one shape; anything else is reported as a network failure. */
export async function request<T>(
  path: string,
  init?: RequestInit & { query?: Query },
): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${path}${qs(init?.query)}`, {
      ...init,
      headers: { Accept: "application/json", ...(init?.headers ?? {}) },
    });
  } catch (cause) {
    if (cause instanceof DOMException && cause.name === "AbortError") throw cause;
    throw new ApiError(0, "network", "Could not reach the API. Is the server running?", null);
  }
  if (!res.ok) {
    let body: { error?: ErrorBody } | null = null;
    try {
      body = (await res.json()) as { error?: ErrorBody };
    } catch {
      body = null;
    }
    const e = body?.error;
    throw new ApiError(
      res.status,
      e?.code ?? "http_error",
      e?.message ?? `The API returned HTTP ${res.status}.`,
      e?.request_id ?? res.headers.get("X-Request-ID"),
      (e?.details ?? []).map((d) => ({ field: d.field ?? "", message: d.message ?? "" })),
    );
  }
  return (await res.json()) as T;
}

const get = <T>(path: string, query?: Query, signal?: AbortSignal) =>
  request<T>(path, { query, signal });

const post = <T>(path: string, body: unknown, signal?: AbortSignal) =>
  request<T>(path, {
    method: "POST",
    body: JSON.stringify(body),
    headers: { "Content-Type": "application/json" },
    signal,
  });

// Generated documents (evaluation, anomaly summary, backtest) are passed through as-is; these
// interfaces name only the fields the UI reads. Missing fields render as "n/a", never as a guess.
export interface ModelMetrics {
  n: number;
  mae: number | null;
  rmse: number | null;
  wape: number | null;
  bias: number | null;
}
export interface IntervalStats {
  n: number;
  coverage: number | null;
  mean_width: number | null;
}
export interface ForecastPerformance {
  data_label: string;
  mode: string;
  data_days: [string, string];
  test_rows: number;
  test_days: number;
  zones: number;
  overall: Record<string, ModelMetrics>;
  best_baseline: string;
  folds: { fold: number; test_days: [string, string] }[];
  interval: {
    nominal: number;
    overall: IntervalStats;
    by_volume: Record<string, IntervalStats>;
  };
  bootstrap: {
    improvement: Record<
      string,
      { wape_point_difference: number; difference_ci95: [number, number] }
    >;
  };
  oracle_weather_experiment?: {
    label: string;
    wape_without_weather: number;
    wape_with_oracle_weather: number;
  };
}
export interface BacktestPlanner {
  served_share: number;
  vehicles_moved_per_window: number;
}
export interface OptimizationBacktest {
  label: string;
  data_label: string;
  windows_scored: number;
  days: number;
  planners: Record<string, BacktestPlanner>;
  lightgbm_vs_none: { point: number; ci95: [number, number] };
  lightgbm_vs_seasonal_mean_planning: { point: number; ci95: [number, number] };
  assumptions: Record<string, string | number | string[]>;
  design: string;
}
export interface AnomalySummary {
  data_label: string;
  accuracy_status: string;
  scored_days: [string, string];
  events_total: number;
  events_per_1000_zone_days: number;
  by_severity: Record<string, number>;
  by_direction: Record<string, number>;
  busiest_days?: { date: string; events: number; share_of_all: number }[];
}

export const api = {
  meta: (s?: AbortSignal) => get<Schemas["Meta"]>("/api/v1/meta", undefined, s),
  quality: (s?: AbortSignal) => get<Schemas["QualityStage"][]>("/api/v1/quality", undefined, s),
  zones: (s?: AbortSignal) => get<Schemas["Zone"][]>("/api/v1/zones", undefined, s),
  demandSeries: (
    q: { start: string; end: string; zone_id?: number; grain: "hour" | "day"; metric: string },
    s?: AbortSignal,
  ) => get<Schemas["SeriesResponse"]>("/api/v1/demand/series", q, s),
  topZones: (
    q: { start: string; end: string; metric?: string; limit?: number },
    s?: AbortSignal,
  ) => get<Schemas["TopZone"][]>("/api/v1/demand/top-zones", q, s),
  hourlyProfile: (q: { start: string; end: string; zone_id?: number }, s?: AbortSignal) =>
    get<Schemas["HourProfilePoint"][]>("/api/v1/demand/profile/hourly", q, s),
  compare: (
    q: { a_start: string; a_end: string; b_start: string; b_end: string; zone_id?: number },
    s?: AbortSignal,
  ) => get<Schemas["Comparison"]>("/api/v1/demand/compare", q, s),
  serviceMix: (
    q: { start: string; end: string; zone_id?: number; grain: "month" | "total" },
    s?: AbortSignal,
  ) => get<Schemas["ServiceMixPoint"][]>("/api/v1/demand/services", q, s),
  weather: (
    q: { start: string; end: string; condition: "rain" | "snow" | "freezing"; zone_id?: number },
    s?: AbortSignal,
  ) => get<Schemas["WeatherComparison"]>("/api/v1/demand/weather-comparison", q, s),
  forecastPerformance: (s?: AbortSignal) =>
    get<ForecastPerformance>("/api/v1/forecast/performance", undefined, s),
  forecastBacktest: (q: { zone_id: number; date: string }, s?: AbortSignal) =>
    get<Schemas["BacktestForecast"]>("/api/v1/forecast/backtest", q, s),
  forecastNextDay: (q: { zone_id?: number }, s?: AbortSignal) =>
    get<Schemas["NextDayForecast"]>("/api/v1/forecast/next-day", q, s),
  anomalies: (
    q: {
      severity?: string;
      direction?: string;
      zone_id?: number;
      limit?: number;
      offset?: number;
    },
    s?: AbortSignal,
  ) => get<Schemas["AnomalyPage"]>("/api/v1/anomalies", q, s),
  anomalySummary: (s?: AbortSignal) =>
    get<AnomalySummary>("/api/v1/anomalies/summary", undefined, s),
  optimizationBacktest: (s?: AbortSignal) =>
    get<OptimizationBacktest>("/api/v1/optimization/backtest", undefined, s),
  scenario: (body: Schemas["ScenarioRequest"], s?: AbortSignal) =>
    post<Schemas["ScenarioResponse"]>("/api/v1/optimization/scenario", body, s),
  analystStatus: (s?: AbortSignal) =>
    get<Schemas["AnalystStatus"]>("/api/v1/analyst/status", undefined, s),
  analystAsk: (question: string, s?: AbortSignal) =>
    post<Schemas["AnalystResponse"]>("/api/v1/analyst/ask", { question }, s),
};
