import { vi } from "vitest";
import type {
  AnomalySummary,
  ForecastPerformance,
  OptimizationBacktest,
  Schemas,
} from "../api/client";

export const meta: Schemas["Meta"] = {
  api_version: "0.1.0",
  mode: "sample",
  data_label: "TEST / SYNTHETIC DATA",
  synthetic: true,
  data_start: "2024-01-01T00:00:00",
  data_end: "2024-02-26T00:00:00",
  n_zones: 2,
  rows_valid: 226245,
  run_id: "20240101T000000Z-abcd1234",
  built_at_utc: "2024-01-01T00:00:00+00:00",
  llm_configured: false,
  artifacts: { database: true },
  timezone: "America/New_York (timestamps are naive local time)",
};
export const realMeta: Schemas["Meta"] = {
  ...meta,
  mode: "real",
  data_label: "real data",
  synthetic: false,
  data_end: "2024-06-01T00:00:00",
};

export const zones: Schemas["Zone"][] = [
  { location_id: 3, zone: "Sample Zone 03", borough: "Sample", service_zone: null, centroid_lon: -74, centroid_lat: 40.7 },
  { location_id: 7, zone: "Sample Zone 07", borough: "Sample", service_zone: null, centroid_lon: -73.9, centroid_lat: 40.7 },
];

export const compare: Schemas["Comparison"] = {
  metric: "pickups",
  zone_id: null,
  period_a: { total: 70000, days: 7, per_day: 10000 },
  period_b: { total: 84000, days: 7, per_day: 12000 },
  per_day_change: 2000,
  per_day_change_pct: 0.2,
  equal_length: true,
};
export const top: Schemas["TopZone"][] = [
  { location_id: 3, zone: "Sample Zone 03", borough: "Sample", value: 5123, share: 0.31 },
  { location_id: 7, zone: "Sample Zone 07", borough: "Sample", value: 4001, share: 0.24 },
];
export const profile: Schemas["HourProfilePoint"][] = Array.from({ length: 24 }, (_, h) => ({
  hour_of_day: h,
  avg_pickups: 100 + h * 10,
  n_hours: 28,
}));
export const series: Schemas["SeriesResponse"] = {
  zone_id: null,
  zone_name: null,
  grain: "day",
  metric: "pickups",
  start: "2024-01-01",
  end: "2024-01-03",
  points: [
    { ts: "2024-01-01T00:00:00", value: 111 },
    { ts: "2024-01-02T00:00:00", value: 222 },
  ],
};
export const quality: Schemas["QualityStage"][] = [
  {
    stage: "gold",
    overall: "WARN",
    results: [
      { name: "grid_complete", status: "PASS", message: "ok", metrics: {} },
      { name: "weather_coverage", status: "WARN", message: "weather for 31 of 152 days", metrics: {} },
    ],
  },
];

const model = (wape: number) => ({ n: 100, mae: 3.2, rmse: 4.8, wape, bias: 0.01 });
export const perf: ForecastPerformance = {
  data_label: "TEST / SYNTHETIC DATA",
  mode: "sample",
  data_days: ["2024-01-01", "2024-02-25"],
  test_rows: 6048,
  test_days: 21,
  zones: 12,
  overall: {
    lightgbm: model(0.223),
    seasonal_mean_4w: model(0.224),
    seasonal_naive: model(0.279),
    naive: model(0.306),
  },
  best_baseline: "seasonal_mean_4w",
  folds: [
    { fold: 0, test_days: ["2024-02-05", "2024-02-11"] },
    { fold: 2, test_days: ["2024-02-19", "2024-02-25"] },
  ],
  interval: { nominal: 0.8, overall: { n: 6048, coverage: 0.794, mean_width: 4 }, by_volume: {} },
  bootstrap: { improvement: { seasonal_mean_4w: { wape_point_difference: 0.001, difference_ci95: [-0.006, 0.005] } } },
  oracle_weather_experiment: { label: "ORACLE: uses actual weather.", wape_without_weather: 0.223, wape_with_oracle_weather: 0.226 },
};
export const nextDay: Schemas["NextDayForecast"] = {
  data_label: "TEST / SYNTHETIC DATA",
  model_id: "m1",
  target_date: "2024-02-26",
  zone_id: null,
  zone_name: null,
  nominal_coverage: 0.8,
  empirical_coverage_in_evaluation: 0.794,
  note: "City-wide total of the zone point forecasts.",
  points: [
    { hour_ts: "2024-02-26T00:00:00", forecast: 50 },
    { hour_ts: "2024-02-26T01:00:00", forecast: 40 },
  ],
};
export const backtest: Schemas["BacktestForecast"] = {
  data_label: "TEST / SYNTHETIC DATA",
  zone_id: 3,
  zone_name: "Sample Zone 03",
  date: "2024-02-25",
  note: "Forecast made from 00:00 of the day using only earlier days; the model never saw this day (walk-forward fold).",
  points: [{ hour_ts: "2024-02-25T00:00:00", forecast: 10, lo: 6, hi: 14, actual: 9 }],
};

