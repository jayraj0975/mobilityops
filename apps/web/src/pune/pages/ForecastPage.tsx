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
  const track = useAsync((sig) => state.trackRecord(14, sig), [p.seq]);
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
                how well it would forecast real {p.cityName} traffic.
              </p>
            </>
          ) : (
            <LoadingSkeleton lines={4} />
          )}
        </ChartPanel>
      </div>
      <ChartPanel
        title="Track record"
        subtitle="Each published forecast against the demand that followed, last 14 days"
        kind="SIMULATED"
        footer={track.data?.note}
      >
        {track.error && !track.data ? (
          <ErrorState title="Could not load the track record" onRetry={track.reload}>{track.error.message}</ErrorState>
        ) : !track.data ? (
          <LoadingSkeleton lines={4} />
        ) : track.data.days.length === 0 ? (
          <p className="small muted">
            Nothing scored yet. A forecast is scored once the hours it was made for have passed, and only if it was made
            before they began{track.data.excluded_late ? ` (${fmtInt(track.data.excluded_late)} zone-hours were forecast after the fact and are left out)` : ""}.
          </p>
        ) : (
          <>
            <div className="table-wrap">
              <table className="ops-table">
                <caption className="sr-only">Forecast error by day against a same-hour-last-week baseline</caption>
                <thead>
                  <tr>
                    <th scope="col">Day</th><th scope="col" className="num">Zone-hours</th><th scope="col" className="num">MAE</th>
                    <th scope="col" className="num">Last week's MAE</th><th scope="col" className="num">80% range held</th>
                    <th scope="col" className="num">Bias</th>
                  </tr>
                </thead>
                <tbody>
                  {[...track.data.days].reverse().map((d) => (
                    <tr key={String(d.day)}>
                      <th scope="row">{new Date(`${d.day}T00:00`).toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short" })}</th>
                      <td className="num">{fmtInt(d.zone_hours)}</td>
                      <td className="num">{d.mae.toFixed(2)}</td>
                      <td className="num">{d.baseline_mae == null ? "n/a" : d.baseline_mae.toFixed(2)}</td>
                      <td className="num">{fmtPct(d.coverage)}</td>
                      <td className="num">{d.bias > 0 ? "+" : ""}{d.bias.toFixed(2)}</td>
                    </tr>
                  ))}
                  {track.data.total && (
                    <tr className="total">
                      <th scope="row">{track.data.days.length} day{track.data.days.length === 1 ? "" : "s"}</th>
                      <td className="num">{fmtInt(track.data.total.zone_hours)}</td>
                      <td className="num">{track.data.total.mae.toFixed(2)}</td>
                      <td className="num">{track.data.total.baseline_mae == null ? "n/a" : track.data.total.baseline_mae.toFixed(2)}</td>
                      <td className="num">{fmtPct(track.data.total.coverage)}</td>
                      <td className="num">{track.data.total.bias > 0 ? "+" : ""}{track.data.total.bias.toFixed(2)}</td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
            <p className="small muted">
              MAE is the average miss in pickups per zone-hour; "last week" repeats the same zone and hour seven days
              earlier, scored on the same zone-hours. Bias above zero means the forecast ran high. Median lead time{" "}
              {track.data.total ? `${track.data.total.lead_hours_median} hours` : "n/a"}
              {track.data.excluded_late ? `; ${fmtInt(track.data.excluded_late)} zone-hours forecast after they began were left out` : ""}.
            </p>
          </>
        )}
      </ChartPanel>
    </div>
  );
}
