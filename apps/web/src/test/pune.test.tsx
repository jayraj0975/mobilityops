import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { centroidOf, layerPaint, makeProjection, ratioColor, rampColor, ringPath } from "../pune/mapGeometry";
import { connectionNotice } from "../pune/PuneApp";
import { ageText, clock, instant } from "../pune/time";
import { streamReducer, type StreamState } from "../pune/usePuneStream";
import type { EventItemData, Geometry, MapLayer, Snapshot, SourceState, TimeSelector, ZoneValue } from "../pune/types";
import { DataSourceStatus, EmptyState, ErrorState, EventItem, FilterBar, FreshnessIndicator, MapPanel, MetricCard, StatusBadge, TimeRangeSelector } from "../ui";

const zone = (id: number, over: Partial<ZoneValue> = {}): ZoneValue => ({
  id, actual: 100, forecast: 100, lo: 80, hi: 120, ratio: 1, z: 0, status: "normal", event_id: null, ...over,
});
const geometry: Geometry = {
  city: "Pune", bbox: [18.4, 73.7, 18.68, 74.02], attribution: "© OpenStreetMap contributors (ODbL 1.0)", licence: "ODbL", method: "m",
  zones: [
    { id: 1, name: "Kothrud", sector: "West", lat: 18.5, lon: 73.8, area_km2: 5, ring: [[73.7, 18.4], [73.9, 18.4], [73.9, 18.6], [73.7, 18.6]] },
    { id: 2, name: "Baner", sector: "North-West", lat: 18.56, lon: 73.78, area_km2: 4, ring: [[73.9, 18.4], [74.02, 18.4], [74.02, 18.68], [73.9, 18.68]] },
  ],
};
const source = (over: Partial<SourceState> = {}): SourceState => ({
  key: "open-meteo-forecast", label: "Weather now", provider: "Open-Meteo", data_class: "NEAR-REAL-TIME", modelled: true, licence: "CC BY 4.0",
  note: "n", enabled: true, freshness: "LIVE", interval_s: 900, age_s: 120, consecutive_failures: 0, runs: 3, successes: 3, records_total: 100, ...over,
});

describe("time helpers", () => {
  it("says how old something is in plain words", () => {
    expect(ageText(0)).toBe("just now");
    expect(ageText(42)).toBe("42 s ago");
    expect(ageText(300)).toBe("5 min ago");
    expect(ageText(3 * 3600)).toBe("3 h ago");
    expect(ageText(3 * 86400)).toBe("over a day ago");
    expect(ageText(null)).toBe("never");
    expect(ageText(-5)).toBe("just now");
  });
  it("reads clock times as written and instants only when valid", () => {
    expect(clock("2026-09-24T21:17:25")).toBe("21:17");
    expect(clock("nonsense")).toBe("nonsense");
    expect(instant("2026-09-24T15:47:00Z")).toBe(Date.parse("2026-09-24T15:47:00Z"));
    expect(instant("x")).toBeNull();
    expect(instant(null)).toBeNull();
  });
});

describe("map geometry and colour", () => {
  it("projects the study box into a 1000-wide picture with north up", () => {
    const p = makeProjection(geometry.bbox);
    expect(p.width).toBe(1000);
    expect(p.height).toBeGreaterThan(900);
    const [x0, y0] = p.xy(73.7, 18.68);
    const [x1, y1] = p.xy(74.02, 18.4);
    expect([x0, y0]).toEqual([0, 0]);
    expect(x1).toBeCloseTo(1000);
    expect(y1).toBeCloseTo(p.height);
    expect(ringPath(geometry.zones[0]!.ring, p)).toMatch(/^M[\d.,]+L[\d.,]+L[\d.,]+L[\d.,]+Z$/);
  });
  it("colours below-forecast blue and above-forecast orange, clamped", () => {
    expect(ratioColor(0.2)).toBe(ratioColor(0.5));
    expect(ratioColor(3)).toBe(ratioColor(1.5));
    const [rb] = ratioColor(0.5).match(/\d+/g)!.map(Number);
    const [ro] = ratioColor(1.5).match(/\d+/g)!.map(Number);
    expect(rb).toBeLessThan(ro!);
    expect(ratioColor(1)).not.toBe(ratioColor(1.3));
    expect(rampColor(0, 0)).toBe(rampColor(0, 10));
    expect(rampColor(10, 10)).not.toBe(rampColor(0, 10));
  });
  it("leaves zones without a ratio unpainted and flags events by direction", () => {
    const ratio = layerPaint("ratio", []);
    expect(ratio.fill(zone(1, { ratio: null }))).toBe("var(--zone-idle)");
    expect(ratio.fill(undefined)).toBe("var(--zone-idle)");
    expect(ratio.fill(zone(1, { forecast: 0.2, ratio: 3 }))).toBe("var(--zone-idle)"); // too little to judge
    const ev = layerPaint("events", []);
    expect(ev.fill(zone(1))).toBe("var(--zone-idle)");
    expect(ev.fill(zone(1, { status: "surge" }))).not.toBe(ev.fill(zone(1, { status: "drop" })));
    const demand = layerPaint("demand", [zone(1, { actual: 400 })]);
    expect(demand.legend.right).toContain("400");
  });
  it("finds a zone's centroid", () => {
    expect(centroidOf(geometry, 2)).toEqual([73.78, 18.56]);
    expect(centroidOf(geometry, 99)).toBeNull();
  });
});

