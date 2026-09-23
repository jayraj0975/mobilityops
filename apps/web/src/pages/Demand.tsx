import { useState } from "react";
import { api, type Schemas } from "../api/client";
import { DataTable } from "../components/DataTable";
import { Async, Empty } from "../components/State";
import { SeriesChart } from "../components/Charts";
import { addDays, fmtInt, fmtNum, fmtPct } from "../lib/format";
import { useAsync } from "../lib/useAsync";
import { lastDay } from "./Overview";

type Grain = "day" | "hour";
type Metric = "pickups" | "dropoffs" | "revenue";

export function Demand({ meta, zones }: { meta: Schemas["Meta"]; zones: Schemas["Zone"][] }) {
  const last = lastDay(meta);
  const first = meta.data_start.slice(0, 10);
  const [zone, setZone] = useState<number | undefined>(undefined);
  const [start, setStart] = useState(addDays(last, -27));
  const [end, setEnd] = useState(last);
  const [grain, setGrain] = useState<Grain>("day");
  const [metric, setMetric] = useState<Metric>("pickups");
  const [condition, setCondition] = useState<"rain" | "snow" | "freezing">("rain");

  const endExcl = addDays(end, 1);
  const invalid = start > end;
  const series = useAsync(
    (s) => (invalid ? Promise.reject(new Error("The start date must not be after the end date.")) : api.demandSeries({ start, end: endExcl, zone_id: zone, grain, metric }, s)),
    [start, endExcl, zone, grain, metric],
  );
  const top = useAsync((s) => (invalid ? Promise.resolve([]) : api.topZones({ start, end: endExcl, metric, limit: 10 }, s)), [start, endExcl, metric]);
  const weather = useAsync((s) => (invalid ? Promise.reject(new Error("Choose a valid range.")) : api.weather({ start, end: endExcl, condition, zone_id: zone }, s)), [start, endExcl, condition, zone]);

  return (
    <>
      <form className="controls" onSubmit={(e) => e.preventDefault()} aria-label="Demand filters">
        <label>
          Zone
          <select value={zone ?? ""} onChange={(e) => setZone(e.target.value ? Number(e.target.value) : undefined)}>
            <option value="">All zones (city)</option>
            {zones.map((z) => (
              <option key={z.location_id} value={z.location_id}>
                {z.zone} ({z.borough})
              </option>
            ))}
          </select>
        </label>
        <label>
          From
          <input type="date" value={start} min={first} max={last} onChange={(e) => setStart(e.target.value)} />
        </label>
        <label>
          To
          <input type="date" value={end} min={first} max={last} onChange={(e) => setEnd(e.target.value)} />
        </label>
        <label>
          Grain
          <select value={grain} onChange={(e) => setGrain(e.target.value as Grain)}>
            <option value="day">Day</option>
            <option value="hour">Hour</option>
          </select>
        </label>
        <label>
          Metric
          <select value={metric} onChange={(e) => setMetric(e.target.value as Metric)}>
            <option value="pickups">Pickups</option>
            <option value="dropoffs">Dropoffs</option>
            <option value="revenue">Revenue ($)</option>
          </select>
        </label>
      </form>
      {invalid && <p role="alert" className="notice notice-error">The start date must not be after the end date.</p>}

      <section aria-labelledby="series-h">
        <h2 id="series-h">{zone ? zones.find((z) => z.location_id === zone)?.zone : "All zones"}: {metric} by {grain}</h2>
        <Async state={series} what="series">
          {(d) => (
            <SeriesChart
              title={`${metric} by ${grain}`}
              xLabel={grain === "day" ? "Day" : "Hour"}
              yLabel={metric}
              data={d.points.map((p) => ({ x: grain === "day" ? p.ts.slice(0, 10) : p.ts.slice(0, 16).replace("T", " "), y: p.value }))}
            />
          )}
        </Async>
      </section>

      <section aria-labelledby="topz-h">
        <h2 id="topz-h">Top zones for the period</h2>
        <Async state={top} what="ranking">
          {(rows) =>
            rows.length === 0 ? (
              <Empty>No data for this range.</Empty>
            ) : (
              <DataTable
                caption="Top zones"
                rows={rows}
                rowKey={(r) => String(r.location_id)}
                columns={[
                  { key: "zone", header: "Zone", render: (r) => `${r.zone} (${r.borough})` },
                  { key: "value", header: metric, numeric: true, render: (r) => fmtInt(r.value) },
                  { key: "share", header: "Share of city", numeric: true, render: (r) => fmtPct(r.share) },
                ]}
              />
            )
          }
        </Async>
      </section>

      <section aria-labelledby="wx-h">
        <h2 id="wx-h">Weather and demand (association only)</h2>
        <label className="inline">
          Condition{" "}
          <select value={condition} onChange={(e) => setCondition(e.target.value as typeof condition)}>
            <option value="rain">Rain</option>
            <option value="snow">Snow</option>
            <option value="freezing">Freezing</option>
          </select>
        </label>
        <Async state={weather} what="weather comparison">
          {(w) => (
            <>
              <p>
                {w.days_with} days with {w.condition} and {w.days_without} without. Mean daily pickups:{" "}
                {fmtInt(w.mean_daily_with)} on {w.condition} days versus {fmtInt(w.mean_daily_without)} on others (ratio {fmtNum(w.raw_ratio, 2)}
                {w.weekday_adjusted_ratio != null && `; ${fmtNum(w.weekday_adjusted_ratio, 2)} after adjusting for the weekday mix`}).
              </p>
              <p className="notice">{w.caveat}</p>
            </>
          )}
        </Async>
      </section>
    </>
  );
}
