import { authHeaders } from "../api/key";
import { parseSse } from "./sse";

export type LinkStatus = "connecting" | "live" | "reconnecting";

export interface SseHandlers {
  onEvent: (event: string, data: unknown) => void;
  onStatus: (status: LinkStatus, message?: string) => void;
  /** Reconnect when nothing (not even a keep-alive comment) arrives for this long. */
  silenceMs?: number;
}

const sleep = (ms: number, signal: AbortSignal) =>
  new Promise<void>((resolve) => {
    const t = setTimeout(resolve, ms);
    signal.addEventListener(
      "abort",
      () => {
        clearTimeout(t);
        resolve();
      },
      { once: true },
    );
  });

/**
 * Follow a server-sent event stream and keep following it: reconnect with backoff (1 s, doubling to
 * 30 s), restart it when it goes silent, and report each transition. ``fetch`` streaming is used
 * rather than ``EventSource`` so the API key header can be sent. Returns a function that stops it.
 */
export function startSse(url: string, h: SseHandlers): () => void {
  const stop = new AbortController();
  const silenceMs = h.silenceMs ?? 30_000;
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
        watchdog = setTimeout(() => link.abort(), silenceMs);
      };
      try {
        h.onStatus(attempt === 0 ? "connecting" : "reconnecting");
        attempt += 1;
        arm();
        const res = await fetch(url, {
          signal: link.signal,
          headers: { Accept: "text/event-stream", ...authHeaders() },
        });
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
        let announced = false;
        for (;;) {
          const { done, value } = await reader.read();
          if (done) break;
          arm();
          buffer += decoder.decode(value, { stream: true });
          const parsed = parseSse(buffer);
          buffer = parsed.rest;
          for (const ev of parsed.events) {
            if (!announced) {
              announced = true;
              h.onStatus("live");
            }
            h.onEvent(ev.event, JSON.parse(ev.data) as unknown);
          }
        }
        throw new Error("The connection closed.");
      } catch (err) {
        if (stop.signal.aborted) return;
        const message =
          err instanceof Error && err.name !== "AbortError"
            ? err.message
            : "No data received; reconnecting.";
        h.onStatus("reconnecting", message);
      } finally {
        clearTimeout(watchdog);
        stop.signal.removeEventListener("abort", abortLink);
      }
      await sleep(delay, stop.signal);
      delay = Math.min(delay * 2, 30_000);
    }
  })();
  return () => stop.abort();
}
