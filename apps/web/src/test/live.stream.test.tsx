import { act, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { liveReducer, type LiveState } from "../lib/useLiveStream";
import { parseSse } from "../lib/sse";
import { Live, ageText } from "../pages/Live";
import type { Hello, ReplayTick } from "../lib/live";

const tick = (index: number, extra: Partial<ReplayTick> = {}): ReplayTick => ({
  kind: "replay",
  label: "REPLAY of held-out days 2024-11-06 to 2024-12-31: forecasts made before those days. Not live taxi data.",
  index,
  of: 1344,
  loop: 0,
  hour_ts: `2024-11-06T${String(index % 24).padStart(2, "0")}:00:00`,
  actual: 1000 + index,
  forecast: 950 + index,
  baseline: 900 + index,
  abs_error: 50,
  running_wape: 0.187,
  top_zones: [{ location_id: 132, zone: "JFK Airport", actual: 120, forecast: 110 }],
  anomalies: [],
  ...extra,
});

const citibike = (over: object = {}) => ({
  kind: "feed",
  feed: "citibike",
  status: "ok",
  source: "Citi Bike GBFS feed",
  as_of: new Date(Date.now() - 20_000).toISOString(),
  fetched_at: new Date().toISOString(),
  error: null,
  data: {
    stations: 2300, active: 2200, offline: 100, bikes: 21000, ebikes: 5200, docks: 30000, empty: 180, full: 95,
    largest_empty: [{ name: "Broadway & W 60 St", capacity: 60, bikes: 0, docks: 60 }],
    largest_full: [],
  },
  ...over,
});
const weather = {
  kind: "feed", feed: "weather", status: "ok", source: "National Weather Service", as_of: new Date().toISOString(), fetched_at: new Date().toISOString(), error: null,
  data: { description: "Mostly Cloudy", temperature_c: 21.7, wind_kmh: null, humidity_pct: 63, precipitation_last_hour_mm: 0, station: "KNYC (Central Park)" },
};

const hello = (extra: Partial<Hello> = {}): Hello =>
  ({
    kind: "hello",
    server_time: new Date().toISOString(),
    data_label: "real data",
    replay: { available: true, label: tick(0).label, start: "2024-11-06T00:00:00", end: "2024-12-31T00:00:00", ticks: 1344, seconds_per_hour: 2, loop_seconds: 2688, history: [tick(0), tick(1)] },
    feeds: { enabled: true, citibike: citibike() as never, weather: weather as never, history: [] },
    ...extra,
  }) as Hello;

const sse = (event: string, body: unknown) => `event: ${event}\ndata: ${JSON.stringify(body)}\n\n`;

/** A streaming Response that delivers the chunks, then stays open (or closes). */
function streamResponse(chunks: string[], close = false): Response {
  const enc = new TextEncoder();
  const body = new ReadableStream<Uint8Array>({
    start(c) {
      for (const ch of chunks) c.enqueue(enc.encode(ch));
      if (close) c.close();
    },
  });
  return new Response(body, { status: 200, headers: { "Content-Type": "text/event-stream" } });
}

describe("parseSse", () => {
  it("returns complete events and keeps the unfinished tail", () => {
    const a = parseSse('event: replay\ndata: {"a":1}\n\nevent: fe');
    expect(a.events).toEqual([{ event: "replay", data: '{"a":1}' }]);
    expect(a.rest).toBe("event: fe");
    const b = parseSse(a.rest + 'ed\ndata: {"b":2}\n\n');
    expect(b.events).toEqual([{ event: "feed", data: '{"b":2}' }]);
  });
  it("ignores keep-alive comments, joins multi-line data and accepts CRLF", () => {
    const r = parseSse(": keep-alive\n\nevent: x\r\ndata: one\r\ndata: two\r\n\r\n");
    expect(r.events).toEqual([{ event: "x", data: "one\ntwo" }]);
  });
  it("does not emit an event with no data", () => {
    expect(parseSse("event: empty\n\n").events).toEqual([]);
  });
});

describe("liveReducer", () => {
  const empty: LiveState = { status: "connecting", ticks: [], history: [] };
  it("takes the replay history and feeds from hello and marks the stream live", () => {
    const s = liveReducer(empty, { type: "hello", hello: hello() });
    expect(s.status).toBe("live");
    expect(s.ticks.map((t) => t.index)).toEqual([0, 1]);
    expect(s.citibike?.data?.bikes).toBe(21000);
  });
  it("appends ticks, drops a duplicate after a reconnect and restarts the series on wrap-around", () => {
    let s = liveReducer(empty, { type: "hello", hello: hello() });
    s = liveReducer(s, { type: "replay", tick: tick(2) });
    s = liveReducer(s, { type: "replay", tick: tick(2) });
    expect(s.ticks.map((t) => t.index)).toEqual([0, 1, 2]);
    s = liveReducer(s, { type: "replay", tick: tick(0, { loop: 1 }) });
    expect(s.ticks.map((t) => t.index)).toEqual([0]);
  });
  it("keeps at most 96 ticks", () => {
    let s = empty;
    for (let i = 0; i < 200; i++) s = liveReducer(s, { type: "replay", tick: tick(i) });
    expect(s.ticks).toHaveLength(96);
    expect(s.ticks.at(-1)?.index).toBe(199);
  });
});

describe("ageText", () => {
  it("speaks in seconds, minutes and hours, and admits an unknown time", () => {
    const now = Date.parse("2026-09-24T12:00:00Z");
    expect(ageText("2026-09-24T11:59:30Z", now)).toBe("30 s ago");
    expect(ageText("2026-09-24T11:55:00Z", now)).toBe("5 min ago");
    expect(ageText("2026-09-24T09:00:00Z", now)).toBe("3 h ago");
    expect(ageText(null, now)).toBe("time unknown");
  });
});

describe("Live page", () => {
  beforeEach(() => vi.useFakeTimers({ shouldAdvanceTime: true }));
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("labels the replay as a replay and the feeds as live, and shows both", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => streamResponse([sse("hello", hello()), sse("replay", tick(2))])));
    render(<Live />);
    expect(await screen.findByText("REPLAY, NOT LIVE.")).toBeInTheDocument();
    expect(screen.getByText("LIVE.")).toBeInTheDocument();
    expect(await screen.findByText("Connected: receiving live updates")).toBeInTheDocument();
    expect(await screen.findByText(/hour 3 of 1344/)).toBeInTheDocument();
    expect(screen.getByText("21,000")).toBeInTheDocument(); // bikes available
    expect(screen.getByText(/5,200 of them e-bikes/)).toBeInTheDocument();
    expect(screen.getByText("21.7 °C")).toBeInTheDocument();
    expect(screen.getByText("n/a")).toBeInTheDocument(); // wind was missing: never invented
    const zones = screen.getByRole("region", { name: "Busiest zones this hour" });
    expect(within(zones).getByText("JFK Airport")).toBeInTheDocument();
    expect(screen.getByText(/Source: Citi Bike GBFS feed/)).toBeInTheDocument();
  });

  it("says when a feed is down and that the numbers shown are the last good reading", async () => {
    const down = citibike({ status: "unavailable", error: "HTTPStatusError: 503" });
    const h = hello({ feeds: { enabled: true, citibike: down as never, weather: weather as never, history: [] } });
    vi.stubGlobal("fetch", vi.fn(async () => streamResponse([sse("hello", h)])));
    render(<Live />);
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("not answering right now");
    expect(alert).toHaveTextContent("last good reading, not current");
  });

  it("explains an unavailable replay and a server with live feeds switched off", async () => {
    const h = hello({ replay: { available: false, reason: "no forecast predictions yet; run `forecast-eval`" }, feeds: { enabled: false } });
    vi.stubGlobal("fetch", vi.fn(async () => streamResponse([sse("hello", h)])));
    render(<Live />);
    expect(await screen.findByText(/replay is not available yet: no forecast predictions yet/)).toBeInTheDocument();
    expect(screen.getByText(/Live feeds are switched off/)).toBeInTheDocument();
  });

  it("reconnects after the stream drops, and tells the viewer while it does", async () => {
    let calls = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        calls += 1;
        return calls === 1 ? streamResponse([sse("hello", hello())], true) : streamResponse([sse("hello", hello()), sse("replay", tick(7))]);
      }),
    );
    render(<Live />);
    expect(await screen.findByText(/Connection lost: reconnecting/)).toBeInTheDocument();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1100);
    });
    expect(await screen.findByText("Connected: receiving live updates")).toBeInTheDocument();
    expect(await screen.findByText(/hour 8 of 1344/)).toBeInTheDocument();
    expect(calls).toBe(2);
  });

  it("shows the server's own reason when the stream is refused", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response(JSON.stringify({ error: { code: "busy", message: "32 live streams are already open" } }), { status: 429 })),
    );
    render(<Live />);
    expect(await screen.findByText(/32 live streams are already open/)).toBeInTheDocument();
  });
});
