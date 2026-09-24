import type { ReactNode } from "react";
import type { Freshness } from "../pune/types";
import { DataClassTag } from "./DataClassTag";
import { FreshnessIndicator } from "./FreshnessIndicator";

export interface MetricCardProps {
  label: string;
  value: ReactNode;
  unit?: string;
  /** e.g. "−12% vs forecast"; the sign is in the text, the tone is decoration. */
  delta?: string;
  deltaTone?: "up" | "down" | "flat";
  note?: string;
  kind?: string;
  modelled?: boolean;
  freshness?: Freshness;
  ageSeconds?: number | null;
}

export function MetricCard(p: MetricCardProps) {
  return (
    <article className="metric" aria-label={p.label}>
      <header className="metric-head">
        <h3>{p.label}</h3>
        {p.kind && <DataClassTag kind={p.kind} modelled={p.modelled} />}
      </header>
      <p className="metric-value">
        {p.value}
        {p.unit && <span className="metric-unit"> {p.unit}</span>}
      </p>
      {p.delta && <p className={`metric-delta metric-delta-${p.deltaTone ?? "flat"}`}>{p.delta}</p>}
      {p.note && <p className="metric-note">{p.note}</p>}
      {p.freshness && (
        <footer>
          <FreshnessIndicator state={p.freshness} ageSeconds={p.ageSeconds} />
        </footer>
      )}
    </article>
  );
}
