const HELP: Record<string, string> = {
  LIVE: "Observations delivered within seconds of being made.",
  "NEAR-REAL-TIME": "The latest model or observation step, minutes old by design.",
  RECENT: "Within the last day or so.",
  HISTORICAL: "Complete past data.",
  PREDICTED: "A forecast. Always shown with a range.",
  SIMULATED: "Produced by a model of how demand behaves, not observed. No real Pune trip data is used.",
  STATIC: "Does not change with time.",
};

/** What kind of data this is. SIMULATED is drawn loudest so it cannot be mistaken for a measurement. */
export function DataClassTag({ kind, modelled = false }: { kind: string; modelled?: boolean }) {
  const cls = kind.toLowerCase().replace(/[^a-z]+/g, "-");
  return (
    <span className={`dctag dctag-${cls}`} title={HELP[kind] ?? kind}>
      {kind}
      {modelled && kind !== "SIMULATED" ? " · MODELLED" : ""}
    </span>
  );
}
