import { api, type Schemas } from "../api/client";
import { Async } from "../components/State";
import { BarsChart, SeriesChart } from "../components/Charts";
import { addDays, fmtInt, fmtPct } from "../lib/format";
import { useAsync } from "../lib/useAsync";

export const lastDay = (meta: Schemas["Meta"]): string => addDays(meta.data_end.slice(0, 10), -1);

export function Overview({ meta }: { meta: Schemas["Meta"] }) {
  const last = lastDay(meta);
  const end = addDays(last, 1);
  const w1 = addDays(last, -6);
  const w0 = addDays(last, -13);
  const cmp = useAsync((s) => api.compare({ a_start: w0, a_end: w1, b_start: w1, b_end: end }, s), [w0, w1, end]);
  const top = useAsync((s) => api.topZones({ start: w1, end, limit: 8 }, s), [w1, end]);
  const profile = useAsync((s) => api.hourlyProfile({ start: addDays(last, -27), end }, s), [last]);
  const daily = useAsync(
    (s) => api.demandSeries({ start: addDays(last, -59), end, grain: "day", metric: "pickups" }, s),
    [last],
  );
  const quality = useAsync((s) => api.quality(s), []);

  return (
    <>
      <section aria-labelledby="kpi-h">
        <h2 id="kpi-h">Last 7 days</h2>
        <Async state={cmp} what="summary">
          {(c) => (
            <div className="kpis">
              <div className="kpi">
                <span className="kpi-label">Pickups ({w1} to {last})</span>
                <span className="kpi-value">{fmtInt(c.period_b.total)}</span>
              </div>
              <div className="kpi">
                <span className="kpi-label">Per day</span>
                <span className="kpi-value">{fmtInt(c.period_b.per_day)}</span>
              </div>
              <div className="kpi">
                <span className="kpi-label">Per-day change vs the 7 days before</span>
                <span className="kpi-value">{fmtPct(c.per_day_change_pct)}</span>
                <span className="muted small">
                  from {fmtInt(c.period_a.per_day)} to {fmtInt(c.period_b.per_day)} a day
                </span>
              </div>
            </div>
          )}
        </Async>
      </section>

      <section aria-labelledby="top-h">
        <h2 id="top-h">Busiest zones, last 7 days</h2>
        <Async state={top} what="zones">
          {(rows) => (
            <BarsChart
              title="Pickups by zone"
              yLabel="pickups"
              data={rows.map((r) => ({ x: r.zone, y: r.value }))}
            />
          )}
        </Async>
      </section>

      <section aria-labelledby="daily-h">
        <h2 id="daily-h">Daily pickups, last 60 days</h2>
        <Async state={daily} what="daily series">
          {(d) => (
            <SeriesChart
              title="Citywide pickups per day"
              xLabel="Day"
              data={d.points.map((p) => ({ x: p.ts.slice(0, 10), y: p.value }))}
            />
          )}
        </Async>
      </section>

      <section aria-labelledby="hour-h">
        <h2 id="hour-h">Typical day: pickups by hour</h2>
        <Async state={profile} what="hourly profile">
          {(p) => (
            <SeriesChart
              title="Average pickups per hour of day (last 28 days)"
              xLabel="Hour"
              data={p.map((r) => ({ x: `${String(r.hour_of_day).padStart(2, "0")}:00`, y: r.avg_pickups }))}
            />
          )}
        </Async>
      </section>

      <section aria-labelledby="dq-h">
        <h2 id="dq-h">Data quality</h2>
        <Async state={quality} what="quality reports">
          {(stages) => (
            <ul className="plain">
              {stages.map((s) => (
                <li key={s.stage}>
                  <span className={`badge badge-${s.overall.toLowerCase()}`}>{s.overall}</span>{" "}
                  <strong>{s.stage}</strong>: {s.results.filter((r) => r.status === "PASS").length} of{" "}
                  {s.results.length} checks pass
                  {s.results.filter((r) => r.status !== "PASS").map((r) => (
                    <div key={r.name} className="muted small">
                      {r.status}: {r.name} – {r.message}
                    </div>
                  ))}
                </li>
              ))}
            </ul>
          )}
        </Async>
        <p className="muted small">
          {fmtInt(meta.rows_valid)} valid trips across {meta.n_zones} zones; built {meta.built_at_utc.slice(0, 16)} UTC
          (run {meta.run_id}). Timestamps are New York local time; the spring-forward hour is excluded and
          the fall-back hour is not modelled.
        </p>
      </section>
    </>
  );
}
