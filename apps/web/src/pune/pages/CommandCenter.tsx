import { state } from "../../api/client";
import { fmtInt, fmtNum } from "../../lib/format";
import { useAsync } from "../../lib/useAsync";
import { ChartPanel, DataSourceStatus, EmptyState, ErrorState, EventItem, ForecastPanel, LoadingSkeleton, MapPanel, MetricCard, TimeRangeSelector, ZoneDetailsPanel } from "../../ui";
import { usePune } from "../PuneContext";
import { ageText } from "../time";
import type { Snapshot } from "../types";

const pct = (ratio: number | null | undefined) =>
  ratio == null ? undefined : `${ratio >= 1 ? "+" : "−"}${Math.abs((ratio - 1) * 100).toFixed(0)}% vs forecast`;

function ageOf(s: Snapshot, key: string, elapsed: number) {
  const src = s.sources.find((x) => x.key === key);
  return src?.age_s == null ? null : src.age_s + elapsed;
}

/** The whole picture on one screen: totals, the map, events, today's forecast, and source health. */
export function CommandCenter() {
  const p = usePune();
  const s = p.snapshot;
  const series = useAsync((sig) => state.series({ back: 24, ahead: 24 }, sig), [p.seq]);
  if (p.geometryError) return <ErrorState title="Could not load the map">{p.geometryError.message}</ErrorState>;
  if (!s || !p.geometry) {
    if (p.stream.unavailable)
      return (
        <EmptyState title="The ingestion worker is not running">
          Start it with <code>python -m mobilityops.cli pune-worker</code>. Nothing is shown until it has written data,
          and nothing is made up while it is away.
        </EmptyState>
      );
    return <LoadingSkeleton lines={5} height={360} />;
  }
  const env = s.environment;
  const ratio = s.totals.ratio;
  const today = series.data;
  const zoneValue = s.zones.find((z) => z.id === p.zoneId);
  const overlap = s.events;
  const top = overlap.some((e) => e.severity === "high") ? "high" : overlap.some((e) => e.severity === "medium") ? "medium" : overlap.length ? "low" : null;
  return (
    <div className="stack">
      <div className="toolbar">
        <TimeRangeSelector value={p.selector} onChange={p.setSelector} />
        <p className="small muted" aria-live="polite">{s.window_note}</p>
      </div>
      <div className="metrics">
        <MetricCard
          label={p.selector === "forecast" ? "Simulated pickups" : "Simulated pickups, window"}
          value={s.totals.actual == null ? "not yet" : fmtInt(s.totals.actual)}
          delta={pct(ratio)}
          deltaTone={ratio == null ? "flat" : ratio >= 1.15 ? "up" : ratio <= 0.85 ? "down" : "flat"}
          note={s.window_note}
          kind="SIMULATED"
        />
        <MetricCard
          label="Forecast, window"
          value={fmtInt(s.totals.forecast)}
          note={`80% range per zone, summed: ${fmtInt(s.totals.lo)} to ${fmtInt(s.totals.hi)}`}
          kind="PREDICTED"
        />
        <MetricCard
          label="Today so far"
          value={today ? fmtInt(today.today_actual) : "…"}
          delta={today && today.today_forecast > 0 ? pct(today.today_actual / today.today_forecast) : undefined}
          deltaTone="flat"
          note={today ? `Forecast for the same hours: ${fmtInt(today.today_forecast)}` : undefined}
          kind="SIMULATED"
        />
        <MetricCard
          label="Events today"
          value={overlap.length}
          note={top ? `Highest severity: ${top}` : "None detected so far"}
          kind="SIMULATED"
        />
        <MetricCard
          label="Weather"
          value={env.temperature ? fmtNum(env.temperature.value, 1) : "n/a"}
          unit="°C"
          note={
            env.precipitation
              ? `Rain ${fmtNum(env.precipitation.value, 1)} mm · humidity ${env.humidity ? fmtInt(env.humidity.value) : "n/a"}%`
              : "No reading"
          }
          kind="NEAR-REAL-TIME"
          modelled
          freshness={env.temperature?.freshness ?? "OFFLINE"}
          ageSeconds={ageOf(s, "open-meteo-forecast", p.elapsed)}
        />
        <MetricCard
          label="Air quality (US AQI)"
          value={env.us_aqi ? fmtInt(env.us_aqi.value) : "n/a"}
          note={env.pm2_5 ? `PM2.5 ${fmtNum(env.pm2_5.value, 1)} µg/m³ (model, not a station)` : "No reading"}
          kind="NEAR-REAL-TIME"
          modelled
          freshness={env.us_aqi?.freshness ?? "OFFLINE"}
          ageSeconds={ageOf(s, "open-meteo-air-quality", p.elapsed)}
        />
      </div>
      <div className="split">
        <ChartPanel
          title="Zones"
          subtitle="Simulated demand against the forecast, by zone"
          kind="SIMULATED"
          freshness={s.freshness}
          ageSeconds={s.sources.find((x) => x.key === "simulated-demand")?.age_s ?? null}
        >
          <MapPanel
            geometry={p.geometry}
            values={s.zones}
            layer={p.layer}
            onLayerChange={p.setLayer}
            selectedId={p.zoneId}
            onSelect={p.setZoneId}
          />
        </ChartPanel>
        <div className="stack">
          <ChartPanel title="Zone details" subtitle={p.zoneId == null ? undefined : "Today, hour by hour"} kind="SIMULATED">
            <ZoneDetailsPanel zoneId={p.zoneId} seq={p.seq} value={zoneValue} onClear={() => p.setZoneId(null)} />
          </ChartPanel>
          <ChartPanel title="Events" subtitle="Where demand left its forecast today" kind="SIMULATED">
            {overlap.length === 0 ? (
              <EmptyState title="No events so far today">
                An event needs at least two consecutive hours far outside the forecast range. Most days have none.
              </EmptyState>
            ) : (
              <ul className="events">
                {overlap.slice(0, 5).map((e) => (
                  <EventItem key={e.id} event={e} onSelect={p.setZoneId} selected={e.zone_id === p.zoneId} />
                ))}
              </ul>
            )}
          </ChartPanel>
        </div>
      </div>
      <ChartPanel
        title="City, today"
        subtitle="Simulated pickups against the forecast, 24 hours back to 24 ahead"
        kind="PREDICTED"
        footer={today?.envelope_note}
      >
        {series.error && !today ? (
          <ErrorState title="Could not load the city series" onRetry={series.reload}>{series.error.message}</ErrorState>
        ) : today ? (
          <ForecastPanel series={today.series} label="City: simulated pickups and forecast" />
        ) : (
          <LoadingSkeleton lines={4} height={260} />
        )}
      </ChartPanel>
      <ChartPanel title="Data sources" subtitle={`Updated ${ageText(p.elapsed)}`}>
        <DataSourceStatus sources={s.sources} elapsedSeconds={p.elapsed} variant="strip" />
      </ChartPanel>
    </div>
  );
}
