import { useMemo, useState } from "react";
import { fmtInt } from "../lib/format";
import { layerPaint, makeProjection, ringPath } from "../pune/mapGeometry";
import { MAP_LAYERS, type Geometry, type MapLayer, type ZoneValue } from "../pune/types";

/**
 * Pune's zones as an SVG map coloured by the chosen layer. Click a zone to inspect it. The map is
 * a picture of the same data as the zone list and the zone selector, which are the keyboard and
 * screen-reader route: 91 tab stops on the map itself would help nobody.
 */
export function MapPanel({
  geometry,
  values,
  layer,
  onLayerChange,
  selectedId,
  onSelect,
}: {
  geometry: Geometry;
  values: ZoneValue[];
  layer: MapLayer;
  onLayerChange: (l: MapLayer) => void;
  selectedId: number | null;
  onSelect: (id: number | null) => void;
}) {
  const [hoverId, setHoverId] = useState<number | null>(null);
  const proj = useMemo(() => makeProjection(geometry.bbox), [geometry.bbox]);
  const paths = useMemo(
    () => geometry.zones.map((z) => ({ id: z.id, d: ringPath(z.ring, proj) })),
    [geometry.zones, proj],
  );
  const byId = useMemo(() => new Map(values.map((v) => [v.id, v])), [values]);
  const paint = useMemo(() => layerPaint(layer, values), [layer, values]);
  const names = useMemo(() => new Map(geometry.zones.map((z) => [z.id, z])), [geometry.zones]);
  const shown = names.get(hoverId ?? selectedId ?? -1);
  const shownValue = shown ? byId.get(shown.id) : undefined;
  const sorted = useMemo(() => [...geometry.zones].sort((a, b) => a.name.localeCompare(b.name)), [geometry.zones]);
  const sel = selectedId != null ? names.get(selectedId) : undefined;
  const selXY = sel ? proj.xy(sel.lon, sel.lat) : null;

  return (
    <div className="map">
      <div className="map-tools">
        <label>
          Layer
          <select value={layer} onChange={(e) => onLayerChange(e.target.value as MapLayer)}>
            {MAP_LAYERS.map((l) => (
              <option key={l.id} value={l.id}>
                {l.label}
              </option>
            ))}
          </select>
        </label>
        <label>
          Zone
          <select value={selectedId ?? ""} onChange={(e) => onSelect(e.target.value ? Number(e.target.value) : null)}>
            <option value="">None selected</option>
            {sorted.map((z) => (
              <option key={z.id} value={z.id}>
                {z.name} ({z.sector})
              </option>
            ))}
          </select>
        </label>
      </div>
      <svg
        viewBox={`0 0 ${proj.width} ${proj.height.toFixed(0)}`}
        className="map-svg"
        role="img"
        aria-label={`Map of ${geometry.zones.length} Pune zones coloured by ${MAP_LAYERS.find((l) => l.id === layer)?.label.toLowerCase()}. Use the zone selector for a keyboard route.`}
        onMouseLeave={() => setHoverId(null)}
      >
        {paths.map((p) => {
          const v = byId.get(p.id);
          return (
            <path
              key={p.id}
              d={p.d}
              fill={paint.fill(v)}
              className={p.id === selectedId ? "zone zone-sel" : "zone"}
              data-zone={p.id}
              onMouseEnter={() => setHoverId(p.id)}
              onClick={() => onSelect(p.id === selectedId ? null : p.id)}
            >
              <title>{names.get(p.id)?.name}</title>
            </path>
          );
        })}
        {sel && selXY && (
          <g pointerEvents="none">
            <circle cx={selXY[0]} cy={selXY[1]} r={5} className="zone-pin" />
            <text x={selXY[0] + 9} y={selXY[1] - 8} className="zone-label">
              {sel.name}
            </text>
          </g>
        )}
      </svg>
      <div className="map-legend" aria-hidden="true">
        <span className="small muted">{paint.legend.left}</span>
        <span
          className="map-ramp"
          style={{
            background: `linear-gradient(90deg, ${paint.legend.from}, ${paint.legend.mid ?? paint.legend.from}, ${paint.legend.to})`,
          }}
        />
        <span className="small muted">{paint.legend.right}</span>
      </div>
      <p className="map-readout small" aria-live="polite">
        {shown ? (
          <>
            <strong>{shown.name}</strong> <span className="muted">({shown.sector})</span>
            {shownValue && (
              <>
                {" "}
                · pickups {fmtInt(shownValue.actual)} · forecast {fmtInt(shownValue.forecast)} ({fmtInt(shownValue.lo)} to{" "}
                {fmtInt(shownValue.hi)})
                {shownValue.ratio != null && ` · ${(shownValue.ratio * 100).toFixed(0)}% of forecast`}
                {shownValue.status !== "normal" && ` · ${shownValue.status.toUpperCase()}`}
              </>
            )}
          </>
        ) : (
          <span className="muted">Hover or pick a zone to read its numbers.</span>
        )}
      </p>
      <p className="small muted">
        {geometry.attribution}. Zones are the service areas of OpenStreetMap suburbs, not administrative wards.
      </p>
    </div>
  );
}
