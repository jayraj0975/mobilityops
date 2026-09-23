import { useMemo, useState } from "react";
import { ApiError, api, type Schemas } from "../api/client";
import { DataTable } from "../components/DataTable";
import { Async, ErrorState } from "../components/State";
import { fmtInt, fmtNum, fmtPct } from "../lib/format";
import { useAsync } from "../lib/useAsync";

const NAMES: Record<string, string> = {
  no_repositioning: "No repositioning",
  plan_seasonal_mean: "Plan with the seasonal-mean forecast",
  plan_lightgbm: "Plan with the LightGBM forecast",
  plan_oracle: "Plan with the actual demand (unattainable upper bound)",
};

function Result({ r, zones }: { r: Schemas["ScenarioResponse"]; zones: Schemas["Zone"][] }) {
  void zones;
  const ok = r.status === "optimal" || r.status === "feasible_time_limit";
  return (
    <div aria-live="polite">
      <p className="banner banner-sim" role="note">
        <strong>{r.label}</strong>
      </p>
      <p>
        <span className={`badge badge-${ok ? "pass" : "warn"}`}>{r.status}</span> {r.message}
      </p>
      <div className="kpis">
        <div className="kpi">
          <span className="kpi-label">Served share without repositioning</span>
          <span className="kpi-value">{fmtPct(r.service_share_before, 2)}</span>
        </div>
        <div className="kpi">
          <span className="kpi-label">{ok ? "Served share with the plan" : "Best attainable"}</span>
          <span className="kpi-value">{fmtPct(ok ? r.service_share_after : r.best_attainable_service_share, 2)}</span>
        </div>
        <div className="kpi">
          <span className="kpi-label">Vehicles moved</span>
          <span className="kpi-value">{fmtInt(r.vehicles_moved)}</span>
          <span className="muted small">of {fmtInt(r.fleet)} assumed vehicles; {fmtNum(r.km_total, 0)} km driven empty</span>
        </div>
      </div>
      <h3>Assumptions this result depends on</h3>
      <DataTable
        caption="Simulation assumptions"
        rows={Object.entries(r.assumptions)}
        rowKey={(e) => e[0]}
        columns={[
          { key: "k", header: "Assumption", render: (e) => e[0].replace(/_/g, " ") },
          { key: "v", header: "Value", render: (e) => String(e[1] ?? "none") },
        ]}
      />
      {r.moves.length > 0 && (
        <>
          <h3>Largest moves</h3>
          <DataTable
            caption="Repositioning moves"
            rows={r.moves}
            rowKey={(m) => `${m.from_zone}-${m.to_zone}`}
            columns={[
              { key: "n", header: "Vehicles", numeric: true, render: (m) => fmtInt(m.vehicles) },
              { key: "f", header: "From", render: (m) => m.from_name },
              { key: "t", header: "To", render: (m) => m.to_name },
              { key: "km", header: "Distance (km)", numeric: true, render: (m) => fmtNum(m.km, 2) },
            ]}
          />
        </>
      )}
    </div>
  );
}