describe("the stream reducer", () => {
  const base: StreamState = { link: "connecting", offsetMs: 0 };
  const snap = (seq: number, at = "2026-09-24T15:47:00Z") => ({ seq, server_time: at }) as Snapshot;
  it("takes the first snapshot from hello and corrects for a wrong local clock", () => {
    const s = streamReducer(base, { type: "hello", snapshot: snap(1), serverTime: "2026-09-24T15:47:10Z", available: true, at: Date.parse("2026-09-24T15:47:00Z") });
    expect(s.link).toBe("live");
    expect(s.snapshot?.seq).toBe(1);
    expect(s.offsetMs).toBe(10_000);
  });
  it("says so when there is no worker instead of inventing data", () => {
    const s = streamReducer(base, { type: "hello", snapshot: null, serverTime: "2026-09-24T15:47:10Z", available: false, at: 1 });
    expect(s.unavailable).toBe(true);
    expect(s.snapshot).toBeUndefined();
  });
  it("keeps the last snapshot while reconnecting, and heartbeats do not replace it", () => {
    let s = streamReducer(base, { type: "snapshot", snapshot: snap(5), at: 100 });
    s = streamReducer(s, { type: "status", status: "reconnecting", message: "lost" });
    expect(s.link).toBe("reconnecting");
    expect(s.snapshot?.seq).toBe(5);
    s = streamReducer(s, { type: "heartbeat", serverTime: "2026-09-24T15:47:20Z", worker: "STALE", at: 200 });
    expect(s.snapshot?.seq).toBe(5);
    expect(s.workerFresh).toBe("STALE");
    expect(s.lastMessageAt).toBe(200);
    expect(s.snapshotAt).toBe(100);
  });
});

describe("connection notices", () => {
  it("is silent when all is well and honest otherwise", () => {
    expect(connectionNotice("live", "LIVE", "LIVE", "21:17")).toBeNull();
    expect(connectionNotice("connecting", undefined, undefined, null)).toBeNull();
    expect(connectionNotice("offline", "LIVE", "LIVE", "21:17")).toContain("offline");
    expect(connectionNotice("reconnecting", "LIVE", "LIVE", "21:17")).toMatch(/out of date/);
    expect(connectionNotice("reconnecting", "LIVE", "LIVE", "21:17")).toContain("21:17");
    expect(connectionNotice("live", "LIVE", "OFFLINE", null)).toContain("worker has stopped");
    expect(connectionNotice("live", "STALE", "LIVE", null)).toContain("stopped updating");
  });
});

