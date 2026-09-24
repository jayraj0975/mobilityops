import { state } from "../../api/client";
import { fmtInt, fmtPct } from "../../lib/format";
import { useAsync } from "../../lib/useAsync";
import { ChartPanel, DataSourceStatus, ErrorState, FreshnessIndicator, LoadingSkeleton, StatusBadge } from "../../ui";
import { usePune } from "../PuneContext";
import { ageText } from "../time";

/** Data quality: what was checked, how each source is behaving, and the state of this connection. */
export function QualityPage() {
  const p = usePune();
  const q = useAsync((s) => state.quality(s), [p.seq]);
  const viewers = useAsync(async (s) => {
    const r = await fetch("/api/v1/state/stream/status", { signal: s });
    return r.ok ? ((await r.json()) as { streams: number; max_streams: number; dropped_events: number }) : null;
  }, [p.seq]);
  if (q.error && !q.data) return <ErrorState title="Could not load data quality" onRetry={q.reload}>{q.error.message}</ErrorState>;
  const d = q.data;
  if (!d) return <LoadingSkeleton lines={6} height={300} />;
  const db = d.database;
  const worker = p.snapshot?.worker;
  const lastMsg = p.stream.lastMessageAt ? (p.now - p.stream.lastMessageAt) / 1000 : null;
  return (
    <div className="stack">
      <div className="two-col">
        <ChartPanel title="Analytical database" subtitle="The history behind the forecast" kind="SIMULATED">
          {db.available ? (
            <>
              <dl className="facts facts-col">
                <div><dt>Built</dt><dd>{db.built_at_utc}</dd></div>
                <div><dt>Window</dt><dd>{db.window_start} to {db.window_end} (end exclusive)</dd></div>
                <div><dt>Days behind today</dt><dd>{db.days_behind} (the worker simulates the gap, then forecasts today)</dd></div>
                <div><dt>Trips</dt><dd>{fmtInt(db.rows_valid)} (simulated)</dd></div>
              </dl>
              <div className="table-wrap">
                <table className="ops-table">
                  <caption className="sr-only">Quality checks on the latest build</caption>
                  <thead><tr><th scope="col">Check</th><th scope="col">Status</th><th scope="col">Detail</th></tr></thead>
                  <tbody>
                    {db.checks.map((c) => (
                      <tr key={c.check}>
                        <th scope="row">{c.check}</th>
                        <td><StatusBadge tone={c.status === "PASS" ? "ok" : c.status === "WARN" ? "warn" : "bad"}>{c.status}</StatusBadge></td>
                        <td className="small">{c.message}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          ) : (
            <p>No database has been built. Run <code>pune-build</code>.</p>
          )}
        </ChartPanel>
        <ChartPanel title="This connection" subtitle="Server-sent events diagnostics">
          <dl className="facts facts-col">
            <div><dt>Link</dt><dd>{p.stream.link}{p.stream.message ? `: ${p.stream.message}` : ""}</dd></div>
            <div><dt>Last message</dt><dd>{ageText(lastMsg)}</dd></div>
            <div><dt>Newest snapshot</dt><dd>{ageText(p.elapsed)}</dd></div>
            <div><dt>Store version</dt><dd>{p.seq}</dd></div>
            <div><dt>Clock offset (server minus this device)</dt><dd>{(p.stream.offsetMs / 1000).toFixed(1)} s</dd></div>
            <div><dt>Ingestion worker</dt><dd>{worker ? <FreshnessIndicator state={worker.freshness} ageSeconds={worker.age_s ? worker.age_s + p.elapsed : null} /> : "unknown"}</dd></div>
            <div><dt>Viewers</dt><dd>{viewers.data ? `${viewers.data.streams} of ${viewers.data.max_streams} allowed (${viewers.data.dropped_events} events dropped for slow viewers)` : "n/a"}</dd></div>
          </dl>
        </ChartPanel>
      </div>
      <ChartPanel title="Source health, last 24 hours" subtitle="From the ingestion run log">
        <div className="table-wrap">
          <table className="ops-table">
            <caption className="sr-only">Source health</caption>
            <thead>
              <tr>
                <th scope="col">Source</th><th scope="col">Freshness</th><th scope="col" className="num">Runs</th>
                <th scope="col" className="num">Success</th><th scope="col" className="num">Rejected records</th>
                <th scope="col" className="num">Mean time</th><th scope="col">Last error</th>
              </tr>
            </thead>
            <tbody>
              {d.health.filter((h) => h.runs_24h > 0 || h.freshness === "DISABLED").map((h) => (
                <tr key={h.key}>
                  <th scope="row">{h.label}</th>
                  <td><FreshnessIndicator state={h.freshness} showAge={false} /></td>
                  <td className="num">{h.runs_24h}</td>
                  <td className="num">{fmtPct(h.success_rate_24h, 0)}</td>
                  <td className="num">{h.rejected_records_24h}</td>
                  <td className="num">{h.mean_duration_ms == null ? "n/a" : `${Math.round(h.mean_duration_ms)} ms`}</td>
                  <td className="small">{h.last_error ?? ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </ChartPanel>
      <ChartPanel title="Sources" subtitle="What each one is, its licence, and whether it is connected">
        <DataSourceStatus sources={d.sources} elapsedSeconds={p.elapsed} />
      </ChartPanel>
      <ChartPanel title="Recent ingestion runs" subtitle="Newest first">
        <div className="table-wrap">
          <table className="ops-table">
            <caption className="sr-only">Recent ingestion runs</caption>
            <thead><tr><th scope="col">Finished</th><th scope="col">Source</th><th scope="col">Result</th><th scope="col" className="num">Records</th><th scope="col" className="num">Time</th></tr></thead>
            <tbody>
              {d.runs.map((r) => (
                <tr key={r.id}>
                  <td className="small">{r.finished_at.replace("T", " ").replace("Z", "").slice(0, 19)}</td>
                  <th scope="row">{r.source}</th>
                  <td>{r.ok ? <StatusBadge tone="ok">OK</StatusBadge> : <StatusBadge tone="bad">FAILED</StatusBadge>}{r.error && <span className="small"> {r.error}</span>}</td>
                  <td className="num">{r.records_ok} of {r.records_in}</td>
                  <td className="num">{r.duration_ms} ms</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </ChartPanel>
      <ul className="plain notes">{d.notes.map((n) => <li key={n} className="small muted">{n}</li>)}</ul>
    </div>
  );
}
