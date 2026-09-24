import { Suspense, lazy, useEffect, useMemo, useRef, useState } from "react";
import { state } from "../api/client";
import type { Schemas } from "../api/client";
import { ErrorBoundary } from "../components/ErrorBoundary";
import { useAsync } from "../lib/useAsync";
import { FreshnessIndicator, LoadingSkeleton, StatusBadge } from "../ui";
import "../ops.css";
import { PuneCtx, type PuneData } from "./PuneContext";
import { clock, useNow } from "./time";
import { useTheme } from "./theme";
import { PUNE_ROUTES, usePuneRoute } from "./usePuneRoute";
import { usePuneStream } from "./usePuneStream";
import type { MapLayer, TimeSelector } from "./types";

const CommandCenter = lazy(() => import("./pages/CommandCenter").then((m) => ({ default: m.CommandCenter })));
const MapPage = lazy(() => import("./pages/MapPage").then((m) => ({ default: m.MapPage })));
const ForecastPage = lazy(() => import("./pages/ForecastPage").then((m) => ({ default: m.ForecastPage })));
const EventsPage = lazy(() => import("./pages/EventsPage").then((m) => ({ default: m.EventsPage })));
const QualityPage = lazy(() => import("./pages/QualityPage").then((m) => ({ default: m.QualityPage })));
const MethodPage = lazy(() => import("./pages/MethodPage").then((m) => ({ default: m.MethodPage })));
const Analyst = lazy(() => import("../pages/Analyst").then((m) => ({ default: m.Analyst })));

const THEME_LABEL = { auto: "Theme: system", light: "Theme: light", dark: "Theme: dark" } as const;

/** The reason the numbers may not be current, in words, or null when everything is fine. */
export function connectionNotice(
  link: string,
  freshness: string | undefined,
  workerFresh: string | undefined,
  lastAt: string | null,
): string | null {
  const at = lastAt ? ` The numbers shown are from ${lastAt}.` : "";
  if (link === "offline") return `This device is offline.${at}`;
  if (link === "connecting") return null;
  if (link === "reconnecting") return `Reconnecting to the server.${at} They may be out of date.`;
  if (workerFresh === "OFFLINE" || workerFresh === "STALE")
    return `The ingestion worker has stopped, so nothing new is arriving.${at} Values are held from its last run.`;
  if (freshness === "STALE" || freshness === "OFFLINE")
    return `One or more data sources have stopped updating.${at} See Data quality for which.`;
  return null;
}

export default function PuneApp({ meta }: { meta: Schemas["Meta"] }) {
  const [route, go] = usePuneRoute();
  const [theme, cycleTheme] = useTheme();
  const stream = usePuneStream();
  const now = useNow(1000);
  const [selector, setSelector] = useState<TimeSelector>("now");
  const [layer, setLayer] = useState<MapLayer>("ratio");
  const [zoneId, setZoneId] = useState<number | null>(null);
  const geometry = useAsync((s) => state.geometry(s), []);
  const seq = stream.snapshot?.seq ?? 0;
  const rest = useAsync(
    (s) => (selector === "now" ? Promise.resolve(null) : state.snapshot(selector, s)),
    [selector, seq],
  );
  const snapshot = selector === "now" ? stream.snapshot : (rest.data ?? undefined);
  const elapsed = stream.snapshotAt ? Math.max(0, (now - stream.snapshotAt) / 1000) : 0;

  const main = useRef<HTMLElement>(null);
  const first = useRef(true);
  useEffect(() => {
    if (first.current) {
      first.current = false;
      return;
    }
    main.current?.focus();
  }, [route]);

  const data: PuneData = useMemo(
    () => ({
      stream,
      snapshot,
      snapshotError: rest.error,
      geometry: geometry.data,
      geometryError: geometry.error,
      selector,
      setSelector,
      layer,
      setLayer,
      zoneId,
      setZoneId,
      now,
      elapsed,
      seq,
    }),
    [stream, snapshot, rest.error, geometry.data, geometry.error, selector, layer, zoneId, now, elapsed, seq],
  );

  const lastAt = stream.snapshot ? clock(stream.snapshot.window_end) : null;
  const notice = connectionNotice(stream.link, stream.snapshot?.freshness, stream.workerFresh ?? stream.snapshot?.worker.freshness, lastAt);
  const s = stream.snapshot;
  return (
    <PuneCtx.Provider value={data}>
      <a className="skip" href="#main">Skip to content</a>
      <header className="ops-top">
        <div className="ops-brand">
          <h1>MobilityOps <span className="ops-city">{meta.city}</span></h1>
          <p className="muted small">Real-time urban mobility platform</p>
        </div>
        <div className="ops-status" role="group" aria-label="System status">
          <span className="ops-status-item"><span className="muted small">Data</span> {s ? <FreshnessIndicator state={s.freshness} showAge={false} /> : <StatusBadge tone="neutral">waiting</StatusBadge>}</span>
          <span className="ops-status-item"><span className="muted small">Worker</span> {s ? <FreshnessIndicator state={stream.workerFresh ? (stream.workerFresh as typeof s.worker.freshness) : s.worker.freshness} showAge={false} /> : <StatusBadge tone="neutral">unknown</StatusBadge>}</span>
          <span className="ops-status-item"><span className="muted small">Link</span> <StatusBadge tone={stream.link === "live" ? "ok" : stream.link === "offline" ? "bad" : "warn"}>{stream.link === "live" ? "CONNECTED" : stream.link.toUpperCase()}</StatusBadge></span>
          <button type="button" className="ops-theme" onClick={cycleTheme}>{THEME_LABEL[theme]}</button>
        </div>
      </header>
      <div className="ops-label" role="region" aria-label="Data source">
        <strong>SIMULATED DEMAND</strong>
        <span>
          {" "}on real weather and geography. Pune publishes no open trip data, so trip counts are generated by a model.
          Nothing here describes real Pune traffic.
        </span>
      </div>
      {notice && <div className="ops-notice" role="status">{notice}</div>}
      <nav aria-label="Sections" className="ops-nav">
        <ul>
          {PUNE_ROUTES.map((r) => (
            <li key={r.id}>
              <button type="button" aria-current={route === r.id ? "page" : undefined} onClick={() => go(r.id)}>{r.label}</button>
            </li>
          ))}
        </ul>
      </nav>
      <main id="main" ref={main} tabIndex={-1} className="ops-main">
        <ErrorBoundary key={route}>
          <h2 className="sr-only">{PUNE_ROUTES.find((r) => r.id === route)?.label}</h2>
          <Suspense fallback={<LoadingSkeleton lines={5} height={300} />}>
            {route === "overview" && <CommandCenter />}
            {route === "map" && <MapPage />}
            {route === "forecast" && <ForecastPage />}
            {route === "events" && <EventsPage />}
            {route === "quality" && <QualityPage />}
            {route === "analyst" && <Analyst />}
            {route === "method" && <MethodPage />}
          </Suspense>
        </ErrorBoundary>
      </main>
      <footer className="ops-foot small muted">
        Weather data by Open-Meteo.com and MET Norway (CC BY 4.0). Map data © OpenStreetMap contributors (ODbL). Demand is simulated;
        forecasts are estimates, not guarantees; optimisation outputs are simulations under stated assumptions.
      </footer>
    </PuneCtx.Provider>
  );
}
