import { useEffect, useReducer } from "react";
import { authHeaders } from "../api/key";
import { parseSse } from "./sse";
import type { CitibikeData, Feed, HistoryPoint, Hello, ReplayTick, WeatherData } from "./live";

export type LiveStatus = "connecting" | "live" | "reconnecting";

export interface LiveState {
  status: LiveStatus;
  hello?: Hello;
  ticks: ReplayTick[];
  citibike?: Feed<CitibikeData>;
  weather?: Feed<WeatherData>;
  history: HistoryPoint[];
  message?: string;
}

const MAX_TICKS = 96;
const SILENCE_MS = 45_000; // the server sends a keep-alive every 15 s; three misses means the link died

type Action =
  | { type: "status"; status: LiveStatus; message?: string }
  | { type: "hello"; hello: Hello }
  | { type: "replay"; tick: ReplayTick }
  | { type: "feed"; feed: Feed<CitibikeData> | Feed<WeatherData> }
  | { type: "history"; points: HistoryPoint[] };

export function liveReducer(state: LiveState, a: Action): LiveState {
  switch (a.type) {
    case "status":
      return { ...state, status: a.status, message: a.message };
    case "hello": {
      const h = a.hello;
      const feeds = h.feeds.enabled ? h.feeds : undefined;
      return {
        ...state,
        status: "live",
        message: undefined,
        hello: h,
        ticks: h.replay.available ? h.replay.history.slice(-MAX_TICKS) : [],
        citibike: feeds?.citibike,
        weather: feeds?.weather,
        history: feeds?.history ?? [],
      };
    }
    case "replay": {
      // A reconnect can replay the tick we already hold; a wrap-around restarts the series.
      const last = state.ticks[state.ticks.length - 1];
      const restarted = last !== undefined && a.tick.index < last.index;
      const base = restarted ? [] : state.ticks.filter((t) => t.index !== a.tick.index);
      return { ...state, ticks: [...base, a.tick].slice(-MAX_TICKS) };
    }
    case "feed":
      return a.feed.feed === "citibike"
        ? { ...state, citibike: a.feed as Feed<CitibikeData> }
        : { ...state, weather: a.feed as Feed<WeatherData> };
    case "history":
      return { ...state, history: a.points };
  }
}

const sleep = (ms: number, signal: AbortSignal) =>
  new Promise<void>((resolve) => {
    const t = setTimeout(resolve, ms);
    signal.addEventListener("abort", () => { clearTimeout(t); resolve(); }, { once: true });
  });

/**
 * Follow the live stream with automatic reconnection (1 s, doubling to 30 s). ``fetch`` streaming is
 * used instead of ``EventSource`` so a request header (the API key) could be sent, and so the
 * connection can be watched for silence and restarted.
 */
export function useLiveStream(url = "/api/v1/live/stream"): LiveState {
  const [state, dispatch] = useReducer(liveReducer, { status: "connecting", ticks: [], history: [] });

  useEffect(() => {
    const stop = new AbortController();
    void (async () => {
      let delay = 1000;
      let attempt = 0;
      while (!stop.signal.aborted) {
        const link = new AbortController();
        const abortLink = () => link.abort();
        stop.signal.addEventListener("abort", abortLink, { once: true });
        let watchdog: ReturnType<typeof setTimeout> | undefined;
        const arm = () => {
          clearTimeout(watchdog);
          watchdog = setTimeout(() => link.abort(), SILENCE_MS);
        };
        try {
          dispatch({ type: "status", status: attempt === 0 ? "connecting" : "reconnecting" });
          attempt += 1;
          arm();
          const res = await fetch(url, { signal: link.signal, headers: { Accept: "text/event-stream", ...authHeaders() } });
          if (!res.ok || !res.body) {
            let detail = `The server answered HTTP ${res.status}.`;
            try {
              const body = (await res.json()) as { error?: { message?: string } };
              if (body.error?.message) detail = body.error.message;
            } catch {
              /* keep the generic message */
            }
            throw new Error(detail);
          }
          delay = 1000;
          const reader = res.body.getReader();
          const decoder = new TextDecoder();
          let buffer = "";
          for (;;) {
            const { done, value } = await reader.read();
            if (done) break;
            arm();
            buffer += decoder.decode(value, { stream: true });
            const parsed = parseSse(buffer);
            buffer = parsed.rest;
            for (const ev of parsed.events) {
              const body = JSON.parse(ev.data) as Record<string, unknown>;
              if (ev.event === "hello") dispatch({ type: "hello", hello: body as unknown as Hello });
              else if (ev.event === "replay") dispatch({ type: "replay", tick: body as unknown as ReplayTick });
              else if (ev.event === "feed") dispatch({ type: "feed", feed: body as unknown as Feed<CitibikeData> });
              else if (ev.event === "history") dispatch({ type: "history", points: (body.citibike ?? []) as HistoryPoint[] });
            }
          }
          throw new Error("The connection closed.");
        } catch (err) {
          if (stop.signal.aborted) return;
          const message = err instanceof Error && err.name !== "AbortError" ? err.message : "No data received; reconnecting.";
          dispatch({ type: "status", status: "reconnecting", message });
        } finally {
          clearTimeout(watchdog);
          stop.signal.removeEventListener("abort", abortLink);
        }
        await sleep(delay, stop.signal);
        delay = Math.min(delay * 2, 30_000);
      }
    })();
    return () => stop.abort();
  }, [url]);

  return state;
}
