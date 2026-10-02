import { state } from "../api/client";
import { useAsync } from "../lib/useAsync";
import { fmtInt, fmtPct } from "../lib/format";
import type { RepositioningScenario } from "../pune/types";

/** RECOMMENDED: a simulated repositioning scenario for one event, fetched lazily when opened. */
export function EventImpactPanel({ eventId, open }: { eventId: string; open: boolean }) {
  const impact = useAsync(
    (s) => (open ? state.eventImpact(eventId, s) : Promise.resolve(undefined)),
    [open, eventId],
  );
  if (!open) return null;
  if (impact.error) return <p className="small muted">Could not load a response scenario: {impact.error.message}</p>;
  if (!impact.data) return <p className="small muted">Loading a response scenario…</p>;
  const scenario = impact.data.scenario as RepositioningScenario | null;
  if (!scenario) {
    return <p className="small muted">No other zone lies within repositioning range of this event.</p>;
  }
  return (
    <div className="impact-panel">
      <p className="small muted">{scenario.label}</p>
      {scenario.status === "infeasible" || scenario.status === "no_solution" ? (
        <p className="small">{scenario.message}</p>
      ) : (
        <>
          <p className="small">
            PREDICTED: without repositioning, {fmtPct(scenario.service_share_before)} of demand
            across the nearby zones would be served ({fmtInt(scenario.served_before)} of{" "}
            {fmtInt(scenario.demand_total)} trips, {scenario.fleet} vehicles assumed).
          </p>
          {scenario.moves.length === 0 ? (
            <p className="small">RECOMMENDED: no repositioning move improves on that under these assumptions.</p>
          ) : (
            <>
              <p className="small">
                RECOMMENDED: move {scenario.vehicles_moved} vehicle{scenario.vehicles_moved === 1 ? "" : "s"}{" "}
                ({fmtInt(scenario.km_total)} km total) to reach {fmtPct(scenario.service_share_after)} served.
              </p>
              <ul className="small">
                {scenario.moves.map((m, i) => (
                  <li key={i}>
                    Zone {m.from_zone} → zone {m.to_zone}: {m.vehicles} vehicle{m.vehicles === 1 ? "" : "s"} ({m.km} km)
                  </li>
                ))}
              </ul>
            </>
          )}
        </>
      )}
    </div>
  );
}
