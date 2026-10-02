import type { Schemas } from "../api/client";

export type Snapshot = Schemas["StateSnapshot"];
export type ZoneValue = Schemas["ZoneValue"];
export type ZoneGeometry = Schemas["ZoneGeometry"];
export type Geometry = Schemas["Geometry"];
export type EventItemData = Schemas["EventItem"];
export type EventImpactData = Schemas["EventImpact"];

/** The shape of ``EventImpactData["scenario"]`` (typed loosely in the API as a free-form
 * dict since it's `optimization.model.ScenarioResult.to_dict()` - a SIMULATED SCENARIO,
 * never a forecast). */
export interface RepositioningScenario {
  status: "optimal" | "feasible_time_limit" | "infeasible" | "no_solution" | "unbounded" | "solver_error";
  message: string;
  label: string;
  fleet: number;
  demand_total: number;
  served_before: number;
  served_after: number;
  service_share_before: number | null;
  service_share_after: number | null;
  vehicles_moved: number;
  km_total: number;
  moves: { from_zone: number; to_zone: number; vehicles: number; km: number }[];
  assumptions: Record<string, unknown>;
}
export type SourceState = Schemas["SourceState"];
export type ZoneDetail = Schemas["ZoneDetail"];
export type CitySeries = Schemas["CitySeries"];
export type DataQuality = Schemas["DataQuality"];
export type Freshness = Schemas["SourceState"]["freshness"];
export type TimeSelector = Snapshot["selector"];

export const TIME_OPTIONS: { id: TimeSelector; label: string; hint: string }[] = [
  { id: "now", label: "NOW", hint: "The hour so far" },
  { id: "-15m", label: "−15 min", hint: "As of 15 minutes ago" },
  { id: "-1h", label: "−1 h", hint: "As of one hour ago" },
  { id: "-6h", label: "−6 h", hint: "As of six hours ago" },
  { id: "today", label: "TODAY", hint: "Today so far" },
  { id: "forecast", label: "FORECAST", hint: "Next full hour, predicted" },
];

export type MapLayer = "ratio" | "demand" | "forecast" | "events";
export const MAP_LAYERS: { id: MapLayer; label: string; hint: string }[] = [
  { id: "ratio", label: "Versus forecast", hint: "Simulated pickups divided by the forecast" },
  { id: "demand", label: "Demand", hint: "Simulated pickups in the window" },
  { id: "forecast", label: "Forecast", hint: "Forecast pickups in the window" },
  { id: "events", label: "Events", hint: "Zones with a detected surge or drop" },
];
