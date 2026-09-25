import type { Schemas } from "../api/client";
import { addDays } from "../lib/format";

/** A hosted demo's own caveat (for example that a free service sleeps when idle), when the operator set one. */
export function DemoNotice({ notice, className }: { notice?: string | null; className?: string }) {
  if (!notice) return null;
  return (
    <p className={className ?? "banner banner-notice"} role="note" aria-label="About this demo">
      {notice}
    </p>
  );
}

/** Always visible: says whether the numbers on screen are real or synthetic test data. */
export function DataBanner({ meta }: { meta: Schemas["Meta"] }) {
  const synthetic = meta.synthetic || meta.mode === "sample";
  const first = meta.data_start.slice(0, 10);
  // data_end is exclusive and a naive local timestamp: plain calendar arithmetic, no timezones.
  const last = addDays(meta.data_end.slice(0, 10), -1);
  return (
    <>
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
      <DemoNotice notice={meta.demo_notice} />
    </>
  );
}
