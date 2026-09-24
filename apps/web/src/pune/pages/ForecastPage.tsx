import { api, state } from "../../api/client";
import { fmtInt, fmtPct } from "../../lib/format";
import { useAsync } from "../../lib/useAsync";
import { ChartPanel, ErrorState, ForecastPanel, LoadingSkeleton, StatusBadge } from "../../ui";
import { usePune } from "../PuneContext";
import { ageText } from "../time";

/** The forecast, its range, how it made, and how good it has been on held-out days. */
export function ForecastPage() {
  const p = usePune();
  const s = p.snapshot;
  const city = useAsync((sig) => state.series({ back: 48, ahead: 24 }, sig), [p.seq]);
  const perf = useAsync((sig) => api.forecastPerformance(sig), []);
  const made = s?.forecast_made_at ? Date.parse(s.forecast_made_at) : null;
  const overall = perf.data?.overall;
  const best = perf.data ? perf.data.best_baseline : null;
  return (
    <div className="stack">
      <ChartPanel
        title="City forecast"
        subtitle="Simulated pickups against the day-ahead forecast and its range"
        kind="PREDICTED"
        footer={city.data?.envelope_note}
      >
        {city.error && !city.data ? (
          <ErrorState title="Could not load the forecast" onRetry={city.reload}>{city.error.message}</ErrorState>
        ) : city.data ? (
          <ForecastPanel series={city.data.series} height={300} label="City: simulated pickups and forecast" />
        ) : (
          <LoadingSkeleton lines={4} height={300} />
        )}
      </ChartPanel>
      <div className="two-col">
        <ChartPanel title="This forecast" kind="PREDICTED">
          <dl className="facts facts-col">
            <div><dt>Model</dt><dd>{s?.forecast_model ?? "not available"}</dd></div>
            <div><dt>Made</dt><dd>{made ? ageText((p.now - made) / 1000) : "not yet"}</dd></div>
            <div><dt>Horizon</dt><dd>Today, from data up to yesterday (day-ahead)</dd></div>
            <div><dt>Range</dt><dd>80% conformal interval per zone-hour</dd></div>
          </dl>
          <p className="small muted">
            The model uses yesterday, last week and calendar features (including Maharashtra holidays). It does not see
            the weather, so on a dry day after rainy ones it forecasts too high. That gap is visible in the chart above
            and is a real limitation of this model.
          </p>
        </ChartPanel>
        <ChartPanel title="How accurate has it been?" subtitle="Walk-forward test on held-out days" kind="SIMULATED">
          {perf.error && !perf.data ? (
            <ErrorState title="No evaluation yet" onRetry={perf.reload}>{perf.error.message}</ErrorState>
          ) : perf.data && overall ? (
            <>
              <div className="table-wrap">
                <table className="ops-table">
                  <caption className="sr-only">Forecast error by model</caption>
                  <thead>
                    <tr><th scope="col">Model</th><th scope="col" className="num">WAPE</th><th scope="col" className="num">MAE</th></tr>
                  </thead>
                  <tbody>
                    {Object.entries(overall).map(([name, m]) => (
                      <tr key={name}>
                        <th scope="row">{name}{name === "lightgbm" ? "" : name === best ? " (best baseline)" : ""}</th>
                        <td className="num">{fmtPct(m.wape)}</td>
                        <td className="num">{m.mae == null ? "n/a" : m.mae.toFixed(2)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="small">
                <StatusBadge tone="info">80% range</StatusBadge> held {fmtPct(perf.data.interval.overall.coverage)} of{" "}
                {fmtInt(perf.data.interval.overall.n)} zone-hours ({perf.data.test_days} test days).
              </p>
              <p className="small muted">
                These errors are measured on simulated demand. They show that the pipeline works; they say nothing about
                how well it would forecast real Pune traffic.
              </p>
            </>
          ) : (
            <LoadingSkeleton lines={4} />
          )}
        </ChartPanel>
      </div>
    </div>
  );
}
