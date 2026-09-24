import { useEffect, useState } from "react";

/** "just now", "42 s ago", "5 min ago", "3 h ago", "over a day ago". */
export function ageText(seconds: number | null | undefined): string {
  if (seconds == null || !Number.isFinite(seconds)) return "never";
  const s = Math.max(0, Math.round(seconds));
  if (s < 5) return "just now";
  if (s < 90) return `${s} s ago`;
  if (s < 90 * 60) return `${Math.round(s / 60)} min ago`;
  if (s < 36 * 3600) return `${Math.round(s / 3600)} h ago`;
  return "over a day ago";
}

/** Re-render every ``ms`` so ages keep counting between updates. */
export function useNow(ms = 1000): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), ms);
    return () => clearInterval(t);
  }, [ms]);
  return now;
}

/** Wall-clock hh:mm of a naive local timestamp ("2026-09-24T21:17:25"): shown as written. */
export function clock(iso: string): string {
  const m = /T(\d{2}):(\d{2})/.exec(iso);
  return m ? `${m[1]}:${m[2]}` : iso;
}

/** The instant "iso" names, for ages; server times carry a Z or offset. */
export function instant(iso: string | null | undefined): number | null {
  if (!iso) return null;
  const t = Date.parse(iso);
  return Number.isNaN(t) ? null : t;
}
