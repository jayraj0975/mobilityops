import { useEffect, useState } from "react";
import { DataTable } from "../components/DataTable";
import { LinesChart } from "../components/Charts";
import { Empty } from "../components/State";
import { fmtInt, fmtNum, fmtPct } from "../lib/format";
import type { CitibikeData, Feed, ReplayTick, StationRow, WeatherData } from "../lib/live";
import { useLiveStream, type LiveStatus } from "../lib/useLiveStream";

const STATUS_TEXT: Record<LiveStatus, string> = {
  connecting: "Connecting to the live stream…",
  live: "Connected: receiving live updates",
  reconnecting: "Connection lost: reconnecting…",
};

function useNow(ms: number): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), ms);
    return () => clearInterval(t);
  }, [ms]);
  return now;
}

/** "3 min ago" from a timestamp; the publisher's own time, not when we fetched it. */
export function ageText(iso: string | null, now: number): string {
  if (!iso) return "time unknown";
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return "time unknown";
  const s = Math.max(0, Math.round((now - t) / 1000));
  if (s < 90) return `${s} s ago`;
  const m = Math.round(s / 60);
  return m < 90 ? `${m} min ago` : `${Math.round(m / 60)} h ago`;
}

const hourLabel = (iso: string) => iso.slice(5, 16).replace("T", " ");

function Kpi({ label, value, note }: { label: string; value: string; note?: string }) {
  return (
    <div className="kpi">
      <span className="kpi-label">{label}</span>
      <span className="kpi-value">{value}</span>
      {note && <span className="muted small">{note}</span>}
    </div>
  );
}

function FeedNotice({ feed, now }: { feed: Feed<CitibikeData> | Feed<WeatherData> | undefined; now: number }) {
  if (!feed || feed.status === "starting") return <p role="status" className="muted">Waiting for the first reading…</p>;
  return (
    <>
      {feed.status === "unavailable" && (
        <p role="alert" className="notice notice-error">
          The source is not answering right now ({feed.error}).{" "}
          {feed.data ? "The figures below are the last good reading, not current." : "No reading has been received yet."}
        </p>
      )}
      <p className="muted small">
        Source: {feed.source}. Reading from {feed.as_of ? new Date(feed.as_of).toLocaleTimeString() : "an unknown time"} (
        {ageText(feed.as_of, now)}).
      </p>
    </>
  );
}

const stationColumns = [
  { key: "name", header: "Station", render: (r: StationRow) => r.name },
  { key: "capacity", header: "Docks", numeric: true, render: (r: StationRow) => fmtInt(r.capacity) },
];

function Replay({ ticks, label }: { ticks: ReplayTick[]; label: string }) {
  const last = ticks[ticks.length - 1];
  if (!last) return <Empty>Waiting for the next replay hour…</Empty>;
  const errPct = last.actual > 0 ? last.abs_error / last.actual : null;
  return (
    <>
      <div className="kpis">
        <Kpi label="Replay hour (New York time)" value={last.hour_ts.slice(0, 16).replace("T", " ")} note={`hour ${last.index + 1} of ${last.of}${last.loop > 0 ? `, loop ${last.loop + 1}` : ""}`} />
        <Kpi label="Actual pickups this hour" value={fmtInt(last.actual)} />
        <Kpi label="Forecast made beforehand" value={fmtInt(last.forecast)} note={errPct == null ? undefined : `off by ${fmtPct(errPct)}`} />
        <Kpi label="City-total error so far (WAPE)" value={fmtPct(last.running_wape)} note="hourly totals over all zones; easier than one zone, whose error is on the Forecast page" />
      </div>
      <LinesChart
        title="City pickups per hour: actual against the forecast"
        data={ticks.map((t) => ({ x: hourLabel(t.hour_ts), actual: t.actual, forecast: t.forecast, baseline: t.baseline }))}
        series={[
          { key: "actual", label: "Actual" },
          { key: "forecast", label: "Model forecast" },
          { key: "baseline", label: "4-week seasonal mean", dashed: true },
        ]}
      />
      <p className="muted small">{label}</p>
      <h3>Busiest zones this hour</h3>
      <DataTable
        caption="Busiest zones this hour"
        rows={last.top_zones}
        rowKey={(r) => String(r.location_id)}
        columns={[
          { key: "zone", header: "Zone", render: (r) => r.zone },
          { key: "actual", header: "Actual", numeric: true, render: (r) => fmtInt(r.actual) },
          { key: "forecast", header: "Forecast", numeric: true, render: (r) => fmtInt(r.forecast) },
        ]}
      />
      <h3>Anomaly events covering this hour</h3>
      {last.anomalies.length === 0 ? (
        <Empty>None. Events describe what coincided with a deviation; they never assert a cause.</Empty>
      ) : (
        <ul>
          {last.anomalies.map((a, i) => (
            <li key={i}>
              <strong>{a.zone}</strong>: {a.direction}, {a.severity} severity ({a.scope}).
            </li>
          ))}
        </ul>
      )}
    </>
  );
}

