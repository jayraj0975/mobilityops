import { useCallback, useEffect, useState } from "react";

export const PUNE_ROUTES = [
  { id: "overview", label: "Overview" },
  { id: "map", label: "Map" },
  { id: "forecast", label: "Forecast" },
  { id: "events", label: "Events" },
  { id: "quality", label: "Data quality" },
  { id: "analyst", label: "Analyst" },
  { id: "method", label: "Method" },
] as const;
export type PuneRouteId = (typeof PUNE_ROUTES)[number]["id"];

const read = (): PuneRouteId => {
  const id = window.location.hash.replace(/^#\/?/, "");
  return PUNE_ROUTES.some((r) => r.id === id) ? (id as PuneRouteId) : "overview";
};

export function usePuneRoute(): [PuneRouteId, (id: PuneRouteId) => void] {
  const [route, setRoute] = useState<PuneRouteId>(read);
  useEffect(() => {
    const on = () => setRoute(read());
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  const go = useCallback((id: PuneRouteId) => {
    window.location.hash = `/${id}`;
  }, []);
  return [route, go];
}
