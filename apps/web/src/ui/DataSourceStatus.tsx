import { DataClassTag } from "./DataClassTag";
import { FreshnessIndicator } from "./FreshnessIndicator";
import type { SourceState } from "../pune/types";

/** Every data source with its class, licence and freshness; ``strip`` is the compact form. */
export function DataSourceStatus({
  sources,
  elapsedSeconds = 0,
  variant = "table",
}: {
  sources: SourceState[];
  /** Seconds since the snapshot arrived: ages keep counting between updates. */
  elapsedSeconds?: number;
  variant?: "strip" | "table";
}) {
  const age = (s: SourceState) => (s.age_s == null ? null : s.age_s + elapsedSeconds);
  if (variant === "strip") {
    return (
      <ul className="src-strip" aria-label="Data sources">
        {sources
          .filter((s) => s.enabled && s.freshness !== "NOT_PERIODIC")
          .map((s) => (
            <li key={s.key}>
              <span className="src-name">{s.label}</span>
              <FreshnessIndicator state={s.freshness} ageSeconds={age(s)} />
            </li>
          ))}
      </ul>
    );
  }
  return (
    <div className="table-wrap">
      <table className="ops-table">
        <caption className="sr-only">Data sources and their freshness</caption>
        <thead>
          <tr>
            <th scope="col">Source</th>
            <th scope="col">Class</th>
            <th scope="col">Freshness</th>
            <th scope="col">Expected</th>
            <th scope="col">Licence</th>
            <th scope="col">Notes</th>
          </tr>
        </thead>
        <tbody>
          {sources.map((s) => (
            <tr key={s.key}>
              <th scope="row">
                {s.label}
                <span className="muted small"> {s.provider}</span>
              </th>
              <td>
                <DataClassTag kind={s.data_class} modelled={s.modelled} />
              </td>
              <td>
                <FreshnessIndicator state={s.freshness} ageSeconds={age(s)} />
                {s.consecutive_failures > 0 && (
                  <p className="small bad-text">
                    {s.consecutive_failures} failed {s.consecutive_failures === 1 ? "poll" : "polls"} in a row
                    {s.last_error ? `: ${s.last_error}` : ""}
                  </p>
                )}
              </td>
              <td className="small">{s.interval_s ? `every ${s.interval_s >= 3600 ? `${s.interval_s / 3600} h` : s.interval_s >= 60 ? `${s.interval_s / 60} min` : `${s.interval_s} s`}` : "n/a"}</td>
              <td className="small">{s.licence}</td>
              <td className="small">{s.enabled ? s.note : `${s.disabled_reason ?? "Not connected"}. ${s.note}`}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
