import { useMemo, useState } from "react";
import { api, type ForecastPerformance, type Schemas } from "../api/client";
import { DataTable } from "../components/DataTable";
import { Async } from "../components/State";
import { BandChart } from "../components/Charts";
import { fmtNum, fmtPct } from "../lib/format";
import { useAsync } from "../lib/useAsync";

const LABELS: Record<string, string> = {
  lightgbm: "LightGBM (Poisson)",
  seasonal_mean_4w: "Seasonal mean (same weekday+hour, last 4 weeks)",
  seasonal_naive: "Seasonal naive (same weekday+hour, last week)",
  naive: "Naive (same hour yesterday)",
};
const ORDER = ["lightgbm", "seasonal_mean_4w", "seasonal_naive", "naive"];

function Performance({ perf }: { perf: ForecastPerformance }) {
  const rows = ORDER.filter((m) => perf.overall[m]).map((m) => ({ id: m, ...perf.overall[m]! }));
  const best = perf.best_baseline;
  const imp = perf.bootstrap.improvement[best];
  const o = perf.oracle_weather_experiment;
  return (
    <>
      <p>
        Held-out evaluation ({perf.data_label}): {perf.test_rows.toLocaleString("en-US")} zone-hours over {perf.test_days} days
        ({perf.data_days[1]} is the last day of data), walk-forward with the model refitted between folds; forecasts are made
        from midnight using only earlier days.
      </p>
      <DataTable
        caption="Forecast accuracy by model"
        rows={rows}
        rowKey={(r) => r.id}
        columns={[
          { key: "m", header: "Model", render: (r) => LABELS[r.id] ?? r.id },
          { key: "wape", header: "WAPE", numeric: true, render: (r) => fmtPct(r.wape) },
          { key: "mae", header: "MAE", numeric: true, render: (r) => fmtNum(r.mae, 2) },
          { key: "rmse", header: "RMSE", numeric: true, render: (r) => fmtNum(r.rmse, 2) },
          { key: "bias", header: "Bias", numeric: true, render: (r) => fmtPct(r.bias) },
        ]}
      />
      {imp && (
        <p>
          Against the strongest baseline ({LABELS[best] ?? best}), the model’s WAPE differs by{" "}
          {fmtNum(100 * imp.wape_point_difference, 1)} percentage points (95% bootstrap interval{" "}
          {fmtNum(100 * imp.difference_ci95[0], 1)} to {fmtNum(100 * imp.difference_ci95[1], 1)}); positive means the model is better.
        </p>
      )}
      <p>
        The {fmtPct(perf.interval.nominal, 0)} prediction intervals contained {fmtPct(perf.interval.overall.coverage)} of held-out values.
      </p>
      {o && (
        <p className="notice">
          <strong>ORACLE experiment, not a deployable result.</strong> {o.label} WAPE {fmtPct(o.wape_without_weather)} without weather
          versus {fmtPct(o.wape_with_oracle_weather)} with actual same-day weather.
        </p>
      )}
    </>
  );
}

function ZoneSelect({
  zones,
  value,
  onChange,
  city,
}: {
  zones: Schemas["Zone"][];
  value: number | undefined;
  onChange: (v: number | undefined) => void;
  city: boolean;
}) {
  return (
    <label>
      Zone
      <select value={value ?? ""} onChange={(e) => onChange(e.target.value ? Number(e.target.value) : undefined)}>
        {city && <option value="">City total</option>}
        {zones.map((z) => (
          <option key={z.location_id} value={z.location_id}>
            {z.zone} ({z.borough})
          </option>
        ))}
      </select>
    </label>
  );
}

export function Forecast({ zones }: { zones: Schemas["Zone"][] }) {
  const perf = useAsync((s) => api.forecastPerformance(s), []);
  const [nextZone, setNextZone] = useState<number | undefined>(undefined);
  const next = useAsync((s) => api.forecastNextDay({ zone_id: nextZone }, s), [nextZone]);

  const range = useMemo<[string, string] | null>(() => {
    const f = perf.data?.folds;
    return f && f.length ? [f[0]!.test_days[0], f[f.length - 1]!.test_days[1]] : null;
  }, [perf.data]);
  const [btZone, setBtZone] = useState<number>(zones[0]?.location_id ?? 1);
  const [btDate, setBtDate] = useState<string>("");
  const date = btDate || range?.[1] || "";
  const backtest = useAsync(
    (s) => (date ? api.forecastBacktest({ zone_id: btZone, date }, s) : Promise.reject(new Error("Choose a date."))),
    [btZone, date],
  );

  return (
    <>
      <section aria-labelledby="perf-h">
        <h2 id="perf-h">How accurate is the forecast?</h2>
        <Async state={perf} what="evaluation">{(p) => <Performance perf={p} />}</Async>
      </section>

      <section aria-labelledby="next-h">
        <h2 id="next-h">Forecast for the day after the data ends</h2>
        <form className="controls" onSubmit={(e) => e.preventDefault()} aria-label="Next-day forecast">
          <ZoneSelect zones={zones} value={nextZone} onChange={setNextZone} city />
        </form>
        <Async state={next} what="forecast">
          {(f) => (
            <>
              <p>
                {f.zone_name ?? "City total"} on {f.target_date} ({f.data_label}). {f.note}
              </p>
              <BandChart
                title={`Forecast for ${f.target_date}`}
                showActual={false}
                data={f.points.map((p) => ({ x: p.hour_ts.slice(11, 16), forecast: p.forecast, lo: p.lo ?? null, hi: p.hi ?? null }))}
              />
              <p className="muted small">
                Nominal interval coverage {fmtPct(f.nominal_coverage, 0)}; measured on held-out days:{" "}
                {fmtPct(f.empirical_coverage_in_evaluation)}. A forecast is an estimate from past patterns, not a guarantee.
              </p>
            </>
          )}
        </Async>
      </section>

      <section aria-labelledby="bt-h">
        <h2 id="bt-h">Past forecasts against actual demand</h2>
        <form className="controls" onSubmit={(e) => e.preventDefault()} aria-label="Backtest">
          <ZoneSelect zones={zones} value={btZone} onChange={(v) => setBtZone(v ?? btZone)} city={false} />
          <label>
            Day
            <input type="date" value={date} min={range?.[0]} max={range?.[1]} onChange={(e) => setBtDate(e.target.value)} />
          </label>
        </form>
        <Async state={backtest} what="backtest">
          {(b) => (
            <>
              <p>
                {b.zone_name}, {b.date}: {b.note}
              </p>
              <BandChart
                title={`Forecast vs actual, ${b.zone_name}, ${b.date}`}
                showActual
                data={b.points.map((p) => ({ x: p.hour_ts.slice(11, 16), forecast: p.forecast, lo: p.lo ?? null, hi: p.hi ?? null, actual: p.actual ?? null }))}
              />
            </>
          )}
        </Async>
      </section>
    </>
  );
}
