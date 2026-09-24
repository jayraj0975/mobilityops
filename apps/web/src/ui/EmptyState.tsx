import type { ReactNode } from "react";

export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="state state-empty" role="status">
      <strong>{title}</strong>
      {children && <p>{children}</p>}
    </div>
  );
}
