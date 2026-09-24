import type { Geometry, MapLayer, ZoneValue } from "./types";

export interface Projection {
  width: number;
  height: number;
  xy: (lon: number, lat: number) => [number, number];
}

/** Equirectangular projection of the study box, scaled to a 1000-unit-wide SVG. */
export function makeProjection(bbox: number[], width = 1000): Projection {
  const [latMin = 0, lonMin = 0, latMax = 1, lonMax = 1] = bbox;
  const k = Math.cos((((latMin + latMax) / 2) * Math.PI) / 180);
  const w = (lonMax - lonMin) * k;
  const h = latMax - latMin;
  const scale = width / w;
  return {
    width,
    height: h * scale,
    xy: (lon, lat) => [(lon - lonMin) * k * scale, (latMax - lat) * scale],
  };
}

export function ringPath(ring: number[][], p: Projection): string {
  return (
    ring
      .map(([lon, lat], i) => {
        const [x, y] = p.xy(lon ?? 0, lat ?? 0);
        return `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`;
      })
      .join("") + "Z"
  );
}

type RGB = [number, number, number];
const BELOW: RGB = [59, 130, 246];
const MID: RGB = [120, 134, 156];
const ABOVE: RGB = [249, 115, 22];
const LOW: RGB = [186, 230, 253];
const HIGH: RGB = [3, 105, 161];

const mix = (a: RGB, b: RGB, t: number): string => {
  const c = a.map((v, i) => Math.round(v + (b[i]! - v) * t));
  return `rgb(${c[0]},${c[1]},${c[2]})`;
};

/** Ratio (actual / forecast) to colour: blue below, grey at 1.0, orange above; clamped to 0.5..1.5. */
export function ratioColor(ratio: number): string {
  const t = Math.max(-1, Math.min(1, (ratio - 1) / 0.5));
  return t < 0 ? mix(MID, BELOW, -t) : mix(MID, ABOVE, t);
}

/** Value to colour on a light-to-deep-blue ramp, square-root scaled so quiet zones stay visible. */
export function rampColor(value: number, max: number): string {
  if (max <= 0) return mix(LOW, HIGH, 0);
  return mix(LOW, HIGH, Math.sqrt(Math.max(0, Math.min(1, value / max))));
}

export const EVENT_COLORS = { surge: "rgb(249,115,22)", drop: "rgb(59,130,246)" } as const;

export interface LayerPaint {
  fill: (v: ZoneValue | undefined) => string;
  /** Legend: gradient stops and end labels. */
  legend: { from: string; to: string; mid?: string; left: string; right: string; middle?: string };
}

export function layerPaint(layer: MapLayer, values: ZoneValue[]): LayerPaint {
  const idle = "var(--zone-idle)";
  if (layer === "ratio") {
    return {
      fill: (v) => (v?.ratio == null || v.forecast < 1 ? idle : ratioColor(v.ratio)),
      legend: {
        from: ratioColor(0.5),
        mid: ratioColor(1),
        to: ratioColor(1.5),
        left: "0.5× forecast or less",
        middle: "as forecast",
        right: "1.5× or more",
      },
    };
  }
  if (layer === "events") {
    return {
      fill: (v) => (v && v.status !== "normal" ? EVENT_COLORS[v.status] : idle),
      legend: {
        from: EVENT_COLORS.drop,
        to: EVENT_COLORS.surge,
        left: "drop",
        right: "surge",
      },
    };
  }
  const pick = (v: ZoneValue) => (layer === "demand" ? v.actual ?? 0 : v.forecast);
  const max = values.reduce((m, v) => Math.max(m, pick(v)), 0);
  return {
    fill: (v) => (v ? rampColor(pick(v), max) : idle),
    legend: {
      from: rampColor(0, 1),
      to: rampColor(1, 1),
      left: "0",
      right: `${Math.round(max).toLocaleString("en-US")} (busiest zone)`,
    },
  };
}

export function centroidOf(g: Geometry, id: number): [number, number] | null {
  const z = g.zones.find((zone) => zone.id === id);
  return z ? [z.lon, z.lat] : null;
}
