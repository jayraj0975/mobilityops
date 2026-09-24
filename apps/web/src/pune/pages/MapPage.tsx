import { useMemo, useState } from "react";
import { fmtInt } from "../../lib/format";
import { ChartPanel, EmptyState, LoadingSkeleton, MapPanel, TimeRangeSelector, ZoneDetailsPanel } from "../../ui";
import { usePune } from "../PuneContext";

type SortKey = "deviation" | "demand" | "forecast";

/** A larger map with every zone ranked beside it: the accessible twin of the map. */
export function MapPage() {
  const p = usePune();
  const s = p.snapshot;
  const [sort, setSort] = useState<SortKey>("deviation");
  const names = useMemo(() => new Map(p.geometry?.zones.map((z) => [z.id, z]) ?? []), [p.geometry]);
  const ranked = useMemo(() => {
    if (!s) return [];
    const rows = [...s.zones];
    const key = (z: (typeof rows)[number]) =>
      sort === "deviation" ? Math.abs(z.z ?? 0) : sort === "demand" ? z.actual ?? 0 : z.forecast;
    return rows.sort((a, b) => key(b) - key(a)).slice(0, 25);
  }, [s, sort]);
  if (!s || !p.geometry) return p.stream.unavailable ? <EmptyState title="The ingestion worker is not running" /> : <LoadingSkeleton lines={5} height={400} />;
  return (
    <div className="stack">
      <div className="toolbar">
        <TimeRangeSelector value={p.selector} onChange={p.setSelector} />
        <p className="small muted">{s.window_note}</p>
      </div>
      <div className="split split-wide">
        <ChartPanel title="Pune zones" kind="SIMULATED" freshness={s.freshness}>
          <MapPanel geometry={p.geometry} values={s.zones} layer={p.layer} onLayerChange={p.setLayer} selectedId={p.zoneId} onSelect={p.setZoneId} />
        </ChartPanel>
        <div className="stack">
          <ChartPanel title="Zone details" kind="SIMULATED">
            <ZoneDetailsPanel zoneId={p.zoneId} seq={p.seq} value={s.zones.find((z) => z.id === p.zoneId)} onClear={() => p.setZoneId(null)} />
          </ChartPanel>
        </div>
      </div>
      <ChartPanel
        title="Top zones"
        subtitle="The 25 zones that stand out most in this window"
        actions={
          <label className="inline">
            Rank by
            <select value={sort} onChange={(e) => setSort(e.target.value as SortKey)}>
              <option value="deviation">Deviation from forecast</option>
              <option value="demand">Simulated pickups</option>
              <option value="forecast">Forecast</option>
            </select>
          </label>
        }
      >
        <div className="table-wrap">
          <table className="ops-table">
            <caption className="sr-only">Top zones in the selected window</caption>
            <thead>
              <tr>
                <th scope="col">Zone</th>
                <th scope="col">Sector</th>
                <th scope="col" className="num">Simulated pickups</th>
                <th scope="col" className="num">Forecast</th>
                <th scope="col" className="num">Range</th>
                <th scope="col" className="num">Of forecast</th>
                <th scope="col">Status</th>
              </tr>
            </thead>
            <tbody>
              {ranked.map((z) => (
                <tr key={z.id} className={z.id === p.zoneId ? "row-on" : undefined}>
                  <th scope="row">
                    <button type="button" className="linkish" onClick={() => p.setZoneId(z.id)}>
                      {names.get(z.id)?.name ?? z.id}
                    </button>
                  </th>
                  <td>{names.get(z.id)?.sector}</td>
                  <td className="num">{fmtInt(z.actual)}</td>
                  <td className="num">{fmtInt(z.forecast)}</td>
                  <td className="num">{fmtInt(z.lo)} to {fmtInt(z.hi)}</td>
                  <td className="num">{z.ratio == null ? "n/a" : `${(z.ratio * 100).toFixed(0)}%`}</td>
                  <td>{z.status === "normal" ? "normal" : z.status.toUpperCase()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </ChartPanel>
    </div>
  );
}
