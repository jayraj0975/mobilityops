/** Shapes of the messages on /api/v1/live/stream (the API documents them as generic objects). */
export interface ReplayZone {
  location_id: number;
  zone: string;
  actual: number;
  forecast: number;
}
export interface ReplayAnomaly {
  zone: string;
  direction: string;
  severity: string;
  scope: string;
}
export interface ReplayTick {
  kind: "replay";
  label: string;
  index: number;
  of: number;
  loop: number;
  hour_ts: string;
  actual: number;
  forecast: number;
  baseline: number;
  abs_error: number;
  running_wape: number | null;
  top_zones: ReplayZone[];
  anomalies: ReplayAnomaly[];
}
export interface StationRow {
  name: string;
  capacity: number;
  bikes: number;
  docks: number;
}
export interface CitibikeData {
  stations: number;
  active: number;
  offline: number;
  bikes: number;
  ebikes: number;
  docks: number;
  empty: number;
  full: number;
  largest_empty: StationRow[];
  largest_full: StationRow[];
}
export interface WeatherData {
  description: string | null;
  temperature_c: number | null;
  wind_kmh: number | null;
  humidity_pct: number | null;
  precipitation_last_hour_mm: number | null;
  station: string;
}
export interface Feed<T> {
  kind: "feed";
  feed: "citibike" | "weather";
  status: "starting" | "ok" | "unavailable";
  source: string;
  as_of: string | null;
  fetched_at: string | null;
  error: string | null;
  data: T | null;
}
export interface HistoryPoint {
  ts: string;
  bikes: number;
  docks: number;
  empty: number;
}
export interface Hello {
  kind: "hello";
  server_time: string;
  data_label: string;
  replay:
    | { available: false; reason: string }
    | { available: true; label: string; start: string; end: string; ticks: number; seconds_per_hour: number; loop_seconds: number; history: ReplayTick[] };
  feeds: { enabled: false } | { enabled: true; citibike?: Feed<CitibikeData>; weather?: Feed<WeatherData>; history?: HistoryPoint[] };
}
