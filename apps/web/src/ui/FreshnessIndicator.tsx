import type { Freshness } from "../pune/types";
import { ageText } from "../pune/time";
import { StatusBadge, type Tone } from "./StatusBadge";

const TONE: Record<Freshness, Tone> = {
  LIVE: "ok",
  DELAYED: "warn",
  STALE: "bad",
  OFFLINE: "bad",
  DISABLED: "neutral",
  NOT_PERIODIC: "neutral",
};

export const FRESHNESS_HELP: Record<Freshness, string> = {
  LIVE: "Arriving on schedule.",
  DELAYED: "Later than expected, but recent enough to trust.",
  STALE: "Old. Shown for reference; not current.",
  OFFLINE: "Nothing recent has arrived.",
  DISABLED: "Not configured. Nothing is being fetched.",
  NOT_PERIODIC: "Static or historical: freshness does not apply.",
};

const LABEL: Record<Freshness, string> = {
  LIVE: "LIVE",
  DELAYED: "DELAYED",
  STALE: "STALE",
  OFFLINE: "OFFLINE",
  DISABLED: "NOT CONFIGURED",
  NOT_PERIODIC: "STATIC",
};

/** Freshness of one thing, with how old it is. The state is computed by the server from timestamps. */
export function FreshnessIndicator({
  state,
  ageSeconds,
  showAge = true,
}: {
  state: Freshness;
  ageSeconds?: number | null;
  showAge?: boolean;
}) {
  const withAge = showAge && (state === "LIVE" || state === "DELAYED" || state === "STALE" || state === "OFFLINE");
  return (
    <StatusBadge tone={TONE[state]} title={FRESHNESS_HELP[state]}>
      {LABEL[state]}
      {withAge && ageSeconds != null ? <span className="muted"> · {ageText(ageSeconds)}</span> : null}
    </StatusBadge>
  );
}
