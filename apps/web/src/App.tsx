import { Suspense, lazy, useEffect, useRef } from "react";
import { api } from "./api/client";
import { DataBanner } from "./components/Banner";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { Async, Loading } from "./components/State";
import { useAsync } from "./lib/useAsync";
import { ROUTES, useHashRoute } from "./lib/useHashRoute";

// Each section is its own chunk, so the first paint downloads the shell only, and the charting
// library loads with the first section that draws a chart.
const Overview = lazy(() => import("./pages/Overview").then((m) => ({ default: m.Overview })));
const Live = lazy(() => import("./pages/Live").then((m) => ({ default: m.Live })));
const Demand = lazy(() => import("./pages/Demand").then((m) => ({ default: m.Demand })));
const Forecast = lazy(() => import("./pages/Forecast").then((m) => ({ default: m.Forecast })));
const Anomalies = lazy(() => import("./pages/Anomalies").then((m) => ({ default: m.Anomalies })));
const Scenarios = lazy(() => import("./pages/Scenarios").then((m) => ({ default: m.Scenarios })));
const Analyst = lazy(() => import("./pages/Analyst").then((m) => ({ default: m.Analyst })));
const About = lazy(() => import("./pages/About").then((m) => ({ default: m.About })));
const PuneApp = lazy(() => import("./pune/PuneApp"));

export default function App() {
  const [route, go] = useHashRoute();
  const meta = useAsync((s) => api.meta(s), []);
  const zones = useAsync((s) => api.zones(s), []);
  const main = useRef<HTMLElement>(null);
  const first = useRef(true);

  // Move focus to the content when the section changes, but not on first load: that would take
  // the first Tab stop away from the "Skip to content" link.
  useEffect(() => {
    if (first.current) {
      first.current = false;
      return;
    }
    main.current?.focus();
  }, [route]);

  // Pune has its own real-time console; the New York analytics UI stays for the other modes.
  if (meta.data?.mode === "pune")
    return (
      <Suspense fallback={<Loading what="the console" />}>
        <PuneApp meta={meta.data} />
      </Suspense>
    );

  return (
    <>
      <a className="skip" href="#main">
        Skip to content
      </a>
      <header className="top">
        <h1>MobilityOps</h1>
        <p className="muted">Urban mobility intelligence: NYC yellow-taxi demand, forecasts, anomalies and simulated scenarios.</p>
        {meta.data && <DataBanner meta={meta.data} />}
        <nav aria-label="Sections">
          <ul className="nav">
            {ROUTES.map((r) => (
              <li key={r.id}>
                <button type="button" aria-current={route === r.id ? "page" : undefined} onClick={() => go(r.id)}>
                  {r.label}
                </button>
              </li>
            ))}
          </ul>
        </nav>
      </header>
      <main id="main" ref={main} tabIndex={-1}>
        <Async state={meta} what="app">
          {(m) => (
            <Async state={zones} what="zones">
              {(z) => (
                <ErrorBoundary key={route}>
                  <h2 className="sr-only">{ROUTES.find((r) => r.id === route)?.label}</h2>
                  <Suspense fallback={<Loading what="section" />}>
                  {route === "overview" && <Overview meta={m} />}
                  {route === "live" && <Live />}
                  {route === "demand" && <Demand meta={m} zones={z} />}
                  {route === "forecast" && <Forecast zones={z} />}
                  {route === "anomalies" && <Anomalies />}
                  {route === "scenarios" && <Scenarios zones={z} />}
                  {route === "analyst" && <Analyst />}
                  {route === "about" && <About meta={m} />}
                  </Suspense>
                </ErrorBoundary>
              )}
            </Async>
          )}
        </Async>
      </main>
      <footer className="foot muted small">
        Synthetic sample data is always labelled. Optimization outputs are simulations under stated assumptions. Forecasts are
        estimates, not guarantees.
      </footer>
    </>
  );
}
