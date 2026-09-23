import type { ReactNode } from "react";
import { ApiError } from "../api/client";
import type { AsyncState } from "../lib/useAsync";

export function Loading({ what = "data" }: { what?: string }) {
  return (
    <p role="status" className="muted">
      Loading {what}…
    </p>
  );
}

export function ErrorState({ error, onRetry }: { error: Error; onRetry?: () => void }) {
  const api = error instanceof ApiError ? error : null;
  const notReady = api?.code === "not_ready";
  return (
    <div role="alert" className={notReady ? "notice" : "notice notice-error"}>
      <strong>{notReady ? "Not generated yet" : "Something went wrong"}</strong>
      <p>{error.message}</p>
      {api?.requestId && <p className="muted small">Request id: {api.requestId}</p>}
      {onRetry && (
        <button type="button" onClick={onRetry}>
          Try again
        </button>
      )}
    </div>
  );
}

/** Render loading, error, or the data, so no page ever shows stale placeholder numbers. */
export function Async<T>({
  state,
  what,
  children,
}: {
  state: AsyncState<T>;
  what?: string;
  children: (data: T) => ReactNode;
}) {
  if (state.error) return <ErrorState error={state.error} onRetry={state.reload} />;
  if (state.data === undefined) return <Loading what={what} />;
  return <>{children(state.data)}</>;
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="muted">{children}</p>;
}
