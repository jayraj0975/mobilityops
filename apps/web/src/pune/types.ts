import type { Schemas } from "../api/client";

export type Snapshot = Schemas["StateSnapshot"];
export type ZoneValue = Schemas["ZoneValue"];
export type ZoneGeometry = Schemas["ZoneGeometry"];
export type Geometry = Schemas["Geometry"];
export type EventItemData = Schemas["EventItem"];
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
