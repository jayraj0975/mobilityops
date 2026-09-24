import type { Schemas } from "../api/client";
import { api } from "../api/client";
import { useAsync } from "../lib/useAsync";
import { fmtInt, fmtPct } from "../lib/format";
import { DataTable } from "./DataTable";
import { ShareBarsChart } from "./Charts";
import { Async, Empty } from "./State";

/** Yellow taxis, green taxis and for-hire vehicles side by side; only shown when the data has them. */
export function ServiceMix({ meta, zone }: { meta: Schemas["Meta"]; zone?: number }) {
  const start = meta.data_start.slice(0, 10);
  const end = meta.data_end.slice(0, 10);
  const monthly = useAsync((s) => api.serviceMix({ start, end, zone_id: zone, grain: "month" }, s), [start, end, zone]);
  const total = useAsync((s) => api.serviceMix({ start, end, zone_id: zone, grain: "total" }, s), [start, end, zone]);

  return (
    <section aria-labelledby="svc-h">
      <h2 id="svc-h">Yellow taxis, green taxis and for-hire vehicles</h2>
      <p className="muted">
        Share of the pickups counted in the three TLC files (yellow taxis, green taxis, and high-volume
        for-hire vehicles such as Uber and Lyft). It is not the share of all mobility in the city:
        subways, buses, private cars and the older for-hire files are not here. Cleaned pickups only;
        the same cleaning rules were applied to each service.
      </p>
      <Async state={total} what="service totals">
        {(rows) =>
          rows.length === 0 ? (
            <Empty>No data for this selection.</Empty>
          ) : (
            <DataTable
              caption="Pickups by service for the whole period"
              rows={rows}
              rowKey={(r) => r.service}
              columns={[
                { key: "label", header: "Service", render: (r) => r.label },
                { key: "pickups", header: "Pickups", numeric: true, render: (r) => fmtInt(r.pickups) },
                { key: "share", header: "Share", numeric: true, render: (r) => fmtPct(r.share) },
              ]}
            />
          )
        }
      </Async>
      <Async state={monthly} what="service mix by month">
        {(rows) => {
          const series = (meta.services ?? []).map((s) => ({ key: s.service, label: s.label }));
          const months = [...new Set(rows.map((r) => r.period.slice(0, 7)))];
          const data = months.map((m) => ({
            x: m,
            shares: Object.fromEntries(rows.filter((r) => r.period.slice(0, 7) === m).map((r) => [r.service, r.share])),
          }));
          return <ShareBarsChart title="Share of pickups by month" data={data} series={series} />;
        }}
      </Async>
    </section>
  );
}
