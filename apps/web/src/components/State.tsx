import { useEffect, useState, type ReactNode } from "react";
import { ApiError } from "../api/client";
import type { AsyncState } from "../lib/useAsync";

/** After this long a request is slow enough that the person deserves an explanation. */
export const SLOW_LOAD_MS = 4000;

export function Loading({ what = "data" }: { what?: string }) {
  const [slow, setSlow] = useState(false);
  useEffect(() => {
    const t = setTimeout(() => setSlow(true), SLOW_LOAD_MS);
    return () => clearTimeout(t);
  }, []);
  return (
    <p role="status" className="muted">
      Loading {what}…
      {slow && (
        <>
          {" "}
          This is taking longer than usual. The public demo runs on a free plan and can be slow
          after a quiet period; it will appear as soon as the server responds.
        </>
      )}
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