export function Scenarios({ zones }: { zones: Schemas["Zone"][] }) {
  const perf = useAsync((s) => api.forecastPerformance(s), []);
  const bt = useAsync((s) => api.optimizationBacktest(s), []);
  const range = useMemo<[string, string] | null>(() => {
    const f = perf.data?.folds;
    return f && f.length ? [f[0]!.test_days[0], f[f.length - 1]!.test_days[1]] : null;
  }, [perf.data]);

  const [day, setDay] = useState("");
  const [startHour, setStartHour] = useState(17);
  const [endHour, setEndHour] = useState(20);
  const [coverage, setCoverage] = useState(0.85);
  const [minService, setMinService] = useState("");
  const [surgeZone, setSurgeZone] = useState("");
  const [surgeFactor, setSurgeFactor] = useState(1.5);
  const [result, setResult] = useState<Schemas["ScenarioResponse"] | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [busy, setBusy] = useState(false);
  const date = day || range?.[1] || "";

  async function run() {
    setBusy(true);
    setError(null);
    try {
      const body: Schemas["ScenarioRequest"] = {
        date,
        start_hour: startHour,
        end_hour: endHour,
        coverage,
        min_service_share: minService ? Number(minService) / 100 : null,
        demand_multipliers: surgeZone ? { [surgeZone]: surgeFactor } : {},
      };
      setResult(await api.scenario(body));
    } catch (e) {
      setResult(null);
      setError(e instanceof Error ? e : new Error(String(e)));
    } finally {
      setBusy(false);
    }
  }

  const hourInvalid = endHour <= startHour;
  return (
    <>
      <p className="banner banner-sim" role="note">
        Everything on this page is a <strong>SIMULATED SCENARIO under explicit assumptions</strong>. No fleet data exist, so
        supply, vehicle capacity and costs are assumptions; results are not predictions of real-world outcomes.
      </p>

      <section aria-labelledby="run-h">
        <h2 id="run-h">Run a what-if</h2>
        <form
          className="controls"
          onSubmit={(e) => {
            e.preventDefault();
            if (!hourInvalid && date) void run();
          }}
          aria-label="Scenario"
        >
          <label>
            Day (forecast evaluation days only)
            <input type="date" value={date} min={range?.[0]} max={range?.[1]} onChange={(e) => setDay(e.target.value)} required />
          </label>
          <label>
            From hour
            <input type="number" min={0} max={23} value={startHour} onChange={(e) => setStartHour(Number(e.target.value))} />
          </label>
          <label>
            To hour
            <input type="number" min={1} max={24} value={endHour} onChange={(e) => setEndHour(Number(e.target.value))} />
          </label>
          <label>
            Fleet capacity / expected demand
            <input type="number" step={0.05} min={0.3} max={1.5} value={coverage} onChange={(e) => setCoverage(Number(e.target.value))} />
          </label>
          <label>
            Required served share (%), optional
            <input type="number" min={1} max={100} value={minService} onChange={(e) => setMinService(e.target.value)} placeholder="none" />
          </label>
          <label>
            Demand shock in zone, optional
            <select value={surgeZone} onChange={(e) => setSurgeZone(e.target.value)}>
              <option value="">None</option>
              {zones.map((z) => (
                <option key={z.location_id} value={z.location_id}>
                  {z.zone}
                </option>
              ))}
            </select>
          </label>
          {surgeZone && (
            <label>
              Shock factor
              <input type="number" step={0.1} min={0} max={5} value={surgeFactor} onChange={(e) => setSurgeFactor(Number(e.target.value))} />
            </label>
          )}
          <button type="submit" disabled={busy || hourInvalid || !date}>
            {busy ? "Solving…" : "Run simulation"}
          </button>
        </form>
        {hourInvalid && <p role="alert" className="notice notice-error">The end hour must be after the start hour.</p>}
        {error && (
          <ErrorState error={error instanceof ApiError && error.code === "busy" ? new Error("The solver is busy; try again in a moment.") : error} />
        )}
        {result && <Result r={result} zones={zones} />}
      </section>

      <section aria-labelledby="bt-h">
        <h2 id="bt-h">Backtest: would a better forecast improve the plan?</h2>
        <Async state={bt} what="backtest">
          {(b) => (
            <>
              <p className="banner banner-sim" role="note">{b.label}</p>
              <p>{b.design}</p>
              <DataTable
                caption="Served share by planner"
                rows={Object.entries(b.planners)}
                rowKey={(e) => e[0]}
                columns={[
                  { key: "p", header: "Planner", render: (e) => NAMES[e[0]] ?? e[0] },
                  { key: "s", header: "Served share", numeric: true, render: (e) => fmtPct(e[1].served_share, 2) },
                  { key: "m", header: "Vehicles moved / window", numeric: true, render: (e) => fmtInt(e[1].vehicles_moved_per_window) },
                ]}
              />
              <p>
                LightGBM plan vs no repositioning: {fmtNum(100 * b.lightgbm_vs_none.point, 2)} percentage points (95% interval{" "}
                {fmtNum(100 * b.lightgbm_vs_none.ci95[0], 2)} to {fmtNum(100 * b.lightgbm_vs_none.ci95[1], 2)}). LightGBM plan vs
                seasonal-mean plan: {fmtNum(100 * b.lightgbm_vs_seasonal_mean_planning.point, 2)} points. Over {b.windows_scored} day-windows.
              </p>
            </>
          )}
        </Async>
      </section>
    </>
  );
}
