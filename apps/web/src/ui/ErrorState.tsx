import type { ReactNode } from "react";

export function ErrorState({
  title,
  children,
  onRetry,
}: {
  title: string;
  children?: ReactNode;
  onRetry?: () => void;
}) {
  return (
    <div className="state state-error" role="alert">
      <strong>{title}</strong>
      {children && <p>{children}</p>}
      {onRetry && (
        <button type="button" onClick={onRetry}>
          Try again
        </button>
      )}
    </div>
  );
}
