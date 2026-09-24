import { useCallback, useEffect, useState } from "react";

export interface AsyncState<T> {
  data: T | undefined;
  error: Error | undefined;
  loading: boolean;
  reload: () => void;
}

interface Settled<T> {
  key: string;
  data?: T;
  error?: Error;
}

/**
 * Run an async loader when ``deps`` change; cancels the request when they change or on unmount.
 *
 * ``deps`` must be primitives (strings, numbers, booleans, undefined): they form the request key.
 * ``loading`` is derived (the stored result belongs to an older key), so no state is written
 * synchronously inside the effect. Previous data stays visible while a new request is in flight.
 */
export function useAsync<T>(
  loader: (signal: AbortSignal) => Promise<T>,
  deps: readonly (string | number | boolean | null | undefined)[],
): AsyncState<T> {
  const [tick, setTick] = useState(0);
  const key = `${tick}|${JSON.stringify(deps)}`;
  const [settled, setSettled] = useState<Settled<T>>({ key: "" });
  const reload = useCallback(() => setTick((t) => t + 1), []);

  useEffect(() => {
    const ctl = new AbortController();
    loader(ctl.signal)
      .then((data) => {
        if (!ctl.signal.aborted) setSettled({ key, data });
      })
      .catch((error: unknown) => {
        if (ctl.signal.aborted) return;
        setSettled((s) => ({
          key,
          data: s.data,
          error: error instanceof Error ? error : new Error(String(error)),
        }));
      });
    return () => ctl.abort();
    // The loader closes over the values in ``deps``; ``key`` identifies the request.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  const current = settled.key === key;
  return {
    data: settled.data,
    error: current ? settled.error : undefined,
    loading: !current,
    reload,
  };
}