export function Live() {
  const live = useLiveStream();
  const now = useNow(1000);
  const replay = live.hello?.replay;
  const feedsOff = live.hello?.feeds.enabled === false;
  const cb = live.citibike;
  const wx = live.weather;
  const d = cb?.data ?? null;

  return (
    <>
      <p role="status" className={live.status === "live" ? "muted" : "notice"}>
        <strong>{STATUS_TEXT[live.status]}</strong>
        {live.message && ` (${live.message})`}
      </p>

      <section aria-labelledby="replay-h">
        <h2 id="replay-h">Taxi demand: replay of held-out days</h2>
        <div className="banner banner-sim" role="note">
          <strong>REPLAY, NOT LIVE.</strong> NYC taxi trips are published monthly, so no live taxi feed exists. This advances
          through days the model had not seen when it forecast them, one hour every{" "}
          {replay?.available ? fmtNum(replay.seconds_per_hour, 1) : "few"} seconds, on a clock shared by every viewer.
        </div>
        {replay && !replay.available && <p className="notice">The replay is not available yet: {replay.reason}</p>}
        {(replay?.available || live.ticks.length > 0) && <Replay ticks={live.ticks} label={replay?.available ? replay.label : ""} />}
      </section>

      <section aria-labelledby="feeds-h">
        <h2 id="feeds-h">Live city feeds</h2>
        <div className="banner banner-real" role="note">
          <strong>LIVE.</strong> Real public data, fetched while someone is watching: Citi Bike station availability and the
          current weather in Central Park.
        </div>
        {feedsOff ? (
          <p className="notice">Live feeds are switched off on this server (MOBILITYOPS_LIVE_FEEDS=false).</p>
        ) : (
          <>
            <h3>Citi Bike availability</h3>
            <FeedNotice feed={cb} now={now} />
            {d && (
              <>
                <div className="kpis">
                  <Kpi label="Bikes available" value={fmtInt(d.bikes)} note={`${fmtInt(d.ebikes)} of them e-bikes`} />
                  <Kpi label="Free docks" value={fmtInt(d.docks)} />
                  <Kpi label="Empty stations" value={fmtInt(d.empty)} note={`of ${fmtInt(d.active)} in service`} />
                  <Kpi label="Full stations" value={fmtInt(d.full)} note={d.offline > 0 ? `${fmtInt(d.offline)} stations offline` : undefined} />
                </div>
                {live.history.length > 1 && (
                  <LinesChart
                    title="Bikes and docks available, since this server started watching"
                    yLabel="count"
                    data={live.history.map((h) => ({ x: h.ts.slice(11, 16), bikes: h.bikes, docks: h.docks }))}
                    series={[
                      { key: "bikes", label: "Bikes available" },
                      { key: "docks", label: "Free docks" },
                    ]}
                  />
                )}
                <div className="two-col">
                  <div>
                    <h3>Largest empty stations</h3>
                    {d.largest_empty.length === 0 ? <Empty>None right now.</Empty> : <DataTable caption="Largest empty stations" rows={d.largest_empty} rowKey={(r) => r.name} columns={stationColumns} />}
                  </div>
                  <div>
                    <h3>Largest full stations</h3>
                    {d.largest_full.length === 0 ? <Empty>None right now.</Empty> : <DataTable caption="Largest full stations" rows={d.largest_full} rowKey={(r) => r.name} columns={stationColumns} />}
                  </div>
                </div>
              </>
            )}
            <h3>Weather in Central Park</h3>
            <FeedNotice feed={wx} now={now} />
            {wx?.data && (
              <div className="kpis">
                <Kpi label="Temperature" value={wx.data.temperature_c == null ? "n/a" : `${fmtNum(wx.data.temperature_c, 1)} °C`} note={wx.data.description ?? undefined} />
                <Kpi label="Wind" value={wx.data.wind_kmh == null ? "n/a" : `${fmtNum(wx.data.wind_kmh, 0)} km/h`} />
                <Kpi label="Humidity" value={wx.data.humidity_pct == null ? "n/a" : `${fmtNum(wx.data.humidity_pct, 0)}%`} />
                <Kpi label="Rain, last hour" value={wx.data.precipitation_last_hour_mm == null ? "n/a" : `${fmtNum(wx.data.precipitation_last_hour_mm, 1)} mm`} />
              </div>
            )}
          </>
        )}
      </section>
    </>
  );
}