export const anomalyItem = (i: number): Schemas["AnomalyItem"] => ({
  event_id: i,
  location_id: 3,
  zone: "Sample Zone 03",
  borough: "Sample",
  direction: "surge",
  severity: "high",
  start: "2024-02-10T16:00:00",
  end: "2024-02-10T21:00:00",
  hours_flagged: 4,
  hours_span: 5,
  event_z: 16.3,
  peak_z: 14.4,
  actual: 428,
  forecast: 139,
  excess: 289,
  ratio: 3.1,
  scope: "partly shared",
  citywide_share: 0.13,
  overlapping_events: 0,
  context: ["freezing temperatures (daily high -3.9 C)"],
  explanation:
    "Sample Zone 03 (Sample) had 428 pickups between 16:00 and 21:00. This coincided with: freezing temperatures. This describes co-occurrence in the data, not a cause.",
});
export const anomalyPage = (total: number, offset = 0, n = 10): Schemas["AnomalyPage"] => ({
  data_label: "TEST / SYNTHETIC DATA",
  accuracy_status: "verified against planted ground truth (synthetic data only)",
  total,
  limit: 10,
  offset,
  items: Array.from({ length: Math.min(n, Math.max(0, total - offset)) }, (_, i) => anomalyItem(offset + i + 1)),
});
export const anomalySummary: AnomalySummary = {
  data_label: "TEST / SYNTHETIC DATA",
  accuracy_status: "verified against planted ground truth (synthetic data only)",
  scored_days: ["2024-02-05", "2024-02-25"],
  events_total: 3,
  events_per_1000_zone_days: 11.9,
  by_severity: { high: 1, medium: 1, low: 1 },
  by_direction: { surge: 2, drop: 1 },
};

export const optBacktest: OptimizationBacktest = {
  label: "SIMULATED SCENARIO under explicit assumptions; not a forecast of real-world outcomes",
  data_label: "TEST / SYNTHETIC DATA",
  windows_scored: 28,
  days: 14,
  planners: {
    no_repositioning: { served_share: 0.83, vehicles_moved_per_window: 0 },
    plan_lightgbm: { served_share: 0.84, vehicles_moved_per_window: 100 },
    plan_seasonal_mean: { served_share: 0.842, vehicles_moved_per_window: 130 },
    plan_oracle: { served_share: 0.86, vehicles_moved_per_window: 150 },
  },
  lightgbm_vs_none: { point: 0.005, ci95: [0.003, 0.007] },
  lightgbm_vs_seasonal_mean_planning: { point: -0.002, ci95: [-0.003, -0.001] },
  assumptions: { coverage: 0.85 },
  design: "For each out-of-sample day and window a plan is scored against ACTUAL demand.",
};
export const scenario = (over: Partial<Schemas["ScenarioResponse"]> = {}): Schemas["ScenarioResponse"] => ({
  label: "SIMULATED SCENARIO under explicit assumptions; not a forecast of real-world outcomes",
  data_label: "TEST / SYNTHETIC DATA",
  status: "optimal",
  message: "optimal under the stated assumptions",
  context: { date: "2024-02-25", window: "17:00-20:00" },
  assumptions: { max_km: 6, coverage: 0.85 },
  fleet: 3199,
  demand_total: 20000,
  served_before: 16800,
  served_after: 17000,
  service_share_before: 0.84,
  service_share_after: 0.85,
  vehicles_moved: 64,
  km_total: 165,
  best_attainable_service_share: null,
  moves: [{ from_zone: 3, to_zone: 7, from_name: "Sample Zone 03", to_name: "Sample Zone 07", vehicles: 9, km: 0.67 }],
  solver: {},
  ...over,
});

