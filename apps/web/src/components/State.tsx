import { useEffect, useState, type ReactNode } from "react";
import { ApiError } from "../api/client";
import { setApiKey } from "../api/key";
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

/** Shown when a self-hosted server answers 401: the person can enter the key it was started with. */
function ApiKeyForm({ onSaved }: { onSaved?: () => void }) {
  const [value, setValue] = useState("");
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        setApiKey(value);
        onSaved?.();
      }}
    >
      <label>
        API key{" "}
        <input type="password" autoComplete="off" value={value} onChange={(e) => setValue(e.target.value)} />
      </label>{" "}
      <button type="submit">Save and retry</button>
      <p className="muted small">The key stays in this browser only. It is the MOBILITYOPS_API_KEY the server was started with.</p>
    </form>
  );
}

export function ErrorState({ error, onRetry }: { error: Error; onRetry?: () => void }) {
  const api = error instanceof ApiError ? error : null;
  const needsKey = api?.status === 401;
  const notReady = api?.code === "not_ready";
  return (
    <div role="alert" className={notReady ? "notice" : "notice notice-error"}>
      <strong>{needsKey ? "This server needs an API key" : notReady ? "Not generated yet" : "Something went wrong"}</strong>
      <p>{needsKey ? "The server refused the request because no valid API key was sent." : error.message}</p>
      {needsKey && <ApiKeyForm onSaved={onRetry} />}
      {api?.requestId && <p className="muted small">Request id: {api.requestId}</p>}
      {onRetry && !needsKey && (
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
