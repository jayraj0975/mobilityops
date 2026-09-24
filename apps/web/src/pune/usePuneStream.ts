import { useEffect, useReducer, useState } from "react";
import { startSse, type LinkStatus } from "../lib/sseClient";
import type { Snapshot } from "./types";

export type Link = LinkStatus | "offline";

export interface StreamState {
  link: Link;
  snapshot?: Snapshot;
  /** Client clock (ms) when the newest snapshot arrived. */
  snapshotAt?: number;
  /** Client clock (ms) of the newest message of any kind (heartbeats count). */
  lastMessageAt?: number;
  /** server time minus client time at the newest message; corrects for a wrong local clock. */
  offsetMs: number;
  workerFresh?: string;
  unavailable?: boolean;
  message?: string;
}

type Action =
  | { type: "status"; status: Link; message?: string }
  | { type: "hello"; snapshot: Snapshot | null; serverTime: string; available: boolean; at: number }
  | { type: "snapshot"; snapshot: Snapshot; at: number }
  | { type: "heartbeat"; serverTime: string; worker: string; at: number };

const skew = (serverTime: string, at: number) => {
  const t = Date.parse(serverTime);
  return Number.isNaN(t) ? 0 : t - at;
};

export function streamReducer(state: StreamState, a: Action): StreamState {
  switch (a.type) {
    case "status":
      return { ...state, link: a.status, message: a.message };
    case "hello":
      return {
        ...state,
        link: "live",
        message: undefined,
        unavailable: !a.available,
        snapshot: a.snapshot ?? state.snapshot,
        snapshotAt: a.snapshot ? a.at : state.snapshotAt,
        lastMessageAt: a.at,
        offsetMs: skew(a.serverTime, a.at),
      };
    case "snapshot":
      return {
        ...state,
        link: "live",
        message: undefined,
        unavailable: false,
        snapshot: a.snapshot,
        snapshotAt: a.at,
        lastMessageAt: a.at,
        offsetMs: skew(a.snapshot.server_time, a.at),
      };
    case "heartbeat":
      return {
        ...state,
        lastMessageAt: a.at,
        workerFresh: a.worker,
        offsetMs: skew(a.serverTime, a.at),
      };
  }
}

/**
 * The live state of Pune: one server-sent event stream, kept alive with automatic reconnection.
 * ``link`` is the connection's own health (separate from the freshness of the data it carries).
 */
export function usePuneStream(url = "/api/v1/state/stream"): StreamState {
  const [state, dispatch] = useReducer(streamReducer, { link: "connecting", offsetMs: 0 });
  const [generation, setGeneration] = useState(0);

  useEffect(() => {
    const goOffline = () => dispatch({ type: "status", status: "offline", message: "This device is offline." });
    const comeOnline = () => setGeneration((g) => g + 1);
    window.addEventListener("offline", goOffline);
    window.addEventListener("online", comeOnline);
    return () => {
      window.removeEventListener("offline", goOffline);
      window.removeEventListener("online", comeOnline);
    };
  }, []);

  useEffect(() => {
    if (!navigator.onLine) {
      dispatch({ type: "status", status: "offline", message: "This device is offline." });
      return;
    }
    return startSse(url, {
      silenceMs: 30_000, // heartbeats every 10 s: three misses mean the link is dead
      onStatus: (status, message) => dispatch({ type: "status", status, message }),
      onEvent: (event, data) => {
        const at = Date.now();
        const body = data as Record<string, unknown>;
        if (event === "hello")
          dispatch({
            type: "hello",
            snapshot: (body.snapshot as Snapshot | null) ?? null,
            serverTime: String(body.server_time),
            available: body.available === true,
            at,
          });
        else if (event === "snapshot") dispatch({ type: "snapshot", snapshot: body as unknown as Snapshot, at });
        else if (event === "heartbeat") {
          const worker = (body.worker as { freshness?: string } | undefined)?.freshness ?? "OFFLINE";
          dispatch({ type: "heartbeat", serverTime: String(body.server_time), worker, at });
        }
      },
    });
  }, [url, generation]);

  return state;
}
