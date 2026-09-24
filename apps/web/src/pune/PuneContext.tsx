import { createContext, useContext } from "react";
import type { StreamState } from "./usePuneStream";
import type { Geometry, MapLayer, Snapshot, TimeSelector } from "./types";

export interface PuneData {
  stream: StreamState;
  /** The snapshot for the chosen time selector (the streamed one for NOW). */
  snapshot: Snapshot | undefined;
  snapshotError: Error | undefined;
  geometry: Geometry | undefined;
  geometryError: Error | undefined;
  selector: TimeSelector;
  setSelector: (s: TimeSelector) => void;
  layer: MapLayer;
  setLayer: (l: MapLayer) => void;
  zoneId: number | null;
  setZoneId: (id: number | null) => void;
  /** Client clock, refreshed every second. */
  now: number;
  /** Seconds since the newest snapshot arrived. */
  elapsed: number;
  /** Store version: changes whenever the worker writes. */
  seq: number;
}

export const PuneCtx = createContext<PuneData | null>(null);

export function usePune(): PuneData {
  const v = useContext(PuneCtx);
  if (!v) throw new Error("usePune must be used inside <PuneApp>");
  return v;
}
