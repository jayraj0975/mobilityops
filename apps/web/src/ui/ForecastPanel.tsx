import {
  Area,
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { fmtInt } from "../lib/format";
import { clock } from "../pune/time";

export interface SeriesRow {
  hour: string;
  actual: number | null;
  forecast: number | null;
  lo: number | null;
  hi: number | null;
  partial: boolean;
}

/**
 * Simulated demand against the forecast and its 80% range. The running hour is pro-rated, so the
 * actual line ends at the current moment; the forecast continues to the end of the day.
 * The same numbers are available as a table for anyone who cannot use the chart.
 */
export function ForecastPanel({
  series,
  height = 260,
  label,
}: {
  series: SeriesRow[];
  height?: number;
  label: string;
}) {
  const rows = series.map((p) => ({
    t: clock(p.hour),
    hour: p.hour,
    actual: p.actual,
    forecast: p.forecast,
    range: p.lo != null && p.hi != null ? [p.lo, p.hi] : null,
    partial: p.partial,
  }));
  const now = rows.find((r) => r.partial)?.t;
  const summary = `${rows.length} hours; simulated pickups against the forecast and its 80% range.`;
  return (
    <div>
      <div className="chart" role="img" aria-label={`${label}. ${summary}`}>
        <ResponsiveContainer width="100%" height={height}>
          <ComposedChart data={rows} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
            <CartesianGrid stroke="var(--grid)" strokeDasharray="3 3" />
            <XAxis dataKey="t" stroke="var(--muted)" tick={{ fontSize: 11 }} interval="preserveStartEnd" minTickGap={28} />
            <YAxis stroke="var(--muted)" tick={{ fontSize: 11 }} width={44} />
            <Tooltip
              contentStyle={{ background: "var(--surface-2)", border: "1px solid var(--border)", color: "var(--text)" }}
              formatter={(v: unknown) => (Array.isArray(v) ? `${fmtInt(v[0])} to ${fmtInt(v[1])}` : fmtInt(Number(v)))}
            />
            <Area dataKey="range" name="Forecast range (80%)" stroke="none" fill="var(--band)" fillOpacity={0.45} isAnimationActive={false} />
            <Line dataKey="forecast" name="Forecast" stroke="var(--series-forecast)" strokeWidth={2} strokeDasharray="6 4" dot={false} isAnimationActive={false} />
            <Line dataKey="actual" name="Simulated pickups" stroke="var(--series-actual)" strokeWidth={2.5} dot={false} connectNulls={false} isAnimationActive={false} />
            {now && <ReferenceLine x={now} stroke="var(--muted)" strokeDasharray="2 2" label={{ value: "now", fill: "var(--muted)", fontSize: 11 }} />}
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      <ul className="legend" aria-hidden="true">
        <li><span className="swatch swatch-actual" /> Simulated pickups</li>
        <li><span className="swatch swatch-forecast" /> Forecast</li>
        <li><span className="swatch swatch-band" /> 80% range</li>
      </ul>
      <details>
        <summary>View data as a table</summary>
        <div className="table-wrap">
          <table className="ops-table">
            <caption className="sr-only">{label}</caption>
            <thead>
              <tr>
                <th scope="col">Hour</th>
                <th scope="col" className="num">Simulated pickups</th>
                <th scope="col" className="num">Forecast</th>
                <th scope="col" className="num">Range low</th>
                <th scope="col" className="num">Range high</th>
              </tr>
            </thead>
            <tbody>
              {series.map((p) => (
                <tr key={p.hour}>
                  <th scope="row">{clock(p.hour)}{p.partial ? " (so far)" : ""}</th>
                  <td className="num">{fmtInt(p.actual)}</td>
                  <td className="num">{fmtInt(p.forecast)}</td>
                  <td className="num">{fmtInt(p.lo)}</td>
                  <td className="num">{fmtInt(p.hi)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </div>
  );
}