export const analystStatus: Schemas["AnalystStatus"] = {
  planner: "deterministic",
  llm_configured: false,
  llm_status: "not configured (no key): deterministic planner in use",
  tools: 13,
  note: "Answers are built only from read-only tool results and checked for grounding.",
};
export const analystAnswer = (over: Partial<Schemas["AnalystResponse"]> = {}): Schemas["AnalystResponse"] => ({
  question: "What were the busiest zones?",
  status: "answered",
  mode: "deterministic",
  intent: "top_zones",
  data_label: "TEST / SYNTHETIC DATA",
  statements: [
    { kind: "ASSUMPTION", text: "No period was given, so I used the last 7 days.", fact_ids: [] },
    { kind: "FACT", text: "The busiest zones were: first, Sample Zone 03: 5,123.", fact_ids: ["c1.r1.value"] },
    { kind: "INTERPRETATION", text: "This describes counts, not causes.", fact_ids: [] },
    { kind: "LIMITATION", text: "Yellow taxis only.", fact_ids: [] },
  ],
  tools_used: [
    {
      call_id: "c1",
      name: "get_top_zones",
      args: { start: "2024-02-19", end: "2024-02-26" },
      ok: true,
      error: null,
      facts: [{ id: "c1.r1.value", label: "pickups in rank 1 zone", value: "5,123" }],
      data: {},
    },
  ],
  warnings: [],
  grounding: { checked: 2, removed: 0 },
  ...over,
});

export type Handler = (url: URL, init?: RequestInit) => unknown | Response;

/** Route fetch calls by path. Unknown paths fail loudly so a page cannot silently use a guess. */
export function mockApi(routes: Record<string, Handler | unknown>) {
  const fn = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), "http://localhost");
    const h = routes[url.pathname];
    if (h === undefined) {
      return new Response(JSON.stringify({ error: { code: "no_route", message: `no mock for ${url.pathname}`, request_id: "t" } }), { status: 404 });
    }
    const out = await (typeof h === "function" ? (h as Handler)(url, init) : h);
    return out instanceof Response ? out : new Response(JSON.stringify(out), { status: 200, headers: { "Content-Type": "application/json" } });
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}

export const errorResponse = (status: number, code: string, message: string, extra: object = {}) =>
  new Response(JSON.stringify({ error: { code, message, request_id: "req-123", ...extra } }), { status });

export const baseRoutes = {
  "/api/v1/meta": meta,
  "/api/v1/zones": zones,
  "/api/v1/quality": quality,
  "/api/v1/demand/compare": compare,
  "/api/v1/demand/top-zones": top,
  "/api/v1/demand/profile/hourly": profile,
  "/api/v1/demand/series": series,
  "/api/v1/forecast/performance": perf,
  "/api/v1/forecast/next-day": nextDay,
  "/api/v1/forecast/backtest": backtest,
  "/api/v1/anomalies": () => anomalyPage(3),
  "/api/v1/anomalies/summary": anomalySummary,
  "/api/v1/optimization/backtest": optBacktest,
  "/api/v1/optimization/scenario": () => scenario(),
  "/api/v1/analyst/status": analystStatus,
  "/api/v1/analyst/ask": () => analystAnswer(),
};