describe("design-system components", () => {
  it("badges pair a glyph with a word so colour is never the only cue", () => {
    render(<StatusBadge tone="bad">FAILED</StatusBadge>);
    expect(screen.getByText("FAILED").parentElement?.textContent).toMatch(/▲\s*FAILED/);
  });
  it("shows freshness with its age only where an age means something", () => {
    const { rerender } = render(<FreshnessIndicator state="LIVE" ageSeconds={120} />);
    expect(screen.getByText(/LIVE/).parentElement?.textContent).toContain("2 min ago");
    rerender(<FreshnessIndicator state="DISABLED" ageSeconds={5} />);
    expect(screen.getByText("NOT CONFIGURED")).toBeInTheDocument();
    expect(screen.queryByText(/ago/)).toBeNull();
    rerender(<FreshnessIndicator state="STALE" ageSeconds={7200} />);
    expect(screen.getByText(/STALE/).parentElement?.textContent).toContain("2 h ago");
  });
  it("metric cards label their data class", () => {
    render(<MetricCard label="Forecast" value="1,255" kind="PREDICTED" note="range" delta="+4% vs forecast" deltaTone="up" freshness="LIVE" ageSeconds={3} />);
    const card = screen.getByRole("article", { name: "Forecast" });
    expect(card).toHaveTextContent("PREDICTED");
    expect(card).toHaveTextContent("+4% vs forecast");
    expect(card).toHaveTextContent("1,255");
  });
  it("SIMULATED is never labelled modelled-on-top and modelled sources say so", () => {
    render(<><MetricCard label="a" value="1" kind="SIMULATED" modelled /><MetricCard label="b" value="2" kind="NEAR-REAL-TIME" modelled /></>);
    expect(screen.getByRole("article", { name: "a" })).not.toHaveTextContent("MODELLED");
    expect(screen.getByRole("article", { name: "b" })).toHaveTextContent("MODELLED");
  });
  it("time selector is a radio group over the six choices", () => {
    const onChange = vi.fn();
    function Harness() {
      const [v, setV] = useState<TimeSelector>("now");
      return <TimeRangeSelector value={v} onChange={(x) => { onChange(x); setV(x); }} />;
    }
    render(<Harness />);
    expect(screen.getAllByRole("radio")).toHaveLength(6);
    expect(screen.getByRole("radio", { name: "NOW" })).toBeChecked();
    fireEvent.click(screen.getByRole("radio", { name: "FORECAST" }));
    expect(onChange).toHaveBeenCalledWith("forecast");
    expect(screen.getByRole("radio", { name: "FORECAST" })).toBeChecked();
  });
  it("filter bar reports changes by id", () => {
    const onChange = vi.fn();
    render(<FilterBar filters={[{ id: "sev", label: "Severity", value: "", options: [{ value: "", label: "Any" }, { value: "high", label: "High" }] }]} onChange={onChange} />);
    fireEvent.change(screen.getByLabelText("Severity"), { target: { value: "high" } });
    expect(onChange).toHaveBeenCalledWith("sev", "high");
  });
  it("empty and error states announce themselves; error offers a retry", () => {
    const retry = vi.fn();
    render(<><EmptyState title="Nothing yet">soon</EmptyState><ErrorState title="Broke" onRetry={retry}>why</ErrorState></>);
    expect(screen.getByRole("status")).toHaveTextContent("Nothing yet");
    expect(screen.getByRole("alert")).toHaveTextContent("Broke");
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(retry).toHaveBeenCalled();
  });
  it("source table shows the failure run and what is not connected", () => {
    render(
      <DataSourceStatus
        sources={[
          source({ freshness: "STALE", consecutive_failures: 3, last_error: "HTTP 503", age_s: 4000 }),
          source({ key: "tomtom", label: "Road traffic flow", enabled: false, freshness: "DISABLED", disabled_reason: "no TOMTOM_API_KEY configured", interval_s: 300, age_s: null }),
        ]}
      />,
    );
    expect(screen.getByText(/3 failed polls in a row: HTTP 503/)).toBeInTheDocument();
    expect(screen.getByText("NOT CONFIGURED")).toBeInTheDocument();
    expect(screen.getByText(/no TOMTOM_API_KEY configured/)).toBeInTheDocument();
  });
  it("the strip form hides what is not connected", () => {
    render(<DataSourceStatus variant="strip" sources={[source(), source({ key: "x", label: "Hidden", enabled: false, freshness: "DISABLED" })]} />);
    expect(screen.getByText("Weather now")).toBeInTheDocument();
    expect(screen.queryByText("Hidden")).toBeNull();
  });
  it("an event describes a departure from the forecast and offers the zone", () => {
    const onSelect = vi.fn();
    const e: EventItemData = {
      id: "e1", zone_id: 5, zone: "Kothrud", kind: "surge", severity: "high", start: "2026-09-24T19:00:00", end: "2026-09-24T21:00:00",
      actual: 300, expected: 120, score: 11.5, detected_at: "2026-09-24T15:40:00Z", explanation: "no cause claimed", data_class: "SIMULATED",
    };
    render(<ul><EventItem event={e} onSelect={onSelect} /></ul>);
    expect(screen.getByText("HIGH")).toBeInTheDocument();
    expect(screen.getByText(/2\.5×/)).toBeInTheDocument();
    expect(screen.getByText("SIMULATED")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Kothrud" }));
    expect(onSelect).toHaveBeenCalledWith(5);
  });
});

describe("the map panel", () => {
  function Harness({ layer = "ratio" as MapLayer }) {
    const [sel, setSel] = useState<number | null>(null);
    const [l, setL] = useState<MapLayer>(layer);
    return <MapPanel geometry={geometry} values={[zone(1, { actual: 250, forecast: 200, ratio: 1.25 }), zone(2, { status: "surge" })]} layer={l} onLayerChange={setL} selectedId={sel} onSelect={setSel} />;
  }
  it("selects a zone by click, by the keyboard route, and reads its numbers", () => {
    const { container } = render(<Harness />);
    expect(container.querySelectorAll("path.zone")).toHaveLength(2);
    fireEvent.click(container.querySelector('path[data-zone="1"]')!);
    expect(container.querySelector("path.zone-sel")).not.toBeNull();
    expect(screen.getByText(/pickups 250/)).toBeInTheDocument();
    expect(screen.getByText(/125% of forecast/)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Zone"), { target: { value: "2" } });
    expect(screen.getByText(/SURGE/)).toBeInTheDocument();
    fireEvent.click(container.querySelector('path[data-zone="2"]')!); // clicking the selected zone clears it
    expect(container.querySelector("path.zone-sel")).toBeNull();
  });
  it("changes layer and always credits OpenStreetMap", () => {
    render(<Harness />);
    fireEvent.change(screen.getByLabelText("Layer"), { target: { value: "events" } });
    expect(screen.getByText("surge")).toBeInTheDocument();
    expect(screen.getByText(/OpenStreetMap contributors/)).toBeInTheDocument();
    expect(screen.getByRole("img")).toHaveAccessibleName(/keyboard route/);
  });
});
