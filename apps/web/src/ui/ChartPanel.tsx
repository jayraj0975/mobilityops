import { useId, type ReactNode } from "react";
import type { Freshness } from "../pune/types";
import { DataClassTag } from "./DataClassTag";
import { FreshnessIndicator } from "./FreshnessIndicator";

/** A titled panel for a chart or table: says what kind of data it shows and how fresh it is. */
export function ChartPanel({
  title,
  subtitle,
  kind,
  freshness,
  ageSeconds,
  actions,
  children,
  footer,
}: {
  title: string;
  subtitle?: string;
  kind?: string;
  freshness?: Freshness;
  ageSeconds?: number | null;
  actions?: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
}) {
  const id = useId();
  return (
    <section className="panel" aria-labelledby={id}>
      <header className="panel-head">
        <div>
          <h2 id={id}>{title}</h2>
          {subtitle && <p className="muted small">{subtitle}</p>}
        </div>
        <div className="panel-tags">
          {kind && <DataClassTag kind={kind} />}
          {freshness && <FreshnessIndicator state={freshness} ageSeconds={ageSeconds} />}
          {actions}
        </div>
      </header>
      <div className="panel-body">{children}</div>
      {footer && <footer className="panel-foot small muted">{footer}</footer>}
    </section>
  );
}
