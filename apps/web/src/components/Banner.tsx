import type { Schemas } from "../api/client";
import { addDays } from "../lib/format";

/** Always visible: says whether the numbers on screen are real or synthetic test data. */
export function DataBanner({ meta }: { meta: Schemas["Meta"] }) {
  const synthetic = meta.synthetic || meta.mode === "sample";
  const first = meta.data_start.slice(0, 10);
  // data_end is exclusive and a naive local timestamp: plain calendar arithmetic, no timezones.
  const last = addDays(meta.data_end.slice(0, 10), -1);
  return (
    <div
      className={synthetic ? "banner banner-synthetic" : "banner banner-real"}
      role="region"
      aria-label="Data source"
    >
      <strong>{meta.data_label.toUpperCase()}</strong>
      <span>
        {synthetic
          ? " – generated for tests and demos; these are not real trips."
          : ` – NYC TLC yellow taxis, ${first} to ${last}.`}
      </span>
    </div>
  );
}
