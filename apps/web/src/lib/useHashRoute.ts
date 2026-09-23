import { useCallback, useEffect, useState } from "react";

export const ROUTES = [
  { id: "overview", label: "Overview" },
  { id: "demand", label: "Demand" },
  { id: "forecast", label: "Forecast" },
  { id: "anomalies", label: "Anomalies" },
  { id: "scenarios", label: "Scenarios" },
  { id: "analyst", label: "Analyst" },
] as const;
export type RouteId = (typeof ROUTES)[number]["id"];

const read = (): RouteId => {
  const id = window.location.hash.replace(/^#\/?/, "");
  return ROUTES.some((r) => r.id === id) ? (id as RouteId) : "overview";
};

export function useHashRoute(): [RouteId, (id: RouteId) => void] {
  const [route, setRoute] = useState<RouteId>(read);
  useEffect(() => {
    const on = () => setRoute(read());
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  const go = useCallback((id: RouteId) => {
    window.location.hash = `/${id}`;
  }, []);
  return [route, go];
}
