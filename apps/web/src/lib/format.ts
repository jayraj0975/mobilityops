export const fmtInt = (x: number | null | undefined): string =>
  x == null || Number.isNaN(x) ? "n/a" : Math.round(x).toLocaleString("en-US");

export const fmtNum = (x: number | null | undefined, digits = 1): string =>
  x == null || Number.isNaN(x)
    ? "n/a"
    : x.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits });

export const fmtPct = (x: number | null | undefined, digits = 1): string =>
  x == null || Number.isNaN(x) ? "n/a" : `${(100 * x).toFixed(digits)}%`;

export const fmtDateTime = (iso: string): string => {
  const d = new Date(iso);
  return Number.isNaN(d.getTime())
    ? iso
    : d.toLocaleString("en-US", {
        weekday: "short",
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
        hour12: false,
      });
};

/** Local calendar date as YYYY-MM-DD, without timezone shifts (timestamps are naive local time). */
export const isoDate = (d: Date): string => {
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
};

export const addDays = (iso: string, days: number): string => {
  const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
  return isoDate(new Date(y ?? 1970, (m ?? 1) - 1, (d ?? 1) + days));
};
