import { state } from "../api/client";
import { fmtInt } from "../lib/format";
import { useAsync } from "../lib/useAsync";
import type { ZoneValue } from "../pune/types";
import { EmptyState } from "./EmptyState";
import { ErrorState } from "./ErrorState";
import { EventItem } from "./EventItem";
import { ForecastPanel } from "./ForecastPanel";
import { LoadingSkeleton } from "./LoadingSkeleton";

/** One zone: today's simulated demand against its forecast and range, and its events. */
export function ZoneDetailsPanel({
  zoneId,
  seq,
  value,
  onClear,
}: {
  zoneId: number | null;
  /** Changes whenever the store does, which triggers a reload. */
  seq: number;
  value?: ZoneValue;
  onClear: () => void;
}) {
  const detail = useAsync((s) => (zoneId == null ? Promise.resolve(null) : state.zone(zoneId, s)), [zoneId, seq]);
  if (zoneId == null)
    return (
      <EmptyState title="No zone selected">
        Click a zone on the map, or choose one from the list, to see its demand against the forecast.
      </EmptyState>
    );
  if (detail.error && !detail.data) return <ErrorState title="Could not load this zone" onRetry={detail.reload}>{detail.error.message}</ErrorState>;
  const d = detail.data;
  if (!d) return <LoadingSkeleton lines={4} height={220} />;
  const ratio = d.today_forecast > 0 ? d.today_actual / d.today_forecast : null;
  return (
    <div className="zone-detail">
      <header className="zone-detail-head">
        <div>
          <h3>{d.name}</h3>
          <p className="muted small">{d.sector} sector · zone {d.id}</p>
        </div>
        <button type="button" onClick={onClear}>Clear</button>
      </header>
      <dl className="facts">
        <div><dt>Today so far</dt><dd>{fmtInt(d.today_actual)}</dd></div>
        <div><dt>Forecast for the same hours</dt><dd>{fmtInt(d.today_forecast)}</dd></div>
        <div><dt>Ratio</dt><dd>{ratio == null ? "n/a" : `${(ratio * 100).toFixed(0)}%`}</dd></div>
        {value && <div><dt>This window</dt><dd>{fmtInt(value.actual)} vs {fmtInt(value.forecast)}</dd></div>}
      </dl>
      <ForecastPanel series={d.series} height={200} label={`${d.name}: simulated pickups and forecast`} />
      {d.events.length > 0 && (
        <>
          <h4>Events in this zone</h4>
          <ul className="events">
            {d.events.map((e) => (
              <EventItem key={e.id} event={e} />
            ))}
          </ul>
        </>
      )}
    </div>
  );
}
