import { useState } from "react";
import { api, type Schemas } from "../api/client";
import { Async, Empty } from "../components/State";
import { fmtDateTime, fmtInt, fmtNum } from "../lib/format";
import { useAsync } from "../lib/useAsync";

const PAGE = 10;

function Card({ e }: { e: Schemas["AnomalyItem"] }) {
  return (
    <li className="card">
      <h3>
        {e.zone} <span className="muted">({e.borough})</span>
      </h3>
      <p>
        <span className={`badge badge-sev-${e.severity}`}>{e.severity} severity</span>{" "}
        <span className="badge">{e.direction}</span> <span className="badge">{e.scope}</span>
      </p>
      <p>
        {fmtDateTime(e.start)} to {fmtDateTime(e.end)}: {fmtInt(e.actual)} pickups against a forecast of {fmtInt(e.forecast)}
        {e.ratio != null && ` (${fmtNum(e.ratio, 1)}x)`}; event score {fmtNum(e.event_z, 1)}.
      </p>
      <p>{e.explanation}</p>
    </li>
  );
}

export function Anomalies() {
  const [severity, setSeverity] = useState("");
  const [direction, setDirection] = useState("");
  const [offset, setOffset] = useState(0);
  const summary = useAsync((s) => api.anomalySummary(s), []);
  const page = useAsync(
    (s) => api.anomalies({ severity: severity || undefined, direction: direction || undefined, limit: PAGE, offset }, s),
    [severity, direction, offset],
  );
  const reset = <T,>(set: (v: T) => void) => (v: T) => {
    set(v);
    setOffset(0);
  };

  return (
    <>
      <section aria-labelledby="as-h">
        <h2 id="as-h">Summary</h2>
        <Async state={summary} what="anomaly summary">
          {(a) => (
            <>
              <p>
                {a.events_total} events over {a.scored_days[0]} to {a.scored_days[1]} ({fmtNum(a.events_per_1000_zone_days, 1)} per 1,000
                zone-days). By severity: {Object.entries(a.by_severity).map(([k, v]) => `${k} ${v}`).join(", ")}. By direction:{" "}
                {Object.entries(a.by_direction).map(([k, v]) => `${k} ${v}`).join(", ")}.
              </p>
              <p className="notice">
                <strong>Accuracy status:</strong> {a.accuracy_status}. Explanations list what coincided with a deviation; they do
                not establish a cause. Only out-of-sample days can be scored, and drops are harder to detect than surges.
              </p>
              {a.busiest_days && a.busiest_days.length > 0 && (
                <p className="muted small">
                  Days with the most events (one city-wide disruption can produce many events):{" "}
                  {a.busiest_days.slice(0, 4).map((d) => `${d.date} (${d.events})`).join(", ")}.
                </p>
              )}
            </>
          )}
        </Async>
      </section>

      <section aria-labelledby="al-h">
        <h2 id="al-h">Events, largest first</h2>
        <form className="controls" onSubmit={(e) => e.preventDefault()} aria-label="Anomaly filters">
          <label>
            Severity
            <select value={severity} onChange={(e) => reset(setSeverity)(e.target.value)}>
              <option value="">Any</option>
              <option value="high">High</option>
              <option value="medium">Medium</option>
              <option value="low">Low</option>
            </select>
          </label>
          <label>
            Direction
            <select value={direction} onChange={(e) => reset(setDirection)(e.target.value)}>
              <option value="">Any</option>
              <option value="surge">Surge</option>
              <option value="drop">Drop</option>
            </select>
          </label>
        </form>
        <Async state={page} what="events">
          {(p) =>
            p.items.length === 0 ? (
              <Empty>No events match these filters.</Empty>
            ) : (
              <>
                <p aria-live="polite">
                  Showing {p.offset + 1} to {p.offset + p.items.length} of {p.total}.
                </p>
                <ul className="cards">
                  {p.items.map((e) => (
                    <Card key={e.event_id} e={e} />
                  ))}
                </ul>
                <div className="pager">
                  <button type="button" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))}>
                    Previous
                  </button>
                  <button type="button" disabled={offset + PAGE >= p.total} onClick={() => setOffset(offset + PAGE)}>
                    Next
                  </button>
                </div>
              </>
            )
          }
        </Async>
      </section>
    </>
  );
}
