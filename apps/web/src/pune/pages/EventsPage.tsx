import { useMemo, useState } from "react";
import { state } from "../../api/client";
import { useAsync } from "../../lib/useAsync";
import { Anomalies } from "../../pages/Anomalies";
import { ChartPanel, EmptyState, ErrorState, EventItem, FilterBar, LoadingSkeleton } from "../../ui";
import { usePune } from "../PuneContext";

/** Live events (today) and, below, the batch detector's anomalies over the held-out period. */
export function EventsPage() {
  const p = usePune();
  const events = useAsync((s) => state.events(100, s), [p.seq]);
  const [sev, setSev] = useState("");
  const [kind, setKind] = useState("");
  const shown = useMemo(
    () => (events.data ?? []).filter((e) => (!sev || e.severity === sev) && (!kind || e.kind === kind)),
    [events.data, sev, kind],
  );
  return (
    <div className="stack">
      <ChartPanel
        title="Live events"
        subtitle="Runs of hours where simulated demand left the forecast (rule-based, today)"
        kind="SIMULATED"
        footer="An event is at least two consecutive completed hours whose pooled deviation reaches 5σ, at least 1.5× (or at most 0.6×) the forecast, on at least 30 forecast trips. It describes a departure from the forecast; it does not explain it."
      >
        <FilterBar
          filters={[
            { id: "sev", label: "Severity", value: sev, options: [{ value: "", label: "Any" }, { value: "high", label: "High" }, { value: "medium", label: "Medium" }, { value: "low", label: "Low" }] },
            { id: "kind", label: "Direction", value: kind, options: [{ value: "", label: "Any" }, { value: "surge", label: "Surge" }, { value: "drop", label: "Drop" }] },
          ]}
          onChange={(id, v) => (id === "sev" ? setSev(v) : setKind(v))}
        />
        {events.error && !events.data ? (
          <ErrorState title="Could not load events" onRetry={events.reload}>{events.error.message}</ErrorState>
        ) : !events.data ? (
          <LoadingSkeleton lines={3} />
        ) : shown.length === 0 ? (
          <EmptyState title={events.data.length === 0 ? "No events so far today" : "No events match these filters"}>
            {events.data.length === 0 ? "Demand has stayed within its forecast range for long enough to count." : undefined}
          </EmptyState>
        ) : (
          <ul className="events">
            {shown.map((e) => (
              <EventItem key={e.id} event={e} onSelect={(id) => { p.setZoneId(id); window.location.hash = "/overview"; }} />
            ))}
          </ul>
        )}
      </ChartPanel>
      <section aria-label="Batch detector">
        <h2>Batch detector, held-out period</h2>
        <Anomalies />
      </section>
    </div>
  );
}
