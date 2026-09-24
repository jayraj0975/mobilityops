import { fmtInt } from "../lib/format";
import { clock } from "../pune/time";
import type { EventItemData } from "../pune/types";
import { DataClassTag } from "./DataClassTag";
import { StatusBadge, type Tone } from "./StatusBadge";

const SEV: Record<string, Tone> = { low: "info", medium: "warn", high: "bad" };

/** One detected event. It describes a departure from the forecast, never a cause. */
export function EventItem({
  event,
  onSelect,
  selected = false,
}: {
  event: EventItemData;
  onSelect?: (zoneId: number) => void;
  selected?: boolean;
}) {
  const ratio = event.expected > 0 ? event.actual / event.expected : null;
  return (
    <li className={selected ? "event event-on" : "event"}>
      <header>
        <StatusBadge tone={SEV[event.severity] ?? "neutral"}>{event.severity.toUpperCase()}</StatusBadge>
        <strong>{event.kind === "surge" ? "Surge" : "Drop"}</strong>
        {onSelect ? (
          <button type="button" className="linkish" onClick={() => onSelect(event.zone_id)}>
            {event.zone}
          </button>
        ) : (
          <span>{event.zone}</span>
        )}
        <span className="muted small">
          {clock(event.start)} to {clock(event.end)}
        </span>
        <DataClassTag kind={event.data_class} />
      </header>
      <p className="small">
        {fmtInt(event.actual)} pickups against a forecast of {fmtInt(event.expected)}
        {ratio != null ? ` (${ratio.toFixed(1)}×)` : ""}; deviation {event.score > 0 ? "+" : ""}
        {event.score.toFixed(1)} σ.
      </p>
      <details>
        <summary className="small">Explanation</summary>
        <p className="small muted">{event.explanation}</p>
      </details>
    </li>
  );
}
