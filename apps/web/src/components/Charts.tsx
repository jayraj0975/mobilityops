import {
  Area,
  Bar,
  BarChart,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { DataTable, type Column } from "./DataTable";

const C = {
  main: "var(--series-1)",
  second: "var(--series-2)",
  third: "var(--series-3)",
  band: "var(--band)",
  grid: "var(--grid)",
  text: "var(--muted)",
};

type Row = Record<string, string | number | null>;

/** A chart with a text alternative: the same numbers as a table, one click away. */
function Figure({
  title,
  summary,
  table,
  columns,
  children,
}: {
  title: string;
  summary: string;
  table: Row[];
  columns: Column<Row>[];
  children: React.ReactNode;
}) {
  return (
    <figure className="figure">
      <figcaption>
        <strong>{title}</strong>
        <span className="muted small"> {summary}</span>
      </figcaption>
      <div className="chart" role="img" aria-label={`${title}. ${summary}`}>
        <ResponsiveContainer width="100%" height={260}>
          {children as React.ReactElement}
        </ResponsiveContainer>
      </div>
      <details>
        <summary>View data as a table</summary>
        <DataTable
          caption={`${title} (data)`}
          columns={columns}
          rows={table.slice(0, 200)}
          rowKey={(r) => String(r.x)}
        />
        {table.length > 200 && <p className="muted small">Showing the first 200 rows.</p>}
      </details>
    </figure>
  );
}

const cols = (x: string, ...ys: [string, string][]): Column<Row>[] => [
  { key: "x", header: x, render: (r) => String(r.x) },
  ...ys.map(([k, h]): Column<Row> => ({
    key: k,
    header: h,
    numeric: true,
    render: (r) => (r[k] == null ? "n/a" : Number(r[k]).toLocaleString("en-US", { maximumFractionDigits: 1 })),
  })),
];

export function SeriesChart({
  title,
  xLabel,
  data,
  yLabel = "pickups",
}: {
  title: string;
  xLabel: string;
  data: { x: string; y: number }[];
  yLabel?: string;
}) {
  const peak = data.reduce((m, d) => (d.y > m.y ? d : m), data[0] ?? { x: "", y: 0 });
  return (
    <Figure
      title={title}
      summary={`${data.length} points; highest ${Math.round(peak.y).toLocaleString("en-US")} at ${peak.x}.`}
      table={data.map((d) => ({ x: d.x, y: d.y }))}
      columns={cols(xLabel, ["y", yLabel])}
    >
      <LineChart data={data} margin={{ top: 8, right: 16, bottom: 8, left: 8 }}>
        <CartesianGrid stroke={C.grid} strokeDasharray="3 3" />
        <XAxis dataKey="x" tick={{ fill: C.text, fontSize: 12 }} minTickGap={32} />
        <YAxis tick={{ fill: C.text, fontSize: 12 }} width={56} />
        <Tooltip />
        <Line isAnimationActive={false} type="monotone" dataKey="y" name={yLabel} stroke={C.main} dot={false} strokeWidth={2} />
      </LineChart>
    </Figure>
  );
}

export function BandChart({
  title,
  data,
  showActual,
}: {
  title: string;
  data: { x: string; forecast: number; lo: number | null; hi: number | null; actual?: number | null }[];
  showActual: boolean;
}) {
  const rows = data.map((d) => ({
    ...d,
    band: d.lo != null && d.hi != null ? ([d.lo, d.hi] as [number, number]) : null,
  }));
  return (
    <Figure
      title={title}
      summary={`${data.length} hours; shaded band is the model's interval.`}
      table={data.map((d) => ({ x: d.x, forecast: d.forecast, lo: d.lo, hi: d.hi, actual: d.actual ?? null }))}
      columns={cols("Hour", ["forecast", "Forecast"], ["lo", "Interval low"], ["hi", "Interval high"], ...(showActual ? ([["actual", "Actual"]] as [string, string][]) : []))}
    >
      <ComposedChart data={rows} margin={{ top: 8, right: 16, bottom: 8, left: 8 }}>
        <CartesianGrid stroke={C.grid} strokeDasharray="3 3" />
        <XAxis dataKey="x" tick={{ fill: C.text, fontSize: 12 }} />
        <YAxis tick={{ fill: C.text, fontSize: 12 }} width={56} />
        <Tooltip />
        <Legend />
        <Area isAnimationActive={false} dataKey="band" name="Interval" stroke="none" fill={C.band} fillOpacity={0.5} />
        <Line isAnimationActive={false} dataKey="forecast" name="Forecast" stroke={C.main} dot={false} strokeWidth={2} />
        {showActual && (
          <Line isAnimationActive={false} dataKey="actual" name="Actual" stroke={C.second} strokeDasharray="5 3" dot={false} strokeWidth={2} />
        )}
      </ComposedChart>
    </Figure>
  );
}

export function BarsChart({
  title,
  data,
  yLabel,
}: {
  title: string;
  data: { x: string; y: number }[];
  yLabel: string;
}) {
  return (
    <Figure
      title={title}
      summary={`${data.length} bars.`}
      table={data.map((d) => ({ x: d.x, y: d.y }))}
      columns={cols("Item", ["y", yLabel])}
    >
      <BarChart data={data} margin={{ top: 8, right: 16, bottom: 8, left: 8 }}>
        <CartesianGrid stroke={C.grid} strokeDasharray="3 3" />
        <XAxis dataKey="x" tick={{ fill: C.text, fontSize: 12 }} interval={0} angle={-25} textAnchor="end" height={80} />
        <YAxis tick={{ fill: C.text, fontSize: 12 }} width={56} />
        <Tooltip />
        <Bar isAnimationActive={false} dataKey="y" name={yLabel} fill={C.main} />
      </BarChart>
    </Figure>
  );
}

const SHARE_COLORS = [C.main, C.second, C.third];

/** Stacked bars of shares that sum to 100% per bar, with the numbers available as a table. */
export function ShareBarsChart({
  title,
  data,
  series,
}: {
  title: string;
  data: { x: string; shares: Record<string, number> }[];
  series: { key: string; label: string }[];
}) {
  const rows = data.map((d) => ({ x: d.x, ...Object.fromEntries(series.map((s) => [s.key, 100 * (d.shares[s.key] ?? 0)])) }));
  return (
    <Figure
      title={title}
      summary={`${data.length} bars, each split into ${series.map((s) => s.label).join(", ")}.`}
      table={rows}
      columns={cols("Period", ...series.map((s): [string, string] => [s.key, `${s.label} (%)`]))}
    >
      <BarChart data={rows} margin={{ top: 8, right: 16, bottom: 8, left: 8 }}>
        <CartesianGrid stroke={C.grid} strokeDasharray="3 3" />
        <XAxis dataKey="x" tick={{ fill: C.text, fontSize: 12 }} minTickGap={16} />
        <YAxis tick={{ fill: C.text, fontSize: 12 }} width={56} domain={[0, 100]} unit="%" />
        <Tooltip formatter={(v) => `${Number(v).toFixed(1)}%`} />
        <Legend />
        {series.map((s, i) => (
          <Bar key={s.key} isAnimationActive={false} stackId="share" dataKey={s.key} name={s.label} fill={SHARE_COLORS[i % SHARE_COLORS.length]} />
        ))}
      </BarChart>
    </Figure>
  );
}
