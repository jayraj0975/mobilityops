import { useEffect, useRef } from "react";
import { api } from "./api/client";
import { DataBanner } from "./components/Banner";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { Async } from "./components/State";
import { useAsync } from "./lib/useAsync";
import { ROUTES, useHashRoute } from "./lib/useHashRoute";
import { Analyst } from "./pages/Analyst";
import { Anomalies } from "./pages/Anomalies";
import { Demand } from "./pages/Demand";
import { Forecast } from "./pages/Forecast";
import { Overview } from "./pages/Overview";
import { Scenarios } from "./pages/Scenarios";

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
                  {route === "overview" && <Overview meta={m} />}
                  {route === "demand" && <Demand meta={m} zones={z} />}
                  {route === "forecast" && <Forecast zones={z} />}
                  {route === "anomalies" && <Anomalies />}
                  {route === "scenarios" && <Scenarios zones={z} />}
                  {route === "analyst" && <Analyst />}
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
