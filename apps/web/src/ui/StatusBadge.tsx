import type { ReactNode } from "react";

export type Tone = "ok" | "warn" | "bad" | "info" | "neutral";

const GLYPH: Record<Tone, string> = { ok: "●", warn: "◐", bad: "▲", info: "◆", neutral: "○" };

/** A short status label. The glyph repeats the meaning of the colour so colour is never the only cue. */
export function StatusBadge({
  tone,
  children,
  title,
}: {
  tone: Tone;
  children: ReactNode;
  title?: string;
}) {
  return (
    <span className={`badge2 badge2-${tone}`} title={title}>
      <span aria-hidden="true">{GLYPH[tone]}</span> {children}
    </span>
  );
}
